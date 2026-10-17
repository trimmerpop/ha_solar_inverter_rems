"""Solar Inverter REMS sensor platform."""

from __future__ import annotations

import logging
import struct
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .bridge import acquire_bridge, fetch_locked
from .const import (
    CONF_SLAVE_ID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAULT_BIT_MAP,
    OFFLINE_AFTER_FAILURES,
    SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class SolarInverterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator polling the inverter once for all sensor entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        ip: str,
        port: int,
        slave_id: int,
        scan_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {ip}:{port}",
            config_entry=entry,
            update_interval=scan_interval,
            always_update=False,
        )
        self._ip = ip
        self._port = port
        self._slave_id = slave_id
        self._lock = acquire_bridge(ip, port)
        self._last_time = time.monotonic()
        self._total_grid_energy = 0.0
        self._consecutive_failures = 0

    @property
    def ip(self) -> str:
        """Return the bridge IP address."""
        return self._ip

    @property
    def port(self) -> int:
        """Return the bridge TCP port."""
        return self._port

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and parse new data from the inverter."""
        # An inverter already confirmed offline (night / powered down) gets a
        # fast-fail probe so it does not hold the shared bridge lock with
        # full retries while the healthy inverters wait behind it.
        if self._consecutive_failures >= OFFLINE_AFTER_FAILURES:
            raw_data = await fetch_locked(
                self.hass,
                self._lock,
                self._ip,
                self._port,
                self._slave_id,
                retries=1,
                timeout=1.0,
                response_timeout=1.5,
                retry_delay=0.0,
            )
        else:
            raw_data = await fetch_locked(
                self.hass, self._lock, self._ip, self._port, self._slave_id
            )

        previous: dict[str, Any] = self.data or {}

        # Check for invalid zero total_power glitch: a frame full of zeros
        # (e.g. another inverter's chatter on the shared RS485 bus) must not
        # wipe out real readings. Treat it as a transient failure.
        if raw_data and len(raw_data) >= 26:
            try:
                probe_total_power = int.from_bytes(raw_data[16:24], "big")
                if probe_total_power == 0 and previous.get("total_power", 0) > 0:
                    self._consecutive_failures += 1
                    _LOGGER.warning(
                        "Inverter (slave %s) returned 0 for total_power while "
                        "previous value was %s. Keeping previous values "
                        "(failure %s/%s).",
                        self._slave_id,
                        previous.get("total_power"),
                        self._consecutive_failures,
                        OFFLINE_AFTER_FAILURES,
                    )
                    raise UpdateFailed("Glitched zero total_power frame")
            except UpdateFailed:
                raise
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("Error during early total_power probe: %s", e)

        # Time base only advances on successful polls (below). On transient
        # failures UpdateFailed is raised with _last_time untouched, so the
        # next successful poll integrates energy over the real gap without
        # writing zeros in between.
        current_time = time.monotonic()
        dt = current_time - self._last_time

        if not raw_data or len(raw_data) < 26:
            self._consecutive_failures += 1
            if self._consecutive_failures >= OFFLINE_AFTER_FAILURES:
                # Device is likely off (night time) or unreachable.
                # Advance the time base so the offline gap does not inflate
                # the next energy integration, then report 0 / "Inverter Off".
                self._last_time = current_time
                offline_data: dict[str, Any] = {
                    "pv_voltage": 0,
                    "pv_current": 0,
                    "pv_power": 0,
                    "grid_voltage": 0,
                    "grid_current": 0,
                    "grid_power": 0,
                    "power_factor": 0,
                    "grid_frequency": 0,
                    "inverter_fault": "Inverter Off",
                    "grid_accumulated_energy": round(self._total_grid_energy, 3),
                }
                if "total_power" in previous:
                    offline_data["total_power"] = previous["total_power"]
                return offline_data
            # Transient failure (bus contention with several inverters on one
            # bridge, line noise, single timeout): keep previous values by
            # raising UpdateFailed instead of writing zeros.
            _LOGGER.debug(
                "Transient fetch failure for slave %s "
                "(failure %s/%s). Keeping previous values.",
                self._slave_id,
                self._consecutive_failures,
                OFFLINE_AFTER_FAILURES,
            )
            raise UpdateFailed(
                f"Transient fetch failure for slave {self._slave_id}"
            )

        self._consecutive_failures = 0
        self._last_time = current_time
        current_grid_power = int.from_bytes(raw_data[10:12], "big")
        self._total_grid_energy += (current_grid_power * dt) / 3600000.0

        try:
            parsed_data: dict[str, Any] = {}
            parsed_data["pv_voltage"] = int.from_bytes(raw_data[0:2], "big")
            parsed_data["pv_current"] = int.from_bytes(raw_data[2:4], "big")
            parsed_data["pv_power"] = int.from_bytes(raw_data[4:6], "big")
            parsed_data["grid_voltage"] = int.from_bytes(raw_data[6:8], "big")
            parsed_data["grid_current"] = int.from_bytes(raw_data[8:10], "big")
            parsed_data["grid_power"] = int.from_bytes(raw_data[10:12], "big")
            parsed_data["power_factor"] = round(
                int.from_bytes(raw_data[12:14], "big") * 0.1, 1
            )
            parsed_data["grid_frequency"] = round(
                int.from_bytes(raw_data[14:16], "big") * 0.1, 1
            )
            # Raw value is in Wh, sensor unit is kWh.
            parsed_data["total_power"] = round(
                int.from_bytes(raw_data[16:24], "big") / 1000, 3
            )
            parsed_data["grid_accumulated_energy"] = round(self._total_grid_energy, 3)

            fault_code = int.from_bytes(raw_data[24:26], "big")
            faults = [
                message
                for bit, message in FAULT_BIT_MAP.items()
                if (fault_code >> bit) & 1
            ]

            parsed_data["inverter_fault"] = ", ".join(faults) if faults else "Normal"

            _LOGGER.debug("Successfully updated inverter data: %s", parsed_data)
            return parsed_data
        except (struct.error, IndexError) as e:
            _LOGGER.error(
                "Failed to parse inverter data: %s. Raw: %s",
                e,
                raw_data.hex() if raw_data else "None",
            )
            return previous


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Solar Inverter REMS sensors from a config entry."""
    config = {**config_entry.data, **config_entry.options}
    scan_interval_seconds = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = SolarInverterCoordinator(
        hass,
        config_entry,
        config[CONF_IP_ADDRESS],
        config[CONF_PORT],
        config[CONF_SLAVE_ID],
        timedelta(seconds=scan_interval_seconds),
    )
    config_entry.runtime_data = coordinator

    device_name = config.get(CONF_NAME) or config_entry.title or DEFAULT_NAME

    async_add_entities(
        SolarRS485Sensor(coordinator, config_entry.entry_id, device_name, sensor_type)
        for sensor_type in SENSOR_TYPES
    )

    # Start the first fetch in the background so setup/Home Assistant startup
    # is never blocked by an unreachable inverter (for example at night, when
    # the inverter is powered down). Entities simply report unavailable until
    # the first result arrives. The task is tied to the config entry and is
    # cancelled automatically on unload.
    config_entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        f"{DOMAIN} initial refresh",
    )


class SolarRS485Sensor(CoordinatorEntity[SolarInverterCoordinator], SensorEntity):
    """Representation of a Solar RS485 Sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarInverterCoordinator,
        entry_id: str,
        device_name: str,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type

        sensor_info = SENSOR_TYPES[sensor_type]
        self._attr_name = sensor_info[0]
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{sensor_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Ingeteam",
            model="Solar Inverter REMS",
        )
        self._attr_native_unit_of_measurement = sensor_info[1]
        self._attr_icon = sensor_info[2]
        self._attr_device_class = sensor_info[3]
        self._attr_state_class = sensor_info[4]

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this sensor."""
        return bool(self.coordinator.data) and self._sensor_type in self.coordinator.data

    @property
    def native_value(self) -> Any:
        """Return the current value from the coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._sensor_type)

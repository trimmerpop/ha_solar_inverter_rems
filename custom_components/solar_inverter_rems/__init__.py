"""The Solar Inverter REMS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .bridge import release_bridge
from .const import DOMAIN, PLATFORMS, SENSOR_TYPES

OLD_UNIQUE_ID_PREFIX = "solar_rs485_"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solar Inverter REMS from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = getattr(entry, "runtime_data", None)

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded and coordinator is not None:
        await coordinator.async_shutdown()
        release_bridge(coordinator.ip, coordinator.port)
        entry.runtime_data = None

    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version."""
    if entry.version > 2:
        # Downgrades are not supported.
        return False

    if entry.version == 1:
        # Migrate entity unique IDs from the old
        # ``solar_rs485_{ip}_{slave_id}_{sensor_type}`` format to the
        # entry based ``{DOMAIN}_{entry_id}_{sensor_type}`` format.
        @callback
        def _migrate_entity(reg_entry: er.RegistryEntry) -> dict[str, Any] | None:
            unique_id = reg_entry.unique_id
            if not unique_id or not unique_id.startswith(OLD_UNIQUE_ID_PREFIX):
                return None

            # Match the longest sensor type first so multi-word types
            # (e.g. ``grid_accumulated_energy``) are matched correctly.
            for sensor_type in sorted(SENSOR_TYPES, key=len, reverse=True):
                if unique_id.endswith(f"_{sensor_type}"):
                    new_unique_id = f"{DOMAIN}_{entry.entry_id}_{sensor_type}"
                    if new_unique_id != unique_id:
                        return {"new_unique_id": new_unique_id}
                    return None
            return None

        await er.async_migrate_entries(hass, entry.entry_id, _migrate_entity)
        hass.config_entries.async_update_entry(entry, version=2)

    return True

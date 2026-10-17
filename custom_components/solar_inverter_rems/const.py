from __future__ import annotations

import enum
from typing import Any, Final

try:  # Running inside Home Assistant: use the real constants.
    from homeassistant.const import (  # type: ignore[import-not-found]
        Platform,  # type: ignore[no-redef]
        UnitOfElectricCurrent,  # type: ignore[no-redef]
        UnitOfElectricPotential,  # type: ignore[no-redef]
        UnitOfEnergy,  # type: ignore[no-redef]
        UnitOfFrequency,  # type: ignore[no-redef]
        UnitOfPower,  # type: ignore[no-redef]
    )
except ImportError:  # pragma: no cover - local dev / Pylance without HA installed.
    # Minimal fallbacks with the same values as homeassistant.const so this
    # module stays importable (and Pylance-clean) outside HA. Inside HA the
    # real classes above are used instead.
    # NOTE: enum.StrEnum (Python 3.11+) mirrors HA's StrEnum-based
    # constants so str(member) == member.value (e.g. "V", "kWh").
    # NOTE: fallback classes use distinct private names plus an aliased
    # assignment so Pylance does not treat the `try` import and the
    # `except` class as two conflicting definitions of the same symbol
    # (which caused "Type type[HA.X] is not assignable to type[this.X]").

    class _PlatformFallback(enum.StrEnum):
        SENSOR = "sensor"

    class _UnitOfElectricPotentialFallback(enum.StrEnum):
        VOLT = "V"

    class _UnitOfElectricCurrentFallback(enum.StrEnum):
        AMPERE = "A"

    class _UnitOfPowerFallback(enum.StrEnum):
        WATT = "W"

    class _UnitOfFrequencyFallback(enum.StrEnum):
        HERTZ = "Hz"

    class _UnitOfEnergyFallback(enum.StrEnum):
        KILO_WATT_HOUR = "kWh"

    Platform = _PlatformFallback  # type: ignore[no-redef]
    UnitOfElectricPotential = _UnitOfElectricPotentialFallback  # type: ignore[no-redef]
    UnitOfElectricCurrent = _UnitOfElectricCurrentFallback  # type: ignore[no-redef]
    UnitOfPower = _UnitOfPowerFallback  # type: ignore[no-redef]
    UnitOfFrequency = _UnitOfFrequencyFallback  # type: ignore[no-redef]
    UnitOfEnergy = _UnitOfEnergyFallback  # type: ignore[no-redef]

DOMAIN = "solar_inverter_rems"
CONF_SLAVE_ID = "slave_id"
DEFAULT_NAME = "Solar Inverter"
DEFAULT_SCAN_INTERVAL = 600
DEFAULT_PORT = 8899
PLATFORMS = [Platform.SENSOR]

# RS485-over-TCP communication tuning. Optimized for stability with several
# inverters sharing one bridge: generous retries and timeouts so every
# device is read reliably each tick. Latency does not matter (polls run in
# the executor and never block the event loop or HA startup); polls for one
# bridge are serialized with an asyncio.Lock plus a settle gap, so slower
# sequential reads are expected and fine.
MAX_RETRIES = 5
SOCKET_TIMEOUT = 3.0
RESPONSE_TIMEOUT = 5.0
RETRY_DELAY = 1.5
CONNECT_DELAY = 0.5
# Quiet gap held on the bridge lock after each poll so the RS485 bus and
# the TCP bridge (e.g. Elfin-EW11) settle before the next inverter is polled.
BUS_SETTLE_DELAY = 1.0

# How many consecutive fetch failures before the inverter is considered
# truly offline (night / powered down) and sensors report 0 / "Inverter Off".
# Transient failures (bus contention with several inverters on one bridge,
# line noise, single timeout) keep the previous values instead of zeroing.
OFFLINE_AFTER_FAILURES = 3

# name, native unit, icon, device class, state class
# Device/state classes are plain strings (the values of SensorDeviceClass /
# SensorStateClass) so this module has no runtime dependency on
# `homeassistant.components.sensor` — HA accepts the strings directly.
SENSOR_TYPES: Final[dict[str, list[Any]]] = {
    "pv_voltage": [
        "PV Voltage",
        UnitOfElectricPotential.VOLT,
        "mdi:solar-power",
        "voltage",
        "measurement",
    ],
    "pv_current": [
        "PV Current",
        UnitOfElectricCurrent.AMPERE,
        "mdi:current-dc",
        "current",
        "measurement",
    ],
    "pv_power": [
        "PV Power",
        UnitOfPower.WATT,
        "mdi:solar-power",
        "power",
        "measurement",
    ],
    "grid_voltage": [
        "Grid Voltage",
        UnitOfElectricPotential.VOLT,
        "mdi:current-ac",
        "voltage",
        "measurement",
    ],
    "grid_current": [
        "Grid Current",
        UnitOfElectricCurrent.AMPERE,
        "mdi:current-ac",
        "current",
        "measurement",
    ],
    "grid_power": [
        "Grid Power",
        UnitOfPower.WATT,
        "mdi:power-plug",
        "power",
        "measurement",
    ],
    "power_factor": [
        "Power Factor",
        "%",
        "mdi:cosine-wave",
        "power_factor",
        "measurement",
    ],
    "grid_frequency": [
        "Grid Frequency",
        UnitOfFrequency.HERTZ,
        "mdi:sine-wave",
        "frequency",
        "measurement",
    ],
    "total_power": [
        "Total Power",
        UnitOfEnergy.KILO_WATT_HOUR,
        "mdi:chart-histogram",
        "energy",
        "total_increasing",
    ],
    "inverter_fault": [
        "Inverter Fault",
        None,
        "mdi:alert-circle",
        None,
        None,
    ],
    "grid_accumulated_energy": [
        "Grid Accumulated Energy",
        UnitOfEnergy.KILO_WATT_HOUR,
        "mdi:lightning-bolt",
        "energy",
        "total_increasing",
    ],
}

FAULT_BIT_MAP = {
    0: "Inverter Off",
    1: "PV Over Voltage",
    2: "PV Under Voltage",
    3: "PV Over Current",
    4: "Inverter IGBT Error",
    5: "Inverter Over Temperature",
    6: "Grid Over Voltage",
    7: "Grid Under Voltage",
    8: "Grid Over Current",
    9: "Grid Over Frequency",
    10: "Grid Under Frequency",
    11: "Stand-alone (Islanding)",
    12: "Ground Fault (Leakage)",
}

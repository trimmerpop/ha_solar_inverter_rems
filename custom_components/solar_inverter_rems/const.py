from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)

DOMAIN = "solar_inverter_rems"
CONF_SLAVE_ID = "slave_id"
DEFAULT_NAME = "Solar Inverter"
DEFAULT_SCAN_INTERVAL = 600
DEFAULT_PORT = 8899
PLATFORMS = [Platform.SENSOR]

# RS485-over-TCP communication tuning. Kept low so that polling stays cheap
# when the inverter is off (e.g. at night) while still allowing a few retries
# for line noise during the day. The actual fetch always runs in the executor
# and never blocks the event loop or Home Assistant startup.
MAX_RETRIES = 3
SOCKET_TIMEOUT = 2.0
RESPONSE_TIMEOUT = 2.0
RETRY_DELAY = 1.0
CONNECT_DELAY = 0.4

# name, native unit, icon, device class, state class
SENSOR_TYPES = {
    "pv_voltage": [
        "PV Voltage",
        UnitOfElectricPotential.VOLT,
        "mdi:solar-power",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
    ],
    "pv_current": [
        "PV Current",
        UnitOfElectricCurrent.AMPERE,
        "mdi:current-dc",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
    ],
    "pv_power": [
        "PV Power",
        UnitOfPower.WATT,
        "mdi:solar-power",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
    ],
    "grid_voltage": [
        "Grid Voltage",
        UnitOfElectricPotential.VOLT,
        "mdi:current-ac",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
    ],
    "grid_current": [
        "Grid Current",
        UnitOfElectricCurrent.AMPERE,
        "mdi:current-ac",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
    ],
    "grid_power": [
        "Grid Power",
        UnitOfPower.WATT,
        "mdi:power-plug",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
    ],
    "power_factor": [
        "Power Factor",
        "%",
        "mdi:cosine-wave",
        SensorDeviceClass.POWER_FACTOR,
        SensorStateClass.MEASUREMENT,
    ],
    "grid_frequency": [
        "Grid Frequency",
        UnitOfFrequency.HERTZ,
        "mdi:sine-wave",
        SensorDeviceClass.FREQUENCY,
        SensorStateClass.MEASUREMENT,
    ],
    "total_power": [
        "Total Power",
        UnitOfEnergy.KILO_WATT_HOUR,
        "mdi:chart-histogram",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
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
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
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

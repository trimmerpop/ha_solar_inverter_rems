from homeassistant.const import Platform

DOMAIN = "solar_inverter_rems"
CONF_SLAVE_ID = "slave_id"
DEFAULT_NAME = "Solar Inverter"
DEFAULT_SCAN_INTERVAL = 600
DEFAULT_PORT = 8899
PLATFORMS = [Platform.SENSOR]
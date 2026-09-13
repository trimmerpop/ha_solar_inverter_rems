import logging
import socket
import struct
import time
import threading
import voluptuous as vol
from datetime import timedelta

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle
from .const import CONF_SLAVE_ID, DEFAULT_NAME, DOMAIN

from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import DeviceInfo

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = {
    'pv_voltage': ["PV Voltage", UnitOfElectricPotential.VOLT, "mdi:solar-power", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT],
    'pv_current': ["PV Current", UnitOfElectricCurrent.AMPERE, "mdi:current-dc", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT],
    'pv_power': ["PV Power", UnitOfPower.WATT, "mdi:solar-power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT],
    'grid_voltage': ["Grid Voltage", UnitOfElectricPotential.VOLT, "mdi:current-ac", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT],
    'grid_current': ["Grid Current", UnitOfElectricCurrent.AMPERE, "mdi:current-ac", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT],
    'grid_power': ["Grid Power", UnitOfPower.WATT, "mdi:power-plug", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT],
    'power_factor': ["Power Factor", "%", "mdi:cosine-wave", SensorDeviceClass.POWER_FACTOR, SensorStateClass.MEASUREMENT],
    'grid_frequency': ["Grid Frequency", UnitOfFrequency.HERTZ, "mdi:sine-wave", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT],
    'total_power': ["Total Power", UnitOfEnergy.KILO_WATT_HOUR, "mdi:chart-histogram", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING],
    'inverter_fault': ["Inverter Fault", None, "mdi:alert-circle", None, None],
    'grid_accumulated_energy': ["Grid Accumulated Energy", UnitOfEnergy.KILO_WATT_HOUR, "mdi:lightning-bolt", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING],
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

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_IP_ADDRESS): cv.string,
    vol.Required(CONF_PORT): cv.port,
    vol.Required(CONF_SLAVE_ID): cv.positive_int,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_SCAN_INTERVAL, default=timedelta(minutes=10)): cv.time_period,
})

# Global locks to prevent concurrent connections to the same IP:Port
_CONNECTION_LOCKS = {}
_CONNECTION_LOCKS_LOCK = threading.Lock()

def crc16(data: bytes):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)

def get_solar_data(ip, port, slave_id):
    max_retries = 5
    for attempt in range(max_retries):
        s = None
        try:
            # Create socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2) # 2-second timeout
            
            # 1. Attempt connection
            try:
                s.connect((ip, int(port)))
            except socket.timeout:
                raise Exception("Connection timed out")
            except Exception as e:
                raise Exception(f"Connection failed: {e}")

            # Short delay after connection (for EW11 stability)
            time.sleep(0.4)

            # Clear input buffer (remove residual data from previous communication)
            try:
                s.settimeout(0.1)
                while True:
                    if not s.recv(1024): break
            except:
                pass
            s.settimeout(2) # Restore timeout

            # Create request packet: SOP(0x7E) + SlaveID + Cmd(0x01)
            start_flag = b'\x7e'
            slave_byte = int(slave_id)
            cmd_byte = 1
            
            # Packet structure: SOP + Slave + Cmd
            pdu = struct.pack('>BB', slave_byte, cmd_byte)
            data_for_crc = start_flag + pdu
            
            # Calculate and add CRC
            crc = crc16(data_for_crc)
            request_frame = data_for_crc + crc
            
            # Send data
            s.send(request_frame)
            
            # Response receive loop (repeat until desired Slave ID is found)
            start_time = time.time()
            while True:
                # Overall timeout check
                if time.time() - start_time > 2:
                    raise Exception("Timed out waiting for correct packet")

                # 2. Receive header (5 bytes: SOP, Slave, Cmd, LenH, LenL)
                header = b''
                while len(header) < 5:
                    if time.time() - start_time > 2:
                        raise socket.timeout("Receive Header timed out")
                    try:
                        chunk = s.recv(5 - len(header))
                        if not chunk:
                            raise Exception("Connection closed by peer")
                        header += chunk
                    except socket.timeout:
                        continue # Let outer loop handle timeout
                
                if header[0] != 0x7E:
                    _LOGGER.debug(f"Invalid SOP {header[0]:02X}, skipping")
                    continue

                # 2. Determine data length (Big Endian)
                data_len = struct.unpack('>H', header[3:5])[0]

                # Data length sanity check
                if data_len > 250:
                    _LOGGER.debug(f"Invalid data length: {data_len}, skipping")
                    continue
                
                # 3. Receive remaining data (Data + CRC)
                expected_remaining = data_len + 2
                payload = b''
                while len(payload) < expected_remaining:
                    if time.time() - start_time > 2:
                        raise socket.timeout("Receive Payload timed out")
                    try:
                        chunk = s.recv(expected_remaining - len(payload))
                        if not chunk:
                            raise Exception("Connection closed during payload")
                        payload += chunk
                    except socket.timeout:
                        continue # Let outer loop handle timeout
                
                full_packet = header + payload

                # 4. CRC verification
                received_crc = full_packet[-2:]
                calculated_crc = crc16(full_packet[:-2])
                
                if received_crc != calculated_crc:
                    _LOGGER.debug(f"CRC Mismatch. Recv {received_crc.hex().upper()}, Calc {calculated_crc.hex().upper()}, skipping")
                    continue

                # 5. Verify Slave ID
                if header[1] == int(slave_id):
                    # Success: this is the desired data
                    return full_packet[5:-2]
                else:
                    # Failure: data from another device -> log and continue reading (Skip)
                    _LOGGER.debug(f"Skipping packet for Slave {header[1]} (Expected {slave_id})")
                    continue

        except Exception as e:
            if attempt == max_retries - 1:
                _LOGGER.info(f"Failed to get data after {max_retries} attempts: {e}")
            else:
                _LOGGER.debug(f"Attempt {attempt+1} failed, retrying: {e}")
                time.sleep(2.0)
        finally:
            if s:
                try: s.close()
                except: pass
    return None

class SolarInverterHub:
    """Data hub for the Solar Inverter."""

    def __init__(self, ip, port, slave_id, scan_interval):
        """Initialize the hub."""
        self._ip = ip
        self._port = port
        self._slave_id = slave_id
        self.data = {}
        self.update = Throttle(scan_interval)(self._update)
        self._last_time = time.time()
        self._total_grid_energy = 0.0

    def _update(self):
        """Fetch new data and parse it."""
        # Acquire lock for this IP/Port to ensure single-threaded access
        key = (self._ip, self._port)
        with _CONNECTION_LOCKS_LOCK:
            if key not in _CONNECTION_LOCKS:
                _CONNECTION_LOCKS[key] = threading.Lock()
            lock = _CONNECTION_LOCKS[key]

        with lock:
            raw_data = get_solar_data(self._ip, self._port, self._slave_id)

        # Check for invalid zero total_power glitch
        if raw_data and len(raw_data) >= 26:
            try:
                probe_total_power = int.from_bytes(raw_data[16:24], 'big')
                if probe_total_power == 0 and self.data.get('total_power', 0) > 0:
                    _LOGGER.warning("Inverter returned 0 for total_power while previous value was %s. Skipping glitched update.", self.data.get('total_power'))
                    return
            except Exception as e:
                _LOGGER.debug("Error during early total_power probe: %s", e)

        # Calculate energy accumulation
        current_time = time.time()
        dt = current_time - self._last_time
        self._last_time = current_time

        current_grid_power = 0
        if raw_data and len(raw_data) >= 26:
            current_grid_power = int.from_bytes(raw_data[10:12], 'big')
        self._total_grid_energy += (current_grid_power * dt) / 3600000.0

        if not raw_data or len(raw_data) < 26:
            # Device is likely off (night time) or unreachable.
            # Set instantaneous values to 0, fault to "Inverter Off".
            offline_data = {
                'pv_voltage': 0,
                'pv_current': 0,
                'pv_power': 0,
                'grid_voltage': 0,
                'grid_current': 0,
                'grid_power': 0,
                'power_factor': 0,
                'grid_frequency': 0,
                'inverter_fault': "Inverter Off",
                'grid_accumulated_energy': round(self._total_grid_energy, 3),
            }
            if 'total_power' in self.data:
                offline_data['total_power'] = self.data['total_power']
            self.data = offline_data
            return

        try:
            parsed_data = {}
            parsed_data['pv_voltage'] = int.from_bytes(raw_data[0:2], 'big')
            parsed_data['pv_current'] = int.from_bytes(raw_data[2:4], 'big')
            parsed_data['pv_power'] = int.from_bytes(raw_data[4:6], 'big')
            parsed_data['grid_voltage'] = int.from_bytes(raw_data[6:8], 'big')
            parsed_data['grid_current'] = int.from_bytes(raw_data[8:10], 'big')
            parsed_data['grid_power'] = int.from_bytes(raw_data[10:12], 'big')
            parsed_data['power_factor'] = round(int.from_bytes(raw_data[12:14], 'big') * 0.1, 1)
            parsed_data['grid_frequency'] = round(int.from_bytes(raw_data[14:16], 'big') * 0.1, 1)
            # Raw value is in Wh, sensor unit is kWh.
            parsed_data['total_power'] = round(int.from_bytes(raw_data[16:24], 'big') / 1000, 3)
            parsed_data['grid_accumulated_energy'] = round(self._total_grid_energy, 3)
            
            fault_code = int.from_bytes(raw_data[24:26], 'big')
            faults = []
            for bit, message in FAULT_BIT_MAP.items():
                if (fault_code >> bit) & 1:
                    faults.append(message)
            
            if not faults:
                parsed_data['inverter_fault'] = "Normal"
            else:
                parsed_data['inverter_fault'] = ", ".join(faults)
            
            self.data = parsed_data
            _LOGGER.debug("Successfully updated inverter data: %s", self.data)
        except (struct.error, IndexError) as e:
            _LOGGER.error("Failed to parse inverter data: %s. Raw: %s", e, raw_data.hex() if raw_data else "None")
            self.data = {}

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Solar RS485 sensor from a config entry."""
    config = {**config_entry.data, **config_entry.options}
    ip = config[CONF_IP_ADDRESS]
    port = config[CONF_PORT]
    slave_id = config[CONF_SLAVE_ID]
    name = config[CONF_NAME]
    
    # Config flow saves int (seconds), convert to timedelta
    scan_interval_seconds = config.get(CONF_SCAN_INTERVAL, 10)
    scan_interval = timedelta(seconds=scan_interval_seconds)

    # Migrate old unique_id format for existing entities if needed.
    # Old: solar_rs485_{ip}_{slave_id}_{sensor_type}
    # New: {DOMAIN}_{entry_id}_{sensor_type}
    registry = entity_registry.async_get(hass)
    entity_entries = entity_registry.async_entries_for_config_entry(hass, config_entry.entry_id)
    if entity_entries:
        _LOGGER.debug(
            "Checking existing entities for migration for config entry %s", config_entry.entry_id
        )
        for entity_entry in entity_entries:
            old_uid = entity_entry.unique_id
            if old_uid and old_uid.startswith("solar_rs485_"):
                parts = old_uid.split("_")
                if len(parts) >= 4:
                    sensor_type = parts[-1]
                    new_uid = f"{DOMAIN}_{config_entry.entry_id}_{sensor_type}"
                    if new_uid != old_uid:
                        _LOGGER.info(
                            "Migrating entity %s from %s to %s",
                            entity_entry.entity_id,
                            old_uid,
                            new_uid,
                        )
                        await registry.async_update_entity(
                            entity_entry.entity_id, new_unique_id=new_uid
                        )

    hub = SolarInverterHub(ip, port, slave_id, scan_interval)

    sensors = [
        SolarRS485Sensor(hub, config_entry.entry_id, sensor_type)
        for sensor_type in SENSOR_TYPES
    ]
    async_add_entities(sensors, True)

    return True

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Solar RS485 sensor."""
    ip = config[CONF_IP_ADDRESS]
    port = config[CONF_PORT]
    slave_id = config[CONF_SLAVE_ID]
    name = config.get(CONF_NAME, DEFAULT_NAME)
    scan_interval = config[CONF_SCAN_INTERVAL]

    hub = SolarInverterHub(ip, port, slave_id, scan_interval)
    sensors = [
        SolarRS485Sensor(hub, f"{DOMAIN}_{ip}:{port}:{slave_id}", sensor_type)
        for sensor_type in SENSOR_TYPES
    ]
    add_entities(sensors, False)

class SolarRS485Sensor(SensorEntity):
    """Representation of a Solar RS485 Sensor."""


    def __init__(self, hub, entry_id: str, sensor_type):
        """Initialize the sensor."""
        self._hub = hub
        self._entry_id = entry_id
        self._sensor_type = sensor_type

        sensor_info = SENSOR_TYPES[self._sensor_type]
        self._attr_name = f"{DEFAULT_NAME} {sensor_info[0]}"
        self._attr_unique_id = f"{DOMAIN}_{self._entry_id}_{self._sensor_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=DEFAULT_NAME,
            manufacturer="Ingeteam",
            model="Solar Inverter REMS",
        )
        self._attr_native_unit_of_measurement = sensor_info[1]
        self._attr_icon = sensor_info[2]
        self._attr_device_class = sensor_info[3]
        self._attr_state_class = sensor_info[4]

    @property
    def available(self) -> bool:
        """Return True if hub has data."""
        return self._hub.data and self._sensor_type in self._hub.data

    def update(self):
        """Fetch new state data for the sensor."""
        self._hub.update()
        self._attr_native_value = self._hub.data.get(self._sensor_type)
# REMS Solar Inverter Custom Component

[한국어 문서 (Korean Docs)](README_ko.md)


![Icon](icon.png)

This custom component for Home Assistant integrates single-phase solar inverters certified by the Korea Renewable Energy Integrated Monitoring System (REMS). It connects via an RS485-to-TCP bridge (like the Elfin-EW11) to monitor power generation, voltage, current, and more.

## Features

- **Real-Time Monitoring**:
  - **PV (DC) Side**: Voltage, Current, Power.
  - **Grid (AC) Side**: Voltage, Current, Power, Frequency, Power Factor.
- **Energy Tracking**:
  - Reads total cumulative generation from the inverter.
  - Software-calculated "Grid Accumulated Energy" (session based).
- **Fault Detection**: Decodes inverter fault codes into readable text (e.g., "PV Over Voltage", "Inverter Off", "Normal").
- **Automatic Retry**: Robust connection handling with retries and timeouts for stable RS485-over-TCP communication.

## Supported Devices

- **Inverters**: Any single-phase solar inverter that adheres to the Korean REMS standard protocol.
- **Communication Bridge**: RS485 to TCP/IP server (e.g., Elfin-EW11, Elfin-EE11) configured as a TCP Server.

## Installation

### Method 1: HACS (Recommended)

1. Ensure **HACS** is installed in Home Assistant.
2. Navigate to **HACS > Integrations**.
3. Click the menu (three dots) in the top-right corner and select **Custom repositories**.
4. Add the repository URL:
   ```
   https://github.com/trimmerpop/ha_solar_inverter_rems
   ```
5. Select **Integration** as the category and click **Add**.
6. Find **Solar Inverter REMS** in the list and click **Download**.
7. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the latest release from this repository.
2. Copy the `solar_inverter_rems` folder into your Home Assistant's `custom_components` directory.
   - Path: `/config/custom_components/solar_inverter_rems`
3. Restart Home Assistant.

## Configuration

1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration**.
3. Search for **Solar Inverter REMS**.
4. Enter the required connection details:
   - **Name**: Prefix for your sensors (e.g., "Solar").
   - **IP Address**: IP address of your RS485-to-TCP bridge (e.g., `192.168.0.10`).
   - **Port**: TCP port of the bridge (e.g., `8899`).
   - **Slave ID**: Modbus Slave ID of the inverter (default is usually `1`).
   - **Scan Interval**: How often to fetch data (in seconds, default: 10).

> **Note**: You can change these settings later by clicking **Configure** on the integration entry.

## Sensors

Once configured, the following entities will be available (prefixed with your chosen name):

| Entity ID Suffix | Description | Unit | Class |
| :--- | :--- | :--- | :--- |
| `_pv_voltage` | PV Input Voltage | V | Voltage |
| `_pv_current` | PV Input Current | A | Current |
| `_pv_power` | PV Input Power | W | Power |
| `_grid_voltage` | Grid Output Voltage | V | Voltage |
| `_grid_current` | Grid Output Current | A | Current |
| `_grid_power` | Grid Output Power | W | Power |
| `_grid_frequency` | AC Frequency | Hz | Frequency |
| `_power_factor` | Power Factor | % | Power Factor |
| `_total_power` | Total Lifetime Generation | kWh | Energy |
| `_grid_accumulated_energy` | Session Generation (Software Calculated) | kWh | Energy |
| `_inverter_fault` | Inverter Diagnostics Status | - | - |

## Troubleshooting

- **Connection Failed**:
  - Check if the IP and Port are correct.
  - verify the RS485-to-TCP device is reachable (`ping <ip>`).
  - Ensure no other client (like another HA instance or test tool) is holding the connection open if your bridge only supports one client.
- **No Data / "Inverter Off"**:
  - At night, the inverter typically powers down. The integration will show "Inverter Off" and zero values.
  - If it happens during the day, check the physical RS485 wiring (A+, B-).
- **CRC Mismatch**:
  - Usually indicates noise on the line or an unstable wireless connection to the bridge. The integration will automatically retry.

## Support

If you encounter issues or have feature requests, please report them on the [Issues Tracker](https://github.com/trimmerpop/ha_solar_inverter_rems/issues).

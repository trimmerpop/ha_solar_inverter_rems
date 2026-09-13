"""RS485-over-TCP protocol and per-bridge locking for Solar Inverter REMS.

The inverter is reached through an RS485-to-TCP bridge (e.g. Elfin-EW11).
Several config entries (several inverters) may share the same bridge, so all
access to a given ``(ip, port)`` is serialized with an ``asyncio.Lock``. Only
one request may be on the RS485 bus at a time; waiting for the lock does not
occupy an executor thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import struct
import time

from homeassistant.core import HomeAssistant, callback

from .const import (
    CONNECT_DELAY,
    MAX_RETRIES,
    RESPONSE_TIMEOUT,
    RETRY_DELAY,
    SOCKET_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class _Bridge:
    """A shared RS485-to-TCP bridge and how many entries use it."""

    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        """Initialize the bridge."""
        self.lock = asyncio.Lock()
        self.users = 0


_BRIDGES: dict[tuple[str, int], _Bridge] = {}


@callback
def acquire_bridge(ip: str, port: int) -> asyncio.Lock:
    """Return the lock for ``(ip, port)`` and increase its reference count."""
    key = (ip, port)
    bridge = _BRIDGES.get(key)
    if bridge is None:
        bridge = _Bridge()
        _BRIDGES[key] = bridge
    bridge.users += 1
    return bridge.lock


@callback
def release_bridge(ip: str, port: int) -> None:
    """Decrease the reference count and drop the lock when it is safe.

    The lock is only removed when no entry uses it *and* no fetch is in
    flight. Otherwise a reload that happens while polling would create a new
    lock and allow two concurrent connections to the same bridge.
    """
    key = (ip, port)
    bridge = _BRIDGES.get(key)
    if bridge is None:
        return
    bridge.users -= 1
    if bridge.users <= 0 and not bridge.lock.locked():
        _BRIDGES.pop(key, None)


def crc16(data: bytes) -> bytes:
    """Calculate the Modbus CRC16 of ``data``."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)


def get_solar_data(
    ip: str,
    port: int,
    slave_id: int,
    *,
    retries: int = MAX_RETRIES,
    timeout: float = SOCKET_TIMEOUT,
    response_timeout: float = RESPONSE_TIMEOUT,
    retry_delay: float = RETRY_DELAY,
) -> bytes | None:
    """Fetch a data frame from the inverter.

    This function is blocking and must be run in an executor thread.
    """
    for attempt in range(retries):
        s = None
        try:
            # Create socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)

            # 1. Attempt connection
            try:
                s.connect((ip, int(port)))
            except socket.timeout:
                raise Exception("Connection timed out") from None
            except Exception as e:
                raise Exception(f"Connection failed: {e}") from e

            # Short delay after connection (for EW11 stability)
            time.sleep(CONNECT_DELAY)

            # Clear input buffer (remove residual data from previous communication)
            try:
                s.settimeout(0.1)
                while True:
                    if not s.recv(1024):
                        break
            except Exception:  # noqa: BLE001
                pass
            s.settimeout(timeout)

            # Create request packet: SOP(0x7E) + SlaveID + Cmd(0x01)
            start_flag = b"\x7e"
            slave_byte = int(slave_id)
            cmd_byte = 1

            # Packet structure: SOP + Slave + Cmd
            pdu = struct.pack(">BB", slave_byte, cmd_byte)
            data_for_crc = start_flag + pdu

            # Calculate and add CRC
            request_frame = data_for_crc + crc16(data_for_crc)

            # Send data
            s.send(request_frame)

            # Response receive loop (repeat until desired Slave ID is found)
            start_time = time.time()
            while True:
                # Overall timeout check
                if time.time() - start_time > response_timeout:
                    raise Exception("Timed out waiting for correct packet")

                # 2. Receive header (5 bytes: SOP, Slave, Cmd, LenH, LenL)
                header = b""
                while len(header) < 5:
                    if time.time() - start_time > response_timeout:
                        raise socket.timeout("Receive Header timed out")
                    try:
                        chunk = s.recv(5 - len(header))
                        if not chunk:
                            raise Exception("Connection closed by peer")
                        header += chunk
                    except socket.timeout:
                        continue  # Let outer loop handle timeout

                if header[0] != 0x7E:
                    _LOGGER.debug("Invalid SOP %02X, skipping", header[0])
                    continue

                # 3. Determine data length (Big Endian)
                data_len = struct.unpack(">H", header[3:5])[0]

                # Data length sanity check
                if data_len > 250:
                    _LOGGER.debug("Invalid data length: %s, skipping", data_len)
                    continue

                # 4. Receive remaining data (Data + CRC)
                expected_remaining = data_len + 2
                payload = b""
                while len(payload) < expected_remaining:
                    if time.time() - start_time > response_timeout:
                        raise socket.timeout("Receive Payload timed out")
                    try:
                        chunk = s.recv(expected_remaining - len(payload))
                        if not chunk:
                            raise Exception("Connection closed during payload")
                        payload += chunk
                    except socket.timeout:
                        continue  # Let outer loop handle timeout

                full_packet = header + payload

                # 5. CRC verification
                received_crc = full_packet[-2:]
                calculated_crc = crc16(full_packet[:-2])

                if received_crc != calculated_crc:
                    _LOGGER.debug(
                        "CRC Mismatch. Recv %s, Calc %s, skipping",
                        received_crc.hex().upper(),
                        calculated_crc.hex().upper(),
                    )
                    continue

                # 6. Verify Slave ID
                if header[1] == int(slave_id):
                    # Success: this is the desired data
                    return full_packet[5:-2]

                # Data from another device -> log and continue reading (Skip)
                _LOGGER.debug(
                    "Skipping packet for Slave %s (Expected %s)",
                    header[1],
                    slave_id,
                )

        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                _LOGGER.info("Failed to get data after %s attempts: %s", retries, e)
            else:
                _LOGGER.debug("Attempt %s failed, retrying: %s", attempt + 1, e)
                time.sleep(retry_delay)
        finally:
            if s:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
    return None


async def fetch_locked(
    hass: HomeAssistant,
    lock: asyncio.Lock,
    ip: str,
    port: int,
    slave_id: int,
) -> bytes | None:
    """Fetch data while holding the shared bridge lock.

    The blocking fetch runs in an executor thread. If this coroutine is
    cancelled, we still wait for the in-flight job to finish before releasing
    the lock, so the RS485 bus is never accessed concurrently.
    """
    await lock.acquire()
    try:
        future = hass.async_add_executor_job(get_solar_data, ip, port, slave_id)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Executor jobs cannot be cancelled; wait for it to release the bus.
            with contextlib.suppress(Exception):
                await future
            raise
    finally:
        lock.release()

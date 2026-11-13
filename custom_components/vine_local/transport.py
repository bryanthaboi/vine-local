"""Small Tuya LAN client, also usable outside Home Assistant.

TinyTuya handles framing, encryption and the 3.5 session handshake. Never enable
its debug logging: the underlying library can log keys and raw device payloads.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any

import tinytuya


class ConnectionFailed(Exception):
    """The thermostat did not return a valid authenticated status response."""


class TuyaClient:
    """Serialize requests and release the device's single LAN socket after use."""

    def __init__(
        self, device_id: str, host: str, local_key: str, version: str = "auto", *, controls=()
    ):
        if len(local_key.encode("utf-8")) != 16:
            raise ValueError("A Tuya local key must contain exactly 16 UTF-8 bytes")
        self._device_id = device_id
        self._host = host
        self._key = local_key
        if str(version) not in ("auto", "3.3", "3.4", "3.5"):
            raise ValueError("Unsupported protocol version")
        self._auto = str(version) == "auto"
        self._version = 3.5 if self._auto else float(version)
        self._controls = frozenset(controls)
        self._lock = threading.RLock()

    @property
    def version(self):
        return str(self._version)

    @contextmanager
    def _connection(self):
        with self._lock:
            device = tinytuya.Device(
                self._device_id,
                self._host,
                self._key,
                version=self._version,
                persist=False,
                connection_timeout=4,
                connection_retry_limit=1,
                connection_retry_delay=0,
            )
            device.set_retry(False)
            try:
                yield device
            except ConnectionFailed:
                raise
            except Exception:
                raise ConnectionFailed("No authenticated LAN status received") from None
            finally:
                device.close()

    @staticmethod
    def _parse_status(response):
        if not isinstance(response, dict) or "Error" in response or "Err" in response:
            raise ConnectionFailed("LAN query failed; check key, version and competing clients")
        dps = response.get("dps")
        if not isinstance(dps, dict) or not dps:
            raise ConnectionFailed("LAN response contained no datapoints")
        if not all(isinstance(k, str) and k.isdecimal() for k in dps):
            raise ConnectionFailed("LAN response contained invalid datapoint identifiers")
        return dps

    def status(self) -> dict[str, Any]:
        """Read status without writing any datapoints; sanitize errors."""
        with self._lock:
            for version in (3.5, 3.4, 3.3) if self._auto else (self._version,):
                self._version = version
                try:
                    with self._connection() as device:
                        result = self._parse_status(device.status())
                except ConnectionFailed:
                    continue
                self._auto = False
                return result
            raise ConnectionFailed("No authenticated LAN status received")

    def command(self, values: dict[str, Any]) -> dict[str, Any]:
        """Send allowlisted control fields, then read back actual device state."""
        if not values or set(values) - self._controls:
            raise ValueError("Unsupported thermostat control datapoints")
        with self._connection() as device:
            reply = device.set_multiple_values(values)
            if isinstance(reply, dict) and ("Error" in reply or "Err" in reply):
                raise ConnectionFailed("The thermostat rejected the command")
            dps = self._parse_status(device.status())
            if any(dps.get(k) != v for k, v in values.items()):
                raise ConnectionFailed(
                    "Command was not confirmed by device readback; refresh before retrying"
                )
            return dps

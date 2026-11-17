"""Direct MQTT to a Bambu printer, only for what Bambuddy can't send: a slot's remaining weight (dev plan §6.7).

Bambuddy owns the printer connection and withholds the LAN access code from API keys, so the station keeps
its own copy (BAMBU_ACCESS_CODE). It connects on demand, publishes one `set_filament_weight` (the command
Bambu Studio sends after a slot's filament settings) and waits for the reply, so it never holds one of the
printer's MQTT connections.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .printer_client import PrinterCommandError, PrinterOffline

MQTT_PORT = 8883
MQTT_USER = "bblp"
# Bambu Studio's limits (DevFilamentWeight): 1-10000 g, remain <= total.
MIN_GRAMS = 1
MAX_GRAMS = 10000


@dataclass(frozen=True)
class WeightTarget:
    """Bambuddy's printer id (enough for the simulator) and, live, the printer's LAN address and serial."""

    printer_id: int
    host: str | None = field(default=None, repr=False)
    serial: str | None = field(default=None, repr=False)


def filament_weight(remaining_g: float | None, initial_g: float | None) -> tuple[int, int] | None:
    """(total, remain) in grams as Bambu Studio sends them, or None when Spoolman's numbers can't be sent."""
    if remaining_g is None or initial_g is None:
        return None
    remain = round(remaining_g)
    total = max(round(initial_g), remain)
    if remain < MIN_GRAMS or total > MAX_GRAMS:
        return None
    return total, remain


def remain_percent(total: int, remain: int) -> int:
    """The tray `remain` the printer reports for these grams (the firmware truncates)."""
    return remain * 100 // total


def weight_command(sequence: int, ams_id: int, slot: int, total: int, remain: int) -> dict[str, Any]:
    return {"print": {"command": "set_filament_weight", "sequence_id": str(sequence), "ams_id": ams_id,
                      "slot_id": slot, "total": total, "remain": remain, "src_id": 1}}


class WeightSender(Protocol):
    # True when the sender needs the printer's LAN address and serial (read from Bambuddy).
    needs_address: bool

    async def set_filament_weight(self, target: WeightTarget, ams_id: int, slot: int, total: int,
                                  remain: int) -> None: ...


def _paho_client() -> Any:
    import paho.mqtt.client as mqtt

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"spool-station-{secrets.token_hex(4)}",
                       protocol=mqtt.MQTTv311)


def _refused(reason_code: Any) -> bool:
    if isinstance(reason_code, int):
        return reason_code != 0
    return bool(getattr(reason_code, "is_failure", False))


class MqttWeightSender:
    """One short TLS connection per command (user `bblp`, the access code); the printer's certificate is
    self-signed, so it is not verified."""

    needs_address = True

    def __init__(self, access_code: str, *, port: int = MQTT_PORT, timeout_s: float = 8.0,
                 client_factory: Callable[[], Any] = _paho_client) -> None:
        self._access_code = access_code
        self.port = port
        self.timeout_s = timeout_s
        self.client_factory = client_factory
        self._sequence = secrets.randbelow(10_000) * 100
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"MqttWeightSender(port={self.port})"

    async def set_filament_weight(self, target: WeightTarget, ams_id: int, slot: int, total: int,
                                  remain: int) -> None:
        if not target.host or not target.serial:
            raise PrinterCommandError("the printer's LAN address is unknown")
        async with self._lock:
            self._sequence += 1
            payload = weight_command(self._sequence, ams_id, slot, total, remain)
            await asyncio.to_thread(self._publish, target.host, target.serial, payload)

    def _publish(self, host: str, serial: str, payload: dict[str, Any]) -> None:
        sequence = payload["print"]["sequence_id"]
        connected, subscribed, replied = threading.Event(), threading.Event(), threading.Event()
        outcome: dict[str, Any] = {}

        def on_connect(_client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
            outcome["connect"] = reason_code
            connected.set()

        def on_subscribe(*_args: Any) -> None:
            subscribed.set()

        def on_message(_client: Any, _userdata: Any, message: Any) -> None:
            try:
                data = json.loads(message.payload)
            except ValueError:
                return
            reply = data.get("print") if isinstance(data, dict) else None
            if isinstance(reply, dict) and reply.get("command") == "set_filament_weight" \
                    and str(reply.get("sequence_id")) == sequence:
                outcome["reply"] = reply
                replied.set()

        client = self.client_factory()
        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        client.username_pw_set(MQTT_USER, self._access_code)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        client.tls_set_context(context)
        try:
            client.connect(host, self.port, keepalive=30)
        except OSError as error:
            raise PrinterOffline(f"the printer's MQTT is unreachable ({type(error).__name__})") from error
        client.loop_start()
        try:
            if not connected.wait(self.timeout_s):
                raise PrinterOffline("the printer's MQTT did not answer")
            if _refused(outcome["connect"]):
                raise PrinterCommandError(f"the printer refused the MQTT login ({outcome['connect']}); "
                                          f"check BAMBU_ACCESS_CODE")
            client.subscribe(f"device/{serial}/report")
            if not subscribed.wait(self.timeout_s):
                raise PrinterCommandError("the printer did not confirm the MQTT subscription")
            client.publish(f"device/{serial}/request", json.dumps(payload), qos=1)
            if not replied.wait(self.timeout_s):
                raise PrinterCommandError("no reply from the printer")
            reply = outcome["reply"]
            result = str(reply.get("result") or "").lower()
            if result and result != "success":
                raise PrinterCommandError(f"the printer refused it ({reply.get('reason') or result})")
        finally:
            client.disconnect()
            client.loop_stop()

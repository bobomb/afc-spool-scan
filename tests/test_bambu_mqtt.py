from __future__ import annotations

import json
import ssl
from types import SimpleNamespace
from typing import Any

import pytest

from station.bambu_mqtt import (
    MqttWeightSender,
    WeightTarget,
    filament_weight,
    remain_percent,
    weight_command,
)
from station.printer_client import PrinterCommandError, PrinterOffline

CODE = "12345678"
TARGET = WeightTarget(1, host="192.0.2.30", serial="SIM000000000001")


class FakeClient:
    """The slice of paho's Client the sender uses; replies arrive the way the printer sends them."""

    def __init__(self, *, connect_rc: int = 0, reply: dict[str, Any] | None = None,
                 connect_error: OSError | None = None) -> None:
        self.connect_rc = connect_rc
        self.reply = reply
        self.connect_error = connect_error
        self.published: list[tuple[str, dict[str, Any], int]] = []
        self.subscribed: list[str] = []
        self.closed = False

    def username_pw_set(self, user: str, password: str) -> None:
        self.login = (user, password)

    def tls_set_context(self, context: ssl.SSLContext) -> None:
        self.context = context

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.address = (host, port)

    def loop_start(self) -> None:
        self.on_connect(self, None, {}, self.connect_rc, None)

    def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)
        self.on_subscribe(self, None, 1, [0], None)

    def _deliver(self, data: Any) -> None:
        self.on_message(self, None, SimpleNamespace(topic="device/x/report", payload=json.dumps(data).encode()))

    def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        body = json.loads(payload)
        self.published.append((topic, body, qos))
        if self.reply is None:
            return
        self._deliver({"print": {"command": "push_status", "ams": {}}})
        self._deliver({"print": {"command": "set_filament_weight", "sequence_id": "-1", "result": "fail"}})
        self.on_message(self, None, SimpleNamespace(topic="device/x/report", payload=b"not json"))
        self._deliver({"print": {"command": "set_filament_weight", "sequence_id": body["print"]["sequence_id"],
                                 **self.reply}})

    def disconnect(self) -> None:
        self.closed = True

    def loop_stop(self) -> None:
        self.stopped = True


def sender_for(client: FakeClient, timeout_s: float = 2.0) -> MqttWeightSender:
    return MqttWeightSender(CODE, timeout_s=timeout_s, client_factory=lambda: client)


def test_weights_follow_bambu_studio_limits() -> None:
    assert filament_weight(965.4, 1000.0) == (1000, 965)
    assert filament_weight(1203.0, 1000.0) == (1203, 1203)
    assert filament_weight(0.4, 1000.0) is None and filament_weight(None, 1000.0) is None
    assert filament_weight(500.0, None) is None and filament_weight(12000.0, 12000.0) is None
    assert remain_percent(1000, 965) == 96 and remain_percent(1000, 1000) == 100
    assert weight_command(7, 32, 0, 1000, 965) == {"print": {
        "command": "set_filament_weight", "sequence_id": "7", "ams_id": 32, "slot_id": 0, "total": 1000,
        "remain": 965, "src_id": 1}}


async def test_sends_one_command_and_waits_for_the_reply() -> None:
    client = FakeClient(reply={"result": "success", "reason": "success"})
    sender = sender_for(client)
    await sender.set_filament_weight(TARGET, 32, 4, 1000, 640)
    assert client.address == ("192.0.2.30", 8883) and client.login == ("bblp", CODE)
    assert client.context.verify_mode == ssl.CERT_NONE and not client.context.check_hostname
    assert client.subscribed == ["device/SIM000000000001/report"]
    [(topic, body, qos)] = client.published
    assert topic == "device/SIM000000000001/request" and qos == 1
    assert {k: v for k, v in body["print"].items() if k != "sequence_id"} == {
        "command": "set_filament_weight", "ams_id": 32, "slot_id": 4, "total": 1000, "remain": 640, "src_id": 1}
    assert client.closed
    assert CODE not in repr(sender)


async def test_errors_are_reported_without_the_access_code() -> None:
    with pytest.raises(PrinterCommandError, match="slot busy"):
        await sender_for(FakeClient(reply={"result": "fail", "reason": "slot busy"})).set_filament_weight(
            TARGET, 32, 0, 1000, 500)
    with pytest.raises(PrinterCommandError, match="BAMBU_ACCESS_CODE") as refused:
        await sender_for(FakeClient(connect_rc=5)).set_filament_weight(TARGET, 32, 0, 1000, 500)
    assert CODE not in str(refused.value)
    with pytest.raises(PrinterOffline):
        await sender_for(FakeClient(connect_error=ConnectionRefusedError())).set_filament_weight(
            TARGET, 32, 0, 1000, 500)
    client = FakeClient(reply=None)
    with pytest.raises(PrinterCommandError, match="no reply"):
        await sender_for(client, timeout_s=0.05).set_filament_weight(TARGET, 32, 0, 1000, 500)
    assert client.closed
    with pytest.raises(PrinterCommandError, match="address"):
        await sender_for(FakeClient()).set_filament_weight(WeightTarget(1), 32, 0, 1000, 500)

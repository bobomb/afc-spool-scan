from __future__ import annotations

import asyncio
from types import SimpleNamespace

from station.scanner.evdev_reader import EvdevScanner
from station.scanner.keymap import KEYS, KeyDecoder
from station.scanner.sim import SimScanner

EV_KEY = 1
CODES = {name: index for index, name in enumerate(KEYS) if name}


def press(decoder: KeyDecoder, name: str) -> str | None:
    code = CODES[name]
    result = decoder.feed(code, 1)
    decoder.feed(code, 0)
    return result


def type_text(decoder: KeyDecoder, text: str) -> str | None:
    shifted = {value: key for key, value in {
        "1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(",
        "0": ")", "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|", ";": ":", "'": '"', ",": "<",
        ".": ">", "/": "?",
    }.items()}
    for char in text:
        base = shifted.get(char, char.lower())
        needs_shift = char in shifted or char.isupper()
        if needs_shift:
            decoder.feed(CODES["LSHIFT"], 1)
        press(decoder, "SPACE" if char == " " else base)
        if needs_shift:
            decoder.feed(CODES["LSHIFT"], 0)
    return press(decoder, "ENTER")


def test_decodes_spoolman_code_with_shift() -> None:
    decoder = KeyDecoder()
    assert type_text(decoder, "WEB+SPOOLMAN:S-97") == "WEB+SPOOLMAN:S-97"
    assert type_text(decoder, "web+spoolman:s-97") == "web+spoolman:s-97"
    assert type_text(decoder, "http://x/spool/show/12?a=b c") == "http://x/spool/show/12?a=b c"


def test_backspace_ignored_keys_and_repeat() -> None:
    decoder = KeyDecoder()
    for name in ["1", "2", "BACKSPACE", "3", "TAB", "ESC", "CTRL", "ALT"]:
        press(decoder, name)
    decoder.feed(CODES["4"], 2)
    decoder.feed(200, 1)
    assert press(decoder, "ENTER") == "13"
    assert press(decoder, "ENTER") == ""


def test_shift_released_by_either_shift_key() -> None:
    decoder = KeyDecoder()
    decoder.feed(CODES["RSHIFT"], 1)
    press(decoder, "a")
    decoder.feed(CODES["RSHIFT"], 0)
    press(decoder, "a")
    assert press(decoder, "ENTER") == "Aa"


class FakeInputDevice:
    instances: list[FakeInputDevice] = []
    fail_open = 0

    def __init__(self, path: str) -> None:
        if FakeInputDevice.fail_open:
            FakeInputDevice.fail_open -= 1
            raise FileNotFoundError(path)
        self.path = path
        self.grabbed = False
        self.closed = False
        FakeInputDevice.instances.append(self)

    def grab(self) -> None:
        self.grabbed = True

    def ungrab(self) -> None:
        self.grabbed = False

    def close(self) -> None:
        self.closed = True

    async def async_read_loop(self):  # noqa: ANN201
        events = [SimpleNamespace(type=4, code=4, value=1)]
        for char in "97":
            events.append(SimpleNamespace(type=EV_KEY, code=CODES[char], value=1))
            events.append(SimpleNamespace(type=EV_KEY, code=CODES[char], value=0))
        events.append(SimpleNamespace(type=EV_KEY, code=CODES["ENTER"], value=1))
        for event in events:
            await asyncio.sleep(0)
            yield event
        raise OSError(19, "No such device")


async def test_evdev_scanner_grabs_reads_and_reconnects() -> None:
    FakeInputDevice.instances = []
    FakeInputDevice.fail_open = 1
    fake = SimpleNamespace(InputDevice=FakeInputDevice, ecodes=SimpleNamespace(EV_KEY=EV_KEY))
    scans: list[str] = []
    presence: list[bool] = []
    scanner = EvdevScanner("/dev/input/scanner", scans.append, presence.append, evdev_module=fake, retry_s=0.01)
    scanner.start()
    for _ in range(200):
        await asyncio.sleep(0.005)
        if len(FakeInputDevice.instances) >= 2 and len(scans) >= 2:
            break
    await scanner.stop()
    assert scans[:2] == ["97", "97"]
    assert presence[:4] == [False, True, False, True]
    first = FakeInputDevice.instances[0]
    assert first.closed and not first.grabbed


def test_sim_scanner() -> None:
    scans: list[str] = []
    presence: list[bool] = []
    scanner = SimScanner(scans.append, presence.append)
    scanner.start()
    scanner.inject("web+spoolman:s-1")
    assert scans == ["web+spoolman:s-1"]
    assert presence == [True]

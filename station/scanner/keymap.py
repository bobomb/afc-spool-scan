"""Linux input keycodes to characters (port of usb-qr-scanner-read.sh)."""

from __future__ import annotations

KEYS = [
    "", "ESC", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "BACKSPACE", "TAB",
    "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]", "ENTER", "CTRL",
    "a", "s", "d", "f", "g", "h", "j", "k", "l", ";", "'", "`", "LSHIFT", "\\", "z", "x",
    "c", "v", "b", "n", "m", ",", ".", "/", "RSHIFT", "*", "ALT", "SPACE",
]
SHIFTED = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*",
    "9": "(", "0": ")", "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|", ";": ":",
    "'": '"', ",": "<", ".": ">", "/": "?",
}
IGNORED = {"ESC", "TAB", "CTRL", "ALT", ""}

KEY_RELEASE = 0
KEY_PRESS = 1


class KeyDecoder:
    """Accumulates key presses; returns the buffered code on ENTER."""

    def __init__(self) -> None:
        self.buffer = ""
        self.shift = False

    def feed(self, code: int, value: int) -> str | None:
        name = KEYS[code] if 0 <= code < len(KEYS) else ""
        if value == KEY_RELEASE:
            if name in ("LSHIFT", "RSHIFT"):
                self.shift = False
            return None
        if value != KEY_PRESS:
            return None
        if name in ("LSHIFT", "RSHIFT"):
            self.shift = True
        elif name == "ENTER":
            code_text, self.buffer = self.buffer, ""
            return code_text
        elif name == "BACKSPACE":
            self.buffer = self.buffer[:-1]
        elif name == "SPACE":
            self.buffer += " "
        elif name in IGNORED:
            pass
        else:
            if self.shift:
                name = name.upper() if name.isalpha() else SHIFTED.get(name, name)
            self.buffer += name
        return None

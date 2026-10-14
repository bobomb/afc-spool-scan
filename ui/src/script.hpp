#pragma once
// Headless snapshot scripts: scripted taps, keys and screenshots for visual review.
//
//   screen main|printers|log|settings
//   tap X Y            press and release at a point
//   key 0-9|enter|backspace|clear
//   type 97            several digit keys
//   wait 250           run the UI (and IPC) for N milliseconds
//   shot name          write name.png
//   idle dim|off|wake  force the idle state
//   request ACTION {"json": "args"}   send a protocol request (e.g. sim.scale)
//   # comment

#include <string>
#include <vector>

namespace station {

struct ScriptCommand {
    enum class Kind { Screen, Tap, Key, Type, Wait, Shot, Idle, Request };
    Kind kind = Kind::Wait;
    std::string text;
    std::string args;
    int x = 0;
    int y = 0;
    int ms = 0;
    int line = 0;
};

// Returns false and sets error ("line N: ...") on invalid input.
bool parse_script(const std::string& source, std::vector<ScriptCommand>& commands, std::string& error);

}  // namespace station

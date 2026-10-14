#include "script.hpp"

#include <cctype>
#include <sstream>

namespace station {
namespace {

bool parse_int(const std::string& text, int& out)
{
    if (text.empty()) return false;
    std::size_t pos = 0;
    try {
        out = std::stoi(text, &pos);
    } catch (...) {
        return false;
    }
    return pos == text.size();
}

bool valid_name(const std::string& text)
{
    if (text.empty()) return false;
    for (char c : text) {
        if (!std::isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_') return false;
    }
    return true;
}

}  // namespace

bool parse_script(const std::string& source, std::vector<ScriptCommand>& commands, std::string& error)
{
    commands.clear();
    std::istringstream input(source);
    std::string raw;
    int number = 0;
    while (std::getline(input, raw)) {
        ++number;
        if (!raw.empty() && raw.back() == '\r') raw.pop_back();
        std::istringstream first(raw);
        std::string leading;
        first >> leading;
        if (leading == "request") {
            std::string action;
            first >> action;
            std::string rest;
            std::getline(first, rest);
            const auto start = rest.find_first_not_of(" \t");
            rest = start == std::string::npos ? std::string() : rest.substr(start);
            const bool valid_action = !action.empty() && action.find_first_of("{}#\"") == std::string::npos;
            if (!valid_action || (!rest.empty() && (rest.front() != '{' || rest.back() != '}'))) {
                error = "line " + std::to_string(number) + ": request needs ACTION and an optional {json} object";
                return false;
            }
            ScriptCommand command;
            command.kind = ScriptCommand::Kind::Request;
            command.line = number;
            command.text = action;
            command.args = rest.empty() ? "{}" : rest;
            commands.push_back(command);
            continue;
        }
        const auto hash = raw.find('#');
        if (hash != std::string::npos) raw.erase(hash);
        std::istringstream words(raw);
        std::string verb;
        if (!(words >> verb)) continue;
        std::vector<std::string> args;
        for (std::string word; words >> word;) args.push_back(word);

        ScriptCommand command;
        command.line = number;
        auto fail = [&](const std::string& message) {
            error = "line " + std::to_string(number) + ": " + message;
            return false;
        };
        if (verb == "screen") {
            if (args.size() != 1 || (args[0] != "main" && args[0] != "printers" && args[0] != "log" &&
                                     args[0] != "settings")) {
                return fail("screen needs main, printers, log or settings");
            }
            command.kind = ScriptCommand::Kind::Screen;
            command.text = args[0];
        } else if (verb == "tap") {
            if (args.size() != 2 || !parse_int(args[0], command.x) || !parse_int(args[1], command.y) ||
                command.x < 0 || command.y < 0) {
                return fail("tap needs X Y");
            }
            command.kind = ScriptCommand::Kind::Tap;
        } else if (verb == "key") {
            const bool digit = args.size() == 1 && args[0].size() == 1 &&
                               std::isdigit(static_cast<unsigned char>(args[0][0]));
            if (args.size() != 1 || (!digit && args[0] != "enter" && args[0] != "backspace" &&
                                     args[0] != "clear")) {
                return fail("key needs a digit, enter, backspace or clear");
            }
            command.kind = ScriptCommand::Kind::Key;
            command.text = args[0];
        } else if (verb == "type") {
            if (args.size() != 1) return fail("type needs digits");
            for (char c : args[0]) {
                if (!std::isdigit(static_cast<unsigned char>(c))) return fail("type needs digits");
            }
            command.kind = ScriptCommand::Kind::Type;
            command.text = args[0];
        } else if (verb == "wait") {
            if (args.size() != 1 || !parse_int(args[0], command.ms) || command.ms < 0 || command.ms > 600000) {
                return fail("wait needs milliseconds");
            }
            command.kind = ScriptCommand::Kind::Wait;
        } else if (verb == "shot") {
            if (args.size() != 1 || !valid_name(args[0])) return fail("shot needs a file name");
            command.kind = ScriptCommand::Kind::Shot;
            command.text = args[0];
        } else if (verb == "idle") {
            if (args.size() != 1 || (args[0] != "dim" && args[0] != "off" && args[0] != "wake")) {
                return fail("idle needs dim, off or wake");
            }
            command.kind = ScriptCommand::Kind::Idle;
            command.text = args[0];
        } else {
            return fail("unknown command '" + verb + "'");
        }
        commands.push_back(command);
    }
    return true;
}

}  // namespace station

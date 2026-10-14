// station-ui: LVGL touch UI for the spool station service.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "app.hpp"
#include "platform.hpp"
#include "script.hpp"

using namespace station;

namespace {

struct Args {
    std::string host = "127.0.0.1";
    std::uint16_t port = 7913;
    std::string snapshot_dir;
    std::string state_file;
    std::string script_file;
    bool connect = false;
    int wait_ms = 8000;
    PlatformOptions platform;
};

void usage()
{
    std::printf(
        "station-ui %s\n"
        "Usage: station-ui [options]\n"
        "  --host HOST          service address (default 127.0.0.1)\n"
        "  --port PORT          service port (default 7913)\n"
        "  --zoom PERCENT       simulator window zoom (windows/sdl)\n"
        "  --drm-card PATH      DRM device (default /dev/dri/card1)\n"
        "  --touch PATH         evdev touch device (default: auto-discover)\n"
        "Snapshot mode (headless, writes PNGs):\n"
        "  --snapshot DIR       output directory\n"
        "  --state FILE         render a sample state file instead of connecting\n"
        "  --connect            connect to the running service (default without --state)\n"
        "  --script FILE        run a script of taps/keys/shots (see src/script.hpp)\n"
        "  --wait MS            how long to wait for the service snapshot (default 8000)\n",
        STATION_UI_VERSION);
}

bool parse_args(int argc, char** argv, Args& args)
{
    std::map<std::string, std::string*> strings = {
        {"--host", &args.host},         {"--snapshot", &args.snapshot_dir}, {"--state", &args.state_file},
        {"--script", &args.script_file}, {"--drm-card", &args.platform.drm_card},
        {"--touch", &args.platform.touch_device}};
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto next = [&](std::string& out) {
            if (i + 1 >= argc) return false;
            out = argv[++i];
            return true;
        };
        std::string value;
        if (arg == "-h" || arg == "--help") {
            usage();
            std::exit(0);
        } else if (arg == "--connect") {
            args.connect = true;
        } else if (strings.count(arg)) {
            if (!next(*strings[arg])) return false;
        } else if (arg == "--port" || arg == "--zoom" || arg == "--wait") {
            if (!next(value)) return false;
            char* end = nullptr;
            const long number = std::strtol(value.c_str(), &end, 10);
            if (end == value.c_str() || *end != '\0' || number < 0 || number > 600000) return false;
            if (arg == "--port") {
                if (number == 0 || number > 65535) return false;
                args.port = static_cast<std::uint16_t>(number);
            } else if (arg == "--zoom") {
                args.platform.zoom = static_cast<int>(number);
            } else {
                args.wait_ms = static_cast<int>(number);
            }
        } else {
            std::fprintf(stderr, "station-ui: unknown option %s\n", arg.c_str());
            return false;
        }
    }
    return true;
}

bool read_text(const std::string& path, std::string& out)
{
    std::ifstream file(path, std::ios::binary);
    if (!file) return false;
    std::stringstream buffer;
    buffer << file.rdbuf();
    out = buffer.str();
    return true;
}

void settle(HeadlessPlatform& platform, int ms)
{
    const std::uint64_t end = steady_ms() + static_cast<std::uint64_t>(ms);
    do {
        lv_timer_handler();
        platform.sleep_ms(5);
    } while (steady_ms() < end);
}

ScreenId screen_from(const std::string& name)
{
    if (name == "printers") return ScreenId::Printers;
    if (name == "log") return ScreenId::Log;
    if (name == "settings") return ScreenId::Settings;
    return ScreenId::Main;
}

int run_snapshot(App& app, HeadlessPlatform& platform, const Args& args)
{
    namespace fs = std::filesystem;
    std::error_code error;
    fs::create_directories(args.snapshot_dir, error);
    if (error) {
        std::fprintf(stderr, "station-ui: cannot create %s\n", args.snapshot_dir.c_str());
        return 2;
    }
    std::vector<std::string> screens = {"main", "printers", "log", "settings"};
    if (!args.state_file.empty()) {
        std::string text;
        if (!read_text(args.state_file, text)) {
            std::fprintf(stderr, "station-ui: cannot read %s\n", args.state_file.c_str());
            return 2;
        }
        const json sample = json::parse(text, nullptr, false);
        if (sample.is_discarded() || !sample.is_object()) {
            std::fprintf(stderr, "station-ui: %s is not a JSON object\n", args.state_file.c_str());
            return 2;
        }
        app.load_sample(sample);
        if (sample.contains("screens") && sample["screens"].is_array()) {
            screens.clear();
            for (const json& name : sample["screens"]) {
                if (name.is_string()) screens.push_back(name.get<std::string>());
            }
        }
    } else {
        const std::uint64_t deadline = steady_ms() + static_cast<std::uint64_t>(args.wait_ms);
        while (!app.online() && steady_ms() < deadline) {
            settle(platform, 20);
        }
        if (!app.online()) {
            std::fprintf(stderr, "station-ui: no snapshot from %s:%u within %d ms\n", args.host.c_str(), args.port,
                         args.wait_ms);
            return 3;
        }
    }
    settle(platform, 250);

    auto shot = [&](const std::string& name) {
        const std::string path = (fs::path(args.snapshot_dir) / (name + ".png")).string();
        if (!platform.save_png(path)) {
            std::fprintf(stderr, "station-ui: cannot write %s\n", path.c_str());
            return false;
        }
        std::printf("%s\n", path.c_str());
        return true;
    };

    if (args.script_file.empty()) {
        for (const std::string& name : screens) {
            app.show(screen_from(name));
            settle(platform, 120);
            if (!shot(name)) return 2;
        }
        return 0;
    }

    std::string source;
    if (!read_text(args.script_file, source)) {
        std::fprintf(stderr, "station-ui: cannot read %s\n", args.script_file.c_str());
        return 2;
    }
    std::vector<ScriptCommand> commands;
    std::string message;
    if (!parse_script(source, commands, message)) {
        std::fprintf(stderr, "station-ui: %s: %s\n", args.script_file.c_str(), message.c_str());
        return 2;
    }
    for (const ScriptCommand& command : commands) {
        switch (command.kind) {
        case ScriptCommand::Kind::Screen:
            app.show(screen_from(command.text));
            settle(platform, 120);
            break;
        case ScriptCommand::Kind::Tap:
            platform.press(command.x, command.y);
            settle(platform, 80);
            platform.release();
            settle(platform, 150);
            break;
        case ScriptCommand::Kind::Key:
            app.handle_key(command.text);
            settle(platform, 50);
            break;
        case ScriptCommand::Kind::Type:
            for (char digit : command.text) app.handle_key(std::string(1, digit));
            settle(platform, 50);
            break;
        case ScriptCommand::Kind::Wait:
            settle(platform, command.ms);
            break;
        case ScriptCommand::Kind::Shot:
            settle(platform, 60);
            if (!shot(command.text)) return 2;
            break;
        case ScriptCommand::Kind::Idle:
            app.idle().force(command.text == "off"   ? IdleManager::Level::Off
                             : command.text == "dim" ? IdleManager::Level::Dim
                                                     : IdleManager::Level::Awake);
            settle(platform, 80);
            break;
        case ScriptCommand::Kind::Request: {
            const json request_args = json::parse(command.args, nullptr, false);
            if (request_args.is_discarded() || !request_args.is_object()) {
                std::fprintf(stderr, "station-ui: script line %d: invalid JSON\n", command.line);
                return 2;
            }
            app.request(command.text, request_args, [](const Result& result) {
                if (!result.ok) std::fprintf(stderr, "station-ui: script request failed: %s\n", result.message.c_str());
            });
            settle(platform, 100);
            break;
        }
        }
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv)
{
    Args args;
    if (!parse_args(argc, argv, args)) {
        usage();
        return 2;
    }
    const bool headless = !args.snapshot_dir.empty();
    if (!headless && (!args.state_file.empty() || !args.script_file.empty())) {
        std::fprintf(stderr, "station-ui: --state and --script need --snapshot DIR\n");
        return 2;
    }

    lv_init();
#if !defined(STATION_UI_BACKEND_WINDOWS)
    lv_tick_set_cb(tick_ms);
#endif

    std::unique_ptr<Platform> platform;
    HeadlessPlatform* headless_platform = nullptr;
    if (headless) {
        auto owned = std::make_unique<HeadlessPlatform>();
        headless_platform = owned.get();
        platform = std::move(owned);
    } else {
        platform = create_native_platform();
    }
    if (!platform || !platform->init(args.platform)) {
        std::fprintf(stderr, "station-ui: cannot initialise the %s display\n",
                     platform ? platform->name() : "native");
        return 1;
    }

    App::Options options;
    options.host = args.host;
    options.port = args.port;
    options.use_ipc = !(headless && !args.state_file.empty());
    options.idle_enabled = !headless;
    App app(*platform, options);
    app.start();

    if (headless) {
        return run_snapshot(app, *headless_platform, args);
    }
    std::printf("station-ui %s: %s display, service %s:%u\n", STATION_UI_VERSION, platform->name(),
                args.host.c_str(), args.port);
    for (;;) {
        const std::uint32_t wait = lv_timer_handler();
        platform->sleep_ms(wait == LV_NO_TIMER_READY ? 10 : std::min<std::uint32_t>(wait, 10));
    }
}

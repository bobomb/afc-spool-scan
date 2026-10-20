#pragma once
// Client-side mirror of the service state (dev plan §5.2) with tolerant JSON parsing.

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "protocol.hpp"

namespace station {

enum Topic : std::uint32_t {
    kTopicScale = 1u << 0,
    kTopicScan = 1u << 1,
    kTopicSpool = 1u << 2,
    kTopicPrinters = 1u << 3,
    kTopicActivity = 1u << 4,
    kTopicHealth = 1u << 5,
    kTopicSettings = 1u << 6,
    kTopicService = 1u << 7,
    kTopicConnection = 1u << 8,
    kTopicAll = 0xFFFFu,
};

struct ScaleState {
    bool present = false;
    std::string status = "absent";
    std::optional<double> grams;
    std::string source_unit;
    bool stable = false;
    std::optional<double> tare_g;
    std::optional<double> net_g;
    std::optional<double> expected_g;
    std::optional<double> delta_g;
    std::string check;
};

struct Countdown {
    int spool_id = 0;
    std::string action;
    int remaining_s = 0;
};

struct Prompt {
    std::string kind;
    int spool_id = 0;
    std::string message;
    std::optional<double> gross_g;
    std::optional<double> tare_g;
    std::optional<double> net_g;
    std::optional<double> expected_g;
    std::optional<double> delta_g;
};

struct ScanState {
    std::string last_code;
    std::optional<int> spool_id;
    std::string at;
    std::optional<Countdown> countdown;
    std::optional<Prompt> prompt;
};

struct SpoolInfo {
    int id = 0;
    bool found = true;
    std::string vendor;
    std::string name;
    std::string material;
    std::string color;
    // Every filament colour (Spoolman multi_color_hexes); `color` is the first.
    std::vector<std::string> colors;
    std::optional<double> remaining_g;
    std::optional<double> spool_weight_g;
    std::optional<double> expected_gross_g;
    std::optional<double> initial_weight_g;
    std::optional<double> used_weight_g;
    std::string tare_source;
    std::string location;
    std::string last_used;
    bool archived = false;
    bool low_stock = false;
    std::string message;
};

struct Lane {
    std::string lane;
    std::string map;
    std::optional<int> spool_id;
    std::string material;
    std::string color;
    std::vector<std::string> colors;
    std::optional<double> remaining_g;
    // Remaining as a share of the spool's initial weight in Spoolman (0-100).
    std::optional<double> remaining_pct;
    std::string filament_status;
    std::string status;
    bool prep = false;
    bool load = false;
    bool tool_loaded = false;
    bool low_stock = false;
};

struct Printer {
    std::string key;
    std::string name;
    std::string display_name;
    bool connected = false;
    std::string klippy_state;
    std::string print_state;
    std::optional<double> progress;
    std::string filename;
    std::string afc_state;
    std::string afc_error;
    std::string current_load;
    std::optional<int> pending_spool;
    bool pending_confirmed = false;
    std::vector<Lane> lanes;

    // Mainsail printer name when the service has one, else the configured name.
    const std::string& label() const { return display_name.empty() ? name : display_name; }
};

struct Health {
    bool spoolman = false;
    bool scale = false;
    bool scanner = false;
    std::string scale_status = "absent";
};

struct ActivityEntry {
    std::string id;
    std::string at;
    std::string action;
    std::optional<int> spool_id;
    std::vector<std::string> printers;
    bool ok = false;
    std::string message;
    std::string code;
    bool dry_run = false;
    bool undone = false;
    bool undoable = false;
};

struct Settings {
    std::string scan_mode = "immediate";
    std::string theme = "dark";
    double sanity_threshold_g = 50;
    double sanity_threshold_pct = 10;
    double low_stock_g = 100;
    int undo_depth = 20;
    int idle_dim_s = 120;
    int idle_off_s = 300;
};

struct ServiceInfo {
    std::string version;
    int protocol = 0;
    std::string hardware;
    std::string printers;
    std::string spoolman;
    bool writes = false;
    bool dry_run = false;
};

struct State {
    ServiceInfo service;
    ScaleState scale;
    ScanState scan;
    std::optional<SpoolInfo> spool;
    std::vector<Printer> printers;
    Health health;
    std::vector<ActivityEntry> activity;
    Settings settings;
};

ScaleState parse_scale(const json& data);
ScanState parse_scan(const json& data);
std::optional<SpoolInfo> parse_spool(const json& data);
Printer parse_printer(const json& data);
Health parse_health(const json& data);
std::vector<ActivityEntry> parse_activity(const json& data);
Settings parse_settings(const json& data);
ServiceInfo parse_service(const json& data);

class Model {
public:
    // Each apply_* returns a Topic bitmask of what changed.
    std::uint32_t apply_hello(const json& hello);
    std::uint32_t apply_snapshot(const json& data);
    std::uint32_t apply_event(const std::string& topic, const json& data);
    std::uint32_t set_connected(bool connected);

    const State& state() const { return state_; }
    bool connected() const { return connected_; }
    bool has_snapshot() const { return has_snapshot_; }
    bool compatible() const { return protocol_ == 0 || protocol_ == kProtocolVersion; }
    int protocol() const { return protocol_; }

    const Printer* printer(const std::string& key) const;
    const ActivityEntry* activity(const std::string& id) const;

private:
    State state_;
    bool connected_ = false;
    bool has_snapshot_ = false;
    int protocol_ = 0;
};

}  // namespace station

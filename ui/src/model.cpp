#include "model.hpp"

#include <cctype>

namespace station {
namespace {

const json& field(const json& data, const char* key)
{
    static const json null_value;
    if (!data.is_object()) {
        return null_value;
    }
    const auto it = data.find(key);
    return it == data.end() ? null_value : *it;
}

std::string str(const json& data, const char* key, const std::string& fallback = std::string())
{
    const json& value = field(data, key);
    return value.is_string() ? value.get<std::string>() : fallback;
}

bool boolean(const json& data, const char* key, bool fallback = false)
{
    const json& value = field(data, key);
    return value.is_boolean() ? value.get<bool>() : fallback;
}

std::optional<double> number(const json& data, const char* key)
{
    const json& value = field(data, key);
    if (value.is_number()) {
        return value.get<double>();
    }
    return std::nullopt;
}

std::optional<int> integer(const json& data, const char* key)
{
    const json& value = field(data, key);
    if (value.is_number_integer()) {
        return value.get<int>();
    }
    if (value.is_number_float()) {
        return static_cast<int>(value.get<double>());
    }
    return std::nullopt;
}

double number_or(const json& data, const char* key, double fallback)
{
    return number(data, key).value_or(fallback);
}

std::vector<std::string> strings(const json& data, const char* key)
{
    std::vector<std::string> out;
    const json& value = field(data, key);
    if (value.is_array()) {
        for (const json& item : value) {
            if (item.is_string() && !item.get<std::string>().empty()) out.push_back(item.get<std::string>());
        }
    }
    return out;
}

}  // namespace

ScaleState parse_scale(const json& data)
{
    ScaleState scale;
    scale.present = boolean(data, "present");
    scale.status = str(data, "status", "absent");
    scale.grams = number(data, "grams");
    scale.source_unit = str(data, "source_unit");
    scale.stable = boolean(data, "stable", scale.present && scale.status == "stable");
    scale.tare_g = number(data, "tare_g");
    scale.net_g = number(data, "net_g");
    scale.expected_g = number(data, "expected_g");
    scale.delta_g = number(data, "delta_g");
    scale.check = str(data, "check");
    return scale;
}

ScanState parse_scan(const json& data)
{
    ScanState scan;
    scan.last_code = str(data, "last_code");
    scan.spool_id = integer(data, "spool_id");
    scan.at = str(data, "at");
    const json& countdown = field(data, "countdown");
    if (countdown.is_object()) {
        scan.countdown = Countdown{integer(countdown, "spool_id").value_or(0), str(countdown, "action"),
                                   integer(countdown, "remaining_s").value_or(0)};
    }
    const json& prompt = field(data, "prompt");
    if (prompt.is_object()) {
        Prompt p;
        p.kind = str(prompt, "kind");
        p.spool_id = integer(prompt, "spool_id").value_or(0);
        p.message = str(prompt, "message");
        p.gross_g = number(prompt, "gross_g");
        p.tare_g = number(prompt, "tare_g");
        p.net_g = number(prompt, "net_g");
        p.expected_g = number(prompt, "expected_g");
        p.delta_g = number(prompt, "delta_g");
        scan.prompt = p;
    }
    return scan;
}

std::optional<SpoolInfo> parse_spool(const json& data)
{
    if (!data.is_object()) {
        return std::nullopt;
    }
    const auto id = integer(data, "id");
    if (!id) {
        return std::nullopt;
    }
    SpoolInfo spool;
    spool.id = *id;
    spool.found = boolean(data, "found", true);
    spool.vendor = str(data, "vendor");
    spool.name = str(data, "name");
    spool.material = str(data, "material");
    spool.color = str(data, "color");
    spool.colors = strings(data, "colors");
    if (spool.colors.empty() && !spool.color.empty()) spool.colors.push_back(spool.color);
    spool.remaining_g = number(data, "remaining_g");
    spool.spool_weight_g = number(data, "spool_weight_g");
    spool.expected_gross_g = number(data, "expected_gross_g");
    spool.initial_weight_g = number(data, "initial_weight_g");
    spool.used_weight_g = number(data, "used_weight_g");
    spool.tare_source = str(data, "tare_source");
    spool.location = str(data, "location");
    spool.last_used = str(data, "last_used");
    spool.archived = boolean(data, "archived");
    spool.low_stock = boolean(data, "low_stock");
    spool.message = str(data, "message");
    return spool;
}

Printer parse_printer(const json& data)
{
    Printer printer;
    printer.name = str(data, "name");
    printer.key = str(data, "key");
    if (printer.key.empty()) {
        printer.key = printer.name;
        for (auto& c : printer.key) {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }
    printer.connected = boolean(data, "connected");
    printer.klippy_state = str(data, "klippy_state");
    printer.print_state = str(data, "print_state");
    printer.progress = number(data, "progress");
    printer.filename = str(data, "filename");
    printer.afc_state = str(data, "afc_state");
    printer.afc_error = str(data, "afc_error");
    printer.current_load = str(data, "current_load");
    printer.pending_spool = integer(data, "pending_spool");
    printer.pending_confirmed = boolean(data, "pending_confirmed");
    const json& lanes = field(data, "lanes");
    if (lanes.is_array()) {
        for (const json& item : lanes) {
            if (!item.is_object()) {
                continue;
            }
            Lane lane;
            lane.lane = str(item, "lane");
            lane.map = str(item, "map");
            lane.spool_id = integer(item, "spool_id");
            lane.material = str(item, "material");
            lane.color = str(item, "color");
            lane.colors = strings(item, "colors");
            if (lane.colors.empty() && !lane.color.empty()) lane.colors.push_back(lane.color);
            lane.remaining_g = number(item, "remaining_g");
            lane.remaining_pct = number(item, "remaining_pct");
            lane.filament_status = str(item, "filament_status");
            lane.status = str(item, "status");
            lane.prep = boolean(item, "prep");
            lane.load = boolean(item, "load");
            lane.tool_loaded = boolean(item, "tool_loaded");
            lane.low_stock = boolean(item, "low_stock");
            printer.lanes.push_back(std::move(lane));
        }
    }
    return printer;
}

Health parse_health(const json& data)
{
    Health health;
    health.spoolman = boolean(data, "spoolman");
    health.scale = boolean(data, "scale");
    health.scanner = boolean(data, "scanner");
    health.scale_status = str(data, "scale_status", "absent");
    return health;
}

std::vector<ActivityEntry> parse_activity(const json& data)
{
    std::vector<ActivityEntry> entries;
    if (!data.is_array()) {
        return entries;
    }
    for (const json& item : data) {
        if (!item.is_object()) {
            continue;
        }
        ActivityEntry entry;
        entry.id = str(item, "id");
        entry.at = str(item, "at");
        entry.action = str(item, "action");
        entry.spool_id = integer(item, "spool_id");
        const json& printers = field(item, "printers");
        if (printers.is_array()) {
            for (const json& name : printers) {
                if (name.is_string()) {
                    entry.printers.push_back(name.get<std::string>());
                }
            }
        }
        entry.ok = boolean(item, "ok");
        entry.message = str(item, "message");
        entry.code = str(item, "code");
        entry.dry_run = boolean(item, "dry_run");
        entry.undone = boolean(item, "undone");
        entry.undoable = boolean(item, "undoable");
        entries.push_back(std::move(entry));
    }
    return entries;
}

Settings parse_settings(const json& data)
{
    Settings settings;
    settings.target = str(data, "target", settings.target);
    settings.scan_mode = str(data, "scan_mode", settings.scan_mode);
    settings.theme = str(data, "theme", settings.theme);
    settings.sanity_threshold_g = number_or(data, "sanity_threshold_g", settings.sanity_threshold_g);
    settings.sanity_threshold_pct = number_or(data, "sanity_threshold_pct", settings.sanity_threshold_pct);
    settings.low_stock_g = number_or(data, "low_stock_g", settings.low_stock_g);
    settings.undo_depth = integer(data, "undo_depth").value_or(settings.undo_depth);
    settings.idle_dim_s = integer(data, "idle_dim_s").value_or(settings.idle_dim_s);
    settings.idle_off_s = integer(data, "idle_off_s").value_or(settings.idle_off_s);
    return settings;
}

ServiceInfo parse_service(const json& data)
{
    ServiceInfo service;
    service.version = str(data, "version");
    if (service.version.empty()) {
        service.version = str(data, "service_version");
    }
    service.protocol = integer(data, "protocol").value_or(0);
    service.hardware = str(data, "hardware");
    service.printers = str(data, "printers");
    service.spoolman = str(data, "spoolman");
    service.writes = boolean(data, "writes");
    service.dry_run = boolean(data, "dry_run");
    return service;
}

std::uint32_t Model::apply_hello(const json& hello)
{
    protocol_ = integer(hello, "protocol").value_or(0);
    ServiceInfo service = parse_service(hello);
    service.dry_run = state_.service.dry_run;
    state_.service = service;
    has_snapshot_ = false;
    return kTopicService | kTopicConnection;
}

std::uint32_t Model::apply_snapshot(const json& data)
{
    if (!data.is_object()) {
        return 0;
    }
    if (data.contains("service")) {
        state_.service = parse_service(data["service"]);
        if (protocol_ != 0) {
            state_.service.protocol = protocol_;
        }
    }
    state_.scale = parse_scale(field(data, "scale"));
    state_.scan = parse_scan(field(data, "scan"));
    state_.spool = parse_spool(field(data, "spool"));
    state_.printers.clear();
    const json& printers = field(data, "printers");
    if (printers.is_array()) {
        for (const json& item : printers) {
            state_.printers.push_back(parse_printer(item));
        }
    }
    state_.health = parse_health(field(data, "health"));
    state_.activity = parse_activity(field(data, "activity"));
    state_.settings = parse_settings(field(data, "settings"));
    has_snapshot_ = true;
    return kTopicAll;
}

std::uint32_t Model::apply_event(const std::string& topic, const json& data)
{
    if (topic == "scale") {
        state_.scale = parse_scale(data);
        return kTopicScale;
    }
    if (topic == "scan") {
        state_.scan = parse_scan(data);
        return kTopicScan;
    }
    if (topic == "spool") {
        state_.spool = parse_spool(data);
        return kTopicSpool;
    }
    if (topic == "printer" || topic == "printers") {
        if (data.is_array()) {
            state_.printers.clear();
            for (const json& item : data) {
                state_.printers.push_back(parse_printer(item));
            }
            return kTopicPrinters;
        }
        if (!data.is_object()) {
            return 0;
        }
        Printer printer = parse_printer(data);
        for (Printer& existing : state_.printers) {
            if (existing.key == printer.key) {
                existing = std::move(printer);
                return kTopicPrinters;
            }
        }
        state_.printers.push_back(std::move(printer));
        return kTopicPrinters;
    }
    if (topic == "activity") {
        state_.activity = parse_activity(data);
        return kTopicActivity;
    }
    if (topic == "health") {
        state_.health = parse_health(data);
        return kTopicHealth;
    }
    if (topic == "settings") {
        state_.settings = parse_settings(data);
        return kTopicSettings;
    }
    return 0;
}

std::uint32_t Model::set_connected(bool connected)
{
    if (connected_ == connected) {
        return 0;
    }
    connected_ = connected;
    if (!connected) {
        has_snapshot_ = false;
    }
    return kTopicConnection;
}

const Printer* Model::printer(const std::string& key) const
{
    for (const Printer& printer : state_.printers) {
        if (printer.key == key) {
            return &printer;
        }
    }
    return nullptr;
}

const ActivityEntry* Model::activity(const std::string& id) const
{
    for (const ActivityEntry& entry : state_.activity) {
        if (entry.id == id) {
            return &entry;
        }
    }
    return nullptr;
}

}  // namespace station

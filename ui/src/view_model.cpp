#include "view_model.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>

#include "format.hpp"

namespace station {
namespace {

double linear(std::uint32_t channel)
{
    const double v = static_cast<double>(channel & 0xFFu) / 255.0;
    return v <= 0.04045 ? v / 12.92 : std::pow((v + 0.055) / 1.055, 2.4);
}

std::string trim_lower(const std::string& text)
{
    std::size_t start = 0;
    std::size_t end = text.size();
    while (start < end && std::isspace(static_cast<unsigned char>(text[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    std::string out = text.substr(start, end - start);
    for (char& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

}  // namespace

double relative_luminance(std::uint32_t rgb)
{
    return 0.2126 * linear(rgb >> 16) + 0.7152 * linear(rgb >> 8) + 0.0722 * linear(rgb);
}

double contrast_ratio(std::uint32_t a, std::uint32_t b)
{
    const double la = relative_luminance(a);
    const double lb = relative_luminance(b);
    return (std::max(la, lb) + 0.05) / (std::min(la, lb) + 0.05);
}

std::uint32_t mark_color(const std::vector<std::uint32_t>& fills)
{
    if (fills.empty()) {
        return kMarkLight;
    }
    double light = 21.0;
    double dark = 21.0;
    for (std::uint32_t fill : fills) {
        light = std::min(light, contrast_ratio(fill, kMarkLight));
        dark = std::min(dark, contrast_ratio(fill, kMarkDark));
    }
    return light >= dark ? kMarkLight : kMarkDark;
}

std::vector<std::uint32_t> parse_colors(const std::vector<std::string>& hexes)
{
    constexpr std::uint32_t kInvalid = 0xFF000000u;
    std::vector<std::uint32_t> out;
    for (const std::string& hex : hexes) {
        const std::uint32_t color = parse_hex_color(hex, kInvalid);
        if (color != kInvalid) out.push_back(color);
    }
    return out;
}

std::vector<std::string> included_printers(const std::string& target, const std::vector<std::string>& keys)
{
    const std::string text = trim_lower(target);
    if (text.empty() || text == "both") {
        return keys;
    }
    std::vector<std::string> named;
    std::size_t start = 0;
    while (start <= text.size()) {
        const std::size_t comma = text.find(',', start);
        named.push_back(trim_lower(text.substr(start, comma == std::string::npos ? std::string::npos : comma - start)));
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    std::vector<std::string> out;
    for (const std::string& key : keys) {
        if (std::find(named.begin(), named.end(), key) != named.end()) out.push_back(key);
    }
    return out.empty() ? keys : out;
}

std::optional<std::string> toggle_target(const std::string& target, const std::vector<std::string>& keys,
                                         const std::string& key)
{
    if (std::find(keys.begin(), keys.end(), key) == keys.end()) {
        return target;
    }
    std::vector<std::string> included = included_printers(target, keys);
    const auto it = std::find(included.begin(), included.end(), key);
    if (it != included.end()) {
        if (included.size() == 1) return std::nullopt;
        included.erase(it);
    } else {
        included.push_back(key);
    }
    if (included.size() == keys.size()) {
        return std::string("both");
    }
    std::vector<std::string> ordered;
    for (const std::string& k : keys) {
        if (std::find(included.begin(), included.end(), k) != included.end()) ordered.push_back(k);
    }
    return join(ordered, ",");
}

std::optional<double> spool_remaining_pct(const SpoolInfo& spool)
{
    if (!spool.found || !spool.remaining_g || !spool.initial_weight_g || *spool.initial_weight_g <= 0) {
        return std::nullopt;
    }
    return std::clamp(*spool.remaining_g / *spool.initial_weight_g * 100.0, 0.0, 100.0);
}

HealthSummary summarize_health(const State& state, bool online)
{
    using Level = HealthSummary::Level;
    if (!online) {
        return {Level::Error, "Offline"};
    }
    struct Issue {
        Level level;
        std::string text;
    };
    std::vector<Issue> issues;
    if (!state.health.spoolman) issues.push_back({Level::Error, "Spoolman down"});
    for (const Printer& printer : state.printers) {
        if (!printer.connected) {
            issues.push_back({Level::Error, printer.name + " offline"});
        } else if (!printer.afc_error.empty()) {
            issues.push_back({Level::Warn, printer.name + " AFC error"});
        }
    }
    if (!state.health.scanner) issues.push_back({Level::Warn, "No scanner"});
    const std::string& scale = state.scale.status;
    if (!state.scale.present) {
        issues.push_back({Level::Note, "Scale off"});
    } else if (scale == "fault" || scale == "calibrate") {
        issues.push_back({Level::Warn, "Scale fault"});
    } else if (scale == "over") {
        issues.push_back({Level::Warn, "Scale over"});
    } else if (scale == "under" || scale == "rezero") {
        issues.push_back({Level::Warn, "Re-zero scale"});
    }
    if (issues.empty()) {
        return {Level::Ok, "All OK"};
    }
    std::stable_sort(issues.begin(), issues.end(),
                     [](const Issue& a, const Issue& b) { return static_cast<int>(a.level) > static_cast<int>(b.level); });
    HealthSummary summary{issues.front().level, issues.front().text};
    if (issues.size() > 1) {
        summary.text += " +" + std::to_string(issues.size() - 1);
    }
    return summary;
}

}  // namespace station

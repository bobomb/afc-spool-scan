#pragma once
// Pure view logic for the station screen: mark colours on filament fills, Load targets and the
// one-line connection summary in the side rail. No LVGL, so it is unit tested.

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "model.hpp"

namespace station {

inline constexpr std::uint32_t kMarkLight = 0xFFFFFF;
inline constexpr std::uint32_t kMarkDark = 0x14171C;

// WCAG relative luminance (0..1) and contrast ratio (1..21).
double relative_luminance(std::uint32_t rgb);
double contrast_ratio(std::uint32_t a, std::uint32_t b);
// White or near-black, whichever has the higher worst-case contrast over every fill colour.
std::uint32_t mark_color(const std::vector<std::uint32_t>& fills);
// "#RRGGBB" strings to colours; invalid entries are skipped.
std::vector<std::uint32_t> parse_colors(const std::vector<std::string>& hexes);

// The Load target setting is "both" (every printer) or comma-separated printer keys.
std::vector<std::string> included_printers(const std::string& target, const std::vector<std::string>& keys);
// Target after tapping printer `key`; nullopt when that would leave no printer included.
std::optional<std::string> toggle_target(const std::string& target, const std::vector<std::string>& keys,
                                         const std::string& key);

// Remaining share (0-100) of the selected spool when Spoolman knows its initial weight.
std::optional<double> spool_remaining_pct(const SpoolInfo& spool);

struct HealthSummary {
    enum class Level { Ok, Note, Warn, Error };
    Level level = Level::Ok;
    std::string text;
};
// "All OK", or the most serious problem first ("Yankee offline"), plus "+N" for the rest.
HealthSummary summarize_health(const State& state, bool online);

}  // namespace station

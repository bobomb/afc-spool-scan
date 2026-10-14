#pragma once
// Display formatting helpers (pure; unit tested).

#include <cstdint>
#include <ctime>
#include <optional>
#include <string>
#include <vector>

namespace station {

std::string fmt_number(double value, int decimals);
// "984 g"; empty optional gives "--".
std::string fmt_grams(std::optional<double> grams, int decimals = 0);
// "+349 g" / "-12 g".
std::string fmt_delta(double grams);
std::string scale_status_label(const std::string& status);
std::string print_state_label(const std::string& state, std::optional<double> progress);
std::string action_label(const std::string& action);
std::string capitalize(std::string text);
std::string join(const std::vector<std::string>& items, const std::string& separator);
// Parses "YYYY-MM-DDTHH:MM:SS[.fff][Z|+00:00]" as UTC.
std::optional<std::time_t> parse_iso_utc(const std::string& text);
// Local wall-clock "HH:MM:SS"; empty when the input is invalid.
std::string local_time_of_day(const std::string& iso_utc);
// Local calendar date "YYYY-MM-DD"; empty when the input is invalid.
std::string local_date(const std::string& iso_utc);
// "#RRGGBB" -> 0xRRGGBB, or fallback.
std::uint32_t parse_hex_color(const std::string& text, std::uint32_t fallback);
// Perceived luminance 0..255 for choosing readable text on a swatch.
int luminance(std::uint32_t rgb);

}  // namespace station

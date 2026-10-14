#include "format.hpp"

#include <cctype>
#include <cmath>
#include <cstdio>

namespace station {

std::string fmt_number(double value, int decimals)
{
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.*f", decimals, value);
    std::string text(buffer);
    if (text == "-0" || text == "-0.0") {
        text.erase(0, 1);
    }
    return text;
}

std::string fmt_grams(std::optional<double> grams, int decimals)
{
    if (!grams) {
        return "--";
    }
    return fmt_number(*grams, decimals) + " g";
}

std::string fmt_delta(double grams)
{
    const double rounded = std::round(grams);
    return (rounded < 0 ? "-" : "+") + fmt_number(std::fabs(rounded), 0) + " g";
}

std::string scale_status_label(const std::string& status)
{
    if (status == "stable") return "Ready";
    if (status == "zero") return "Empty";
    if (status == "motion") return "Settling";
    if (status == "under" || status == "rezero") return "Re-zero";
    if (status == "over") return "Overload";
    if (status == "fault" || status == "calibrate") return "Error";
    return "Off";
}

std::string print_state_label(const std::string& state, std::optional<double> progress)
{
    std::string label = state.empty() ? "Unknown" : capitalize(state);
    if ((state == "printing" || state == "paused") && progress) {
        label += " " + fmt_number(*progress * 100.0, 0) + "%";
    }
    return label;
}

std::string action_label(const std::string& action)
{
    if (action == "weigh") return "Weigh";
    if (action == "weigh_load") return "Weigh + Load";
    if (action == "load") return "Load";
    if (action == "scan") return "Scan";
    if (action == "assign_lane") return "Assign lane";
    if (action == "empty_spool") return "Empty spool";
    if (action == "clear_pending") return "Clear pending";
    if (action == "undo") return "Undo";
    if (action == "lookup") return "Look up";
    std::string label = action;
    for (auto& c : label) {
        if (c == '_') c = ' ';
    }
    return capitalize(label);
}

std::string capitalize(std::string text)
{
    if (!text.empty()) {
        text[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(text[0])));
    }
    return text;
}

std::string join(const std::vector<std::string>& items, const std::string& separator)
{
    std::string result;
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i) result += separator;
        result += items[i];
    }
    return result;
}

namespace {

bool digits(const std::string& text, std::size_t pos, std::size_t count, int& out)
{
    if (pos + count > text.size()) return false;
    out = 0;
    for (std::size_t i = pos; i < pos + count; ++i) {
        if (!std::isdigit(static_cast<unsigned char>(text[i]))) return false;
        out = out * 10 + (text[i] - '0');
    }
    return true;
}

// Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's algorithm).
long long days_from_civil(int y, unsigned m, unsigned d)
{
    y -= m <= 2;
    const long long era = (y >= 0 ? y : y - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(y - era * 400);
    const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + static_cast<long long>(doe) - 719468;
}

}  // namespace

std::optional<std::time_t> parse_iso_utc(const std::string& text)
{
    int year, month, day, hour, minute, second;
    if (!digits(text, 0, 4, year) || text.size() < 19 || text[4] != '-' || !digits(text, 5, 2, month) ||
        text[7] != '-' || !digits(text, 8, 2, day) || (text[10] != 'T' && text[10] != ' ') ||
        !digits(text, 11, 2, hour) || text[13] != ':' || !digits(text, 14, 2, minute) || text[16] != ':' ||
        !digits(text, 17, 2, second)) {
        return std::nullopt;
    }
    if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 60) {
        return std::nullopt;
    }
    std::size_t pos = 19;
    if (pos < text.size() && text[pos] == '.') {
        ++pos;
        while (pos < text.size() && std::isdigit(static_cast<unsigned char>(text[pos]))) ++pos;
    }
    long long offset = 0;
    if (pos < text.size()) {
        const char sign = text[pos];
        int oh = 0, om = 0;
        if (sign == 'Z' && pos + 1 == text.size()) {
            offset = 0;
        } else if ((sign == '+' || sign == '-') && digits(text, pos + 1, 2, oh) && text.size() == pos + 6 &&
                   text[pos + 3] == ':' && digits(text, pos + 4, 2, om)) {
            offset = (sign == '+' ? 1 : -1) * (oh * 3600LL + om * 60LL);
        } else {
            return std::nullopt;
        }
    }
    const long long days = days_from_civil(year, static_cast<unsigned>(month), static_cast<unsigned>(day));
    return static_cast<std::time_t>(days * 86400LL + hour * 3600LL + minute * 60LL + second - offset);
}

namespace {

bool local_tm(const std::string& iso_utc, std::tm& local)
{
    const auto when = parse_iso_utc(iso_utc);
    if (!when) return false;
#ifdef _WIN32
    return localtime_s(&local, &*when) == 0;
#else
    return localtime_r(&*when, &local) != nullptr;
#endif
}

}  // namespace

std::string local_time_of_day(const std::string& iso_utc)
{
    std::tm local{};
    if (!local_tm(iso_utc, local)) return std::string();
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "%02d:%02d:%02d", local.tm_hour, local.tm_min, local.tm_sec);
    return buffer;
}

std::string local_date(const std::string& iso_utc)
{
    std::tm local{};
    if (!local_tm(iso_utc, local)) return std::string();
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "%04d-%02d-%02d", local.tm_year + 1900, local.tm_mon + 1, local.tm_mday);
    return buffer;
}

std::uint32_t parse_hex_color(const std::string& text, std::uint32_t fallback)
{
    std::size_t start = !text.empty() && text[0] == '#' ? 1 : 0;
    if (text.size() < start + 6) return fallback;
    std::uint32_t value = 0;
    for (std::size_t i = start; i < start + 6; ++i) {
        const char c = static_cast<char>(std::tolower(static_cast<unsigned char>(text[i])));
        value <<= 4;
        if (c >= '0' && c <= '9') value |= static_cast<std::uint32_t>(c - '0');
        else if (c >= 'a' && c <= 'f') value |= static_cast<std::uint32_t>(c - 'a' + 10);
        else return fallback;
    }
    return value;
}

int luminance(std::uint32_t rgb)
{
    const int r = (rgb >> 16) & 0xFF, g = (rgb >> 8) & 0xFF, b = rgb & 0xFF;
    return (r * 299 + g * 587 + b * 114) / 1000;
}

}  // namespace station

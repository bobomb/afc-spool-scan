#include <doctest/doctest.h>

#include "format.hpp"

using namespace station;

TEST_CASE("weights and deltas")
{
    CHECK(fmt_grams(984.04) == "984 g");
    CHECK(fmt_grams(984.04, 1) == "984.0 g");
    CHECK(fmt_grams(std::nullopt) == "--");
    CHECK(fmt_delta(349.3) == "+349 g");
    CHECK(fmt_delta(-12.6) == "-13 g");
    CHECK(fmt_delta(-0.2) == "+0 g");
    CHECK(fmt_number(-0.04, 1) == "0.0");
}

TEST_CASE("labels")
{
    CHECK(scale_status_label("stable") == "Ready");
    CHECK(scale_status_label("zero") == "Empty");
    CHECK(scale_status_label("motion") == "Settling");
    CHECK(scale_status_label("under") == "Re-zero");
    CHECK(scale_status_label("rezero") == "Re-zero");
    CHECK(scale_status_label("over") == "Overload");
    CHECK(scale_status_label("fault") == "Error");
    CHECK(scale_status_label("calibrate") == "Error");
    CHECK(scale_status_label("absent") == "Off");
    CHECK(print_state_label("printing", 0.424) == "Printing 42%");
    CHECK(print_state_label("complete", 1.0) == "Complete");
    CHECK(print_state_label("", std::nullopt) == "Unknown");
    CHECK(action_label("weigh_load") == "Weigh + Load");
    CHECK(action_label("assign_lane") == "Assign lane");
    CHECK(action_label("new_thing") == "New thing");
    CHECK(join({"Kilo", "Yankee"}, ", ") == "Kilo, Yankee");
    CHECK(join({}, ", ").empty());
}

TEST_CASE("ISO timestamps")
{
    CHECK(parse_iso_utc("1970-01-01T00:00:00Z") == 0);
    CHECK(parse_iso_utc("2026-10-13T21:00:00Z") == 1791925200);
    CHECK(parse_iso_utc("2026-10-13T21:00:00.123+00:00") == 1791925200);
    CHECK(parse_iso_utc("2026-10-13T23:00:00+02:00") == 1791925200);
    CHECK(parse_iso_utc("2026-10-13 21:00:00") == 1791925200);
    CHECK_FALSE(parse_iso_utc("yesterday"));
    CHECK_FALSE(parse_iso_utc("2026-13-01T00:00:00Z"));
    CHECK_FALSE(parse_iso_utc("2026-10-13T21:00:00X"));
    CHECK(local_time_of_day("2026-10-13T21:00:00Z").size() == 8);
    CHECK(local_time_of_day("nope").empty());
    CHECK(local_date("2026-10-01T12:00:00Z").size() == 10);
    CHECK(local_date("2026-10-01T12:00:00Z").rfind("2026-", 0) == 0);
    CHECK(local_date("").empty());
}

TEST_CASE("colors")
{
    CHECK(parse_hex_color("#FFFFFF", 0) == 0xFFFFFF);
    CHECK(parse_hex_color("1e5aa8", 0) == 0x1E5AA8);
    CHECK(parse_hex_color("#12", 7) == 7);
    CHECK(parse_hex_color("#GG0000", 7) == 7);
    CHECK(luminance(0xFFFFFF) == 255);
    CHECK(luminance(0x000000) == 0);
    CHECK(luminance(0x1A1A1A) < 60);
}

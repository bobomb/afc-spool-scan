#include <doctest/doctest.h>

#include "view_model.hpp"

using namespace station;

TEST_CASE("mark colour picks the higher contrast over the fill")
{
    CHECK(contrast_ratio(0xFFFFFF, 0x000000) == doctest::Approx(21.0));
    CHECK(contrast_ratio(0x777777, 0x777777) == doctest::Approx(1.0));
    CHECK(mark_color({0xF2F2F2}) == kMarkDark);
    CHECK(mark_color({0xF5D90A}) == kMarkDark);
    CHECK(mark_color({0xF57C00}) == kMarkDark);
    CHECK(mark_color({0x8A8A8A}) == kMarkDark);
    CHECK(mark_color({0x202020}) == kMarkLight);
    CHECK(mark_color({0x2A5DB0}) == kMarkLight);
    CHECK(mark_color({0xD32F2F}) == kMarkLight);
    CHECK(mark_color({}) == kMarkLight);
    // Multi-colour: purple alone takes dark marks, and the light blue and yellow stops agree.
    CHECK(mark_color({0xC94CE0, 0x33B5E5, 0xF2C14E}) == kMarkDark);
    // Worst case decides: on black + white stripes near-black keeps slightly more contrast.
    CHECK(mark_color({0x000000, 0xFFFFFF}) == kMarkDark);
}

TEST_CASE("colour strings parse and skip invalid entries")
{
    const auto colors = parse_colors({"#C94CE0", "nope", "33b5e5", ""});
    REQUIRE(colors.size() == 2);
    CHECK(colors[0] == 0xC94CE0);
    CHECK(colors[1] == 0x33B5E5);
}

TEST_CASE("selected spool remaining percent")
{
    SpoolInfo spool;
    spool.remaining_g = 701;
    spool.initial_weight_g = 1000;
    CHECK(*spool_remaining_pct(spool) == doctest::Approx(70.1));
    spool.remaining_g = 1200;
    CHECK(*spool_remaining_pct(spool) == doctest::Approx(100.0));
    spool.initial_weight_g.reset();
    CHECK_FALSE(spool_remaining_pct(spool).has_value());
    spool.initial_weight_g = 1000;
    spool.found = false;
    CHECK_FALSE(spool_remaining_pct(spool).has_value());
}

TEST_CASE("side rail status summary")
{
    using Level = HealthSummary::Level;
    State state;
    state.health.spoolman = true;
    state.health.scanner = true;
    state.scale.present = true;
    state.scale.status = "stable";
    Printer kilo;
    kilo.name = "Kilo";
    kilo.connected = true;
    Printer yankee = kilo;
    yankee.name = "Yankee";
    yankee.display_name = "Yeti";
    state.printers = {kilo, yankee};

    CHECK(summarize_health(state, false).text == "Offline");
    auto summary = summarize_health(state, true);
    CHECK(summary.level == Level::Ok);
    CHECK(summary.text == "All OK");

    state.scale.present = false;
    summary = summarize_health(state, true);
    CHECK(summary.level == Level::Note);
    CHECK(summary.text == "Scale off");

    state.printers[1].connected = false;
    state.printers[0].afc_error = "jam";
    summary = summarize_health(state, true);
    CHECK(summary.level == Level::Error);
    CHECK(summary.text == "Yeti offline +2");
}

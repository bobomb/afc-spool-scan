#include <doctest/doctest.h>

#include <fstream>
#include <sstream>

#include "model.hpp"

using namespace station;

namespace {

const char* kSnapshot = R"({
  "service": {"version": "0.1.0", "protocol": 1, "hardware": "sim", "printers": "sim",
              "spoolman": "sim", "writes": false, "dry_run": false},
  "scale": {"present": true, "status": "stable", "grams": 984.0, "source_unit": "g", "stable": true,
            "tare_g": 180.0, "net_g": 804.0, "expected_g": 634.7, "delta_g": 349.3, "check": "warn"},
  "scan": {"last_code": "WEB+SPOOLMAN:S-97", "spool_id": 97, "at": "2026-10-13T21:00:00Z",
           "countdown": null, "prompt": null},
  "spool": {"id": 97, "found": true, "vendor": "Sunlu", "name": "ABS White", "material": "ABS",
            "color": "#FFFFFF", "remaining_g": 454.7, "spool_weight_g": 180.0, "expected_gross_g": 634.7,
            "location": null, "last_used": "2026-10-01T07:16:18Z", "archived": false, "low_stock": false},
  "printers": [
    {"key": "kilo", "name": "Kilo", "display_name": "Kestrel", "connected": true, "print_state": "complete", "progress": 1.0,
     "afc_state": "Idle", "afc_error": null, "current_load": "lane2", "pending_spool": 97,
     "pending_confirmed": true,
     "lanes": [{"lane": "lane1", "map": "T0", "spool_id": 84, "material": "PLA", "color": "#FFFFFF",
                "remaining_g": 888.0, "filament_status": "Ready", "tool_loaded": false, "low_stock": false,
                "remaining_pct": 88.8, "colors": ["#FFFFFF", "#33B5E5"]},
               {"lane": "lane4", "map": "T3", "spool_id": null, "material": null, "color": null,
                "remaining_g": null, "filament_status": "Not Ready", "tool_loaded": false}]}
  ],
  "health": {"spoolman": true, "scale": true, "scanner": false, "scale_status": "stable"},
  "activity": [{"id": "a-41", "at": "2026-10-13T21:00:01Z", "action": "weigh_load", "spool_id": 97,
                "printers": ["Kilo"], "ok": true, "message": "984 g saved; next spool set",
                "undoable": true}],
  "settings": {"scan_mode": "immediate", "theme": "dark", "sanity_threshold_g": 50,
               "sanity_threshold_pct": 10, "low_stock_g": 100, "undo_depth": 20, "idle_dim_s": 120,
               "idle_off_s": 300}
})";

}  // namespace

TEST_CASE("snapshot populates the full state")
{
    Model model;
    CHECK((model.apply_hello(json::parse(R"({"type":"hello","protocol":1,"service_version":"0.1.0"})")) &
           kTopicService) != 0);
    CHECK(model.compatible());
    CHECK(model.apply_snapshot(json::parse(kSnapshot)) == kTopicAll);
    const State& s = model.state();
    CHECK(model.has_snapshot());
    CHECK(s.service.version == "0.1.0");
    CHECK(s.scale.grams == doctest::Approx(984.0));
    CHECK(s.scale.check == "warn");
    CHECK(*s.scale.delta_g == doctest::Approx(349.3));
    CHECK(s.scan.spool_id == 97);
    REQUIRE(s.spool);
    CHECK(s.spool->vendor == "Sunlu");
    CHECK(s.spool->location.empty());
    CHECK(s.spool->colors == std::vector<std::string>{"#FFFFFF"});
    REQUIRE(s.printers.size() == 1);
    CHECK(s.printers[0].name == "Kilo");
    CHECK(s.printers[0].label() == "Kestrel");
    REQUIRE(s.printers[0].lanes.size() == 2);
    CHECK(*s.printers[0].lanes[0].remaining_pct == doctest::Approx(88.8));
    CHECK(s.printers[0].lanes[0].colors == std::vector<std::string>{"#FFFFFF", "#33B5E5"});
    CHECK_FALSE(s.printers[0].lanes[1].remaining_pct.has_value());
    CHECK(s.printers[0].lanes[1].colors.empty());
    CHECK(s.printers[0].pending_spool == 97);
    REQUIRE(s.printers[0].lanes.size() == 2);
    CHECK(s.printers[0].lanes[0].spool_id == 84);
    CHECK_FALSE(s.printers[0].lanes[1].spool_id);
    CHECK(s.printers[0].lanes[1].material.empty());
    CHECK_FALSE(s.health.scanner);
    REQUIRE(s.activity.size() == 1);
    CHECK(s.activity[0].undoable);
    CHECK(s.activity[0].printers == std::vector<std::string>{"Kilo"});
    CHECK(s.settings.idle_off_s == 300);
    CHECK(model.activity("a-41") != nullptr);
    CHECK(model.printer("kilo") != nullptr);
    CHECK(model.printer("prusa") == nullptr);
}

TEST_CASE("events replace subtrees and printer events merge by key")
{
    Model model;
    model.apply_snapshot(json::parse(kSnapshot));
    CHECK(model.apply_event("scale", json::parse(R"({"present":true,"status":"motion","grams":12.5})")) ==
          kTopicScale);
    CHECK(model.state().scale.status == "motion");
    CHECK_FALSE(model.state().scale.delta_g);

    CHECK(model.apply_event("printer", json::parse(R"({"key":"yankee","name":"Yankee","connected":false})")) ==
          kTopicPrinters);
    CHECK(model.state().printers.size() == 2);
    CHECK(model.state().printers[1].label() == "Yankee");
    model.apply_event("printer", json::parse(R"({"key":"kilo","name":"Kilo","connected":false,"lanes":[]})"));
    CHECK(model.state().printers.size() == 2);
    CHECK(model.state().printers[0].label() == "Kilo");
    CHECK_FALSE(model.state().printers[0].connected);
    CHECK(model.state().printers[0].lanes.empty());

    model.apply_event("spool", json());
    CHECK_FALSE(model.state().spool);
    model.apply_event("spool", json::parse(R"({"id":999,"found":false,"message":"Spool 999 not found"})"));
    REQUIRE(model.state().spool);
    CHECK_FALSE(model.state().spool->found);

    model.apply_event("scan", json::parse(
        R"({"spool_id":97,"countdown":{"spool_id":97,"action":"weigh_load","remaining_s":3},)"
        R"("prompt":{"kind":"confirm_weigh","spool_id":97,"message":"m","delta_g":349.3}})"));
    REQUIRE(model.state().scan.countdown);
    CHECK(model.state().scan.countdown->remaining_s == 3);
    REQUIRE(model.state().scan.prompt);
    CHECK(*model.state().scan.prompt->delta_g == doctest::Approx(349.3));

    model.apply_event("settings", json::parse(R"({"theme":"light","undo_depth":5})"));
    CHECK(model.state().settings.theme == "light");
    CHECK(model.state().settings.scan_mode == "immediate");
    CHECK(model.apply_event("bogus", json::object()) == 0);
}

TEST_CASE("tolerates wrong types and missing fields")
{
    Model model;
    model.apply_snapshot(json::parse(R"({"scale":{"present":"yes","grams":"heavy"},"printers":[1,{"name":"X"}],)"
                                     R"("activity":{"not":"a list"},"settings":[]})"));
    CHECK_FALSE(model.state().scale.present);
    CHECK_FALSE(model.state().scale.grams);
    REQUIRE(model.state().printers.size() == 2);
    CHECK(model.state().printers[1].key == "x");
    CHECK(model.state().activity.empty());
    CHECK(model.state().settings.scan_mode == "immediate");
    CHECK(model.apply_snapshot(json::array()) == 0);
}

TEST_CASE("protocol mismatch and connection state")
{
    Model model;
    model.apply_hello(json::parse(R"({"protocol":2})"));
    CHECK_FALSE(model.compatible());
    CHECK(model.protocol() == 2);
    CHECK(model.set_connected(true) == kTopicConnection);
    CHECK(model.set_connected(true) == 0);
    model.apply_snapshot(json::object());
    CHECK(model.has_snapshot());
    model.set_connected(false);
    CHECK_FALSE(model.has_snapshot());
}

TEST_CASE("sample state files parse")
{
    for (const char* name : {"main.json", "printers.json", "log.json", "settings.json"}) {
        std::ifstream file(std::string(STATION_UI_SAMPLES) + "/" + name);
        REQUIRE_MESSAGE(file, name);
        std::stringstream text;
        text << file.rdbuf();
        const json sample = json::parse(text.str());
        Model model;
        model.apply_snapshot(sample.contains("snapshot") ? sample["snapshot"] : sample);
        CHECK_MESSAGE(model.state().printers.size() == 2, name);
    }
}

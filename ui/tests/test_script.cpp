#include <doctest/doctest.h>

#include "script.hpp"

using namespace station;

TEST_CASE("parses every command")
{
    std::vector<ScriptCommand> commands;
    std::string error;
    const char* source =
        "# demo\n"
        "screen printers\n"
        "tap 120 300   # lane\n"
        "\n"
        "key enter\n"
        "key 7\n"
        "type 97\n"
        "wait 250\n"
        "shot after-tap\n"
        "idle off\n";
    REQUIRE(parse_script(source, commands, error));
    REQUIRE(commands.size() == 8);
    CHECK(commands[0].kind == ScriptCommand::Kind::Screen);
    CHECK(commands[0].text == "printers");
    CHECK(commands[1].kind == ScriptCommand::Kind::Tap);
    CHECK(commands[1].x == 120);
    CHECK(commands[1].y == 300);
    CHECK(commands[1].line == 3);
    CHECK(commands[2].text == "enter");
    CHECK(commands[3].text == "7");
    CHECK(commands[4].text == "97");
    CHECK(commands[5].ms == 250);
    CHECK(commands[6].text == "after-tap");
    CHECK(commands[7].kind == ScriptCommand::Kind::Idle);
}

TEST_CASE("request commands keep their JSON")
{
    std::vector<ScriptCommand> commands;
    std::string error;
    REQUIRE(parse_script("request sim.scale {\"grams\": 984, \"note\": \"#1\"}\r\nrequest cancel_countdown\n",
                         commands, error));
    REQUIRE(commands.size() == 2);
    CHECK(commands[0].kind == ScriptCommand::Kind::Request);
    CHECK(commands[0].text == "sim.scale");
    CHECK(commands[0].args == "{\"grams\": 984, \"note\": \"#1\"}");
    CHECK(commands[1].args == "{}");
    CHECK_FALSE(parse_script("request\n", commands, error));
    CHECK_FALSE(parse_script("request weigh [1]\n", commands, error));
}

TEST_CASE("reports errors with line numbers")
{
    std::vector<ScriptCommand> commands;
    std::string error;
    for (const char* bad : {"screen kitchen", "tap 1", "tap a b", "tap -1 5", "key x", "type 9a", "wait -5",
                            "shot ../evil", "idle nap", "jump"}) {
        CHECK_FALSE_MESSAGE(parse_script(std::string("wait 1\n") + bad, commands, error), bad);
        CHECK(error.rfind("line 2:", 0) == 0);
    }
}

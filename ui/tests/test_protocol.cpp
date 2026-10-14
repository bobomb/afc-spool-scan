#include <doctest/doctest.h>

#include "protocol.hpp"

using namespace station;

TEST_CASE("line buffer splits lines across chunks")
{
    LineBuffer buffer;
    CHECK(buffer.append("{\"a\":1}\n{\"b\"", 12));
    auto first = buffer.next_line();
    REQUIRE(first);
    CHECK(*first == "{\"a\":1}");
    CHECK_FALSE(buffer.next_line());
    CHECK(buffer.append(":2}\r\n\n", 6));
    auto second = buffer.next_line();
    REQUIRE(second);
    CHECK(*second == "{\"b\":2}");
    auto empty = buffer.next_line();
    REQUIRE(empty);
    CHECK(empty->empty());
    CHECK(buffer.pending() == 0);
}

TEST_CASE("line buffer rejects oversized lines")
{
    LineBuffer buffer(8);
    CHECK_FALSE(buffer.append("0123456789", 10));
    CHECK(buffer.pending() == 0);
    CHECK(buffer.append("ok\n", 3));
    CHECK(*buffer.next_line() == "ok");
}

TEST_CASE("parse_message classifies messages and survives garbage")
{
    CHECK(parse_message(R"({"type":"hello","protocol":1})").type == MessageType::Hello);
    CHECK(parse_message(R"({"type":"snapshot","data":{}})").type == MessageType::Snapshot);
    CHECK(parse_message(R"({"type":"event","topic":"scale","data":{}})").type == MessageType::Event);
    CHECK(parse_message(R"({"type":"result","id":"u-1","ok":true})").type == MessageType::Result);
    CHECK(parse_message(R"({"type":"other"})").type == MessageType::Unknown);
    CHECK(parse_message("{not json").type == MessageType::Unknown);
    CHECK(parse_message("[1,2]").type == MessageType::Unknown);
    CHECK(parse_message(R"({"type":5})").type == MessageType::Unknown);
}

TEST_CASE("encode_request produces one protocol line")
{
    const std::string line = encode_request("u-7", "weigh", json{{"spool_id", 97}, {"confirm", true}});
    CHECK(line.back() == '\n');
    CHECK(line.find('\n') == line.size() - 1);
    const json parsed = json::parse(line);
    CHECK(parsed["type"] == "request");
    CHECK(parsed["id"] == "u-7");
    CHECK(parsed["action"] == "weigh");
    CHECK(parsed["args"]["spool_id"] == 97);
    CHECK(json::parse(encode_request("u-8", "cancel_countdown", json()))["args"] == json::object());
}

TEST_CASE("parse_result reads all fields")
{
    const json body = json::parse(
        R"({"type":"result","id":"u-3","ok":false,"code":"needs_confirm","message":"differs",)"
        R"("data":{"delta_g":349.3},"dry_run":true,"activity_id":"a-4"})");
    const Result result = parse_result(body);
    CHECK(result.id == "u-3");
    CHECK_FALSE(result.ok);
    CHECK(result.code == "needs_confirm");
    CHECK(result.message == "differs");
    CHECK(result.data["delta_g"] == doctest::Approx(349.3));
    CHECK(result.dry_run);
    CHECK(result.activity_id == "a-4");
    CHECK(parse_result(json::parse(R"({"id":5,"ok":true})")).id == "5");
}

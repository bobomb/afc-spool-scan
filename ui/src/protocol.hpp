#pragma once
// Protocol v1 framing and message helpers (dev plan §5).

#include <cstddef>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

namespace station {

using json = nlohmann::json;

inline constexpr int kProtocolVersion = 1;
inline constexpr std::size_t kMaxLineBytes = 1u << 20;

// Splits a byte stream into newline-terminated lines.
class LineBuffer {
public:
    explicit LineBuffer(std::size_t max_line = kMaxLineBytes) : max_line_(max_line) {}

    // Returns false if a line grew beyond the limit; the buffer is then cleared.
    bool append(const char* data, std::size_t size);
    std::optional<std::string> next_line();
    void clear();
    std::size_t pending() const { return buffer_.size(); }

private:
    std::string buffer_;
    std::size_t max_line_;
    std::size_t scan_from_ = 0;
};

enum class MessageType { Hello, Snapshot, Event, Result, Unknown };

struct Message {
    MessageType type = MessageType::Unknown;
    json body;
};

// Never throws; malformed input yields MessageType::Unknown.
Message parse_message(const std::string& line);

std::string encode_request(const std::string& id, const std::string& action, const json& args);

struct Result {
    std::string id;
    bool ok = false;
    std::string message;
    std::string code;
    std::string activity_id;
    bool dry_run = false;
    json data;
};

Result parse_result(const json& body);

}  // namespace station

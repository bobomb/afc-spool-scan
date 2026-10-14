#include "protocol.hpp"

namespace station {

bool LineBuffer::append(const char* data, std::size_t size)
{
    buffer_.append(data, size);
    if (buffer_.find('\n', scan_from_) == std::string::npos) {
        scan_from_ = buffer_.size();
        if (buffer_.size() > max_line_) {
            clear();
            return false;
        }
    }
    return true;
}

std::optional<std::string> LineBuffer::next_line()
{
    const auto end = buffer_.find('\n');
    if (end == std::string::npos) {
        scan_from_ = buffer_.size();
        return std::nullopt;
    }
    std::string line = buffer_.substr(0, end);
    buffer_.erase(0, end + 1);
    scan_from_ = 0;
    if (!line.empty() && line.back() == '\r') {
        line.pop_back();
    }
    if (line.size() > max_line_) {
        return std::string();
    }
    return line;
}

void LineBuffer::clear()
{
    buffer_.clear();
    scan_from_ = 0;
}

Message parse_message(const std::string& line)
{
    Message message;
    json body = json::parse(line, nullptr, false);
    if (body.is_discarded() || !body.is_object()) {
        return message;
    }
    const auto type = body.find("type");
    if (type == body.end() || !type->is_string()) {
        return message;
    }
    const std::string& name = type->get_ref<const std::string&>();
    if (name == "hello") {
        message.type = MessageType::Hello;
    } else if (name == "snapshot") {
        message.type = MessageType::Snapshot;
    } else if (name == "event") {
        message.type = MessageType::Event;
    } else if (name == "result") {
        message.type = MessageType::Result;
    }
    message.body = std::move(body);
    return message;
}

std::string encode_request(const std::string& id, const std::string& action, const json& args)
{
    json request = {{"type", "request"}, {"id", id}, {"action", action},
                    {"args", args.is_object() ? args : json::object()}};
    return request.dump(-1, ' ', false, json::error_handler_t::replace) + "\n";
}

namespace {

std::string string_field(const json& body, const char* key)
{
    const auto it = body.find(key);
    return it != body.end() && it->is_string() ? it->get<std::string>() : std::string();
}

}  // namespace

Result parse_result(const json& body)
{
    Result result;
    if (!body.is_object()) {
        return result;
    }
    const auto id = body.find("id");
    if (id != body.end()) {
        result.id = id->is_string() ? id->get<std::string>() : id->dump();
    }
    const auto ok = body.find("ok");
    result.ok = ok != body.end() && ok->is_boolean() && ok->get<bool>();
    result.message = string_field(body, "message");
    result.code = string_field(body, "code");
    result.activity_id = string_field(body, "activity_id");
    const auto dry = body.find("dry_run");
    result.dry_run = dry != body.end() && dry->is_boolean() && dry->get<bool>();
    const auto data = body.find("data");
    if (data != body.end()) {
        result.data = *data;
    }
    return result;
}

}  // namespace station

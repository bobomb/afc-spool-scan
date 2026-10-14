#pragma once
// Non-blocking TCP client for the station IPC (newline-delimited JSON).
// Polled from the UI thread; reconnects automatically.

#include <cstdint>
#include <functional>
#include <string>

#include "protocol.hpp"

namespace station {

class IpcClient {
public:
    using LineHandler = std::function<void(const std::string&)>;
    using ConnectionHandler = std::function<void(bool)>;

    IpcClient(std::string host, std::uint16_t port, std::uint32_t reconnect_ms = 2000,
              std::uint32_t connect_timeout_ms = 3000);
    ~IpcClient();
    IpcClient(const IpcClient&) = delete;
    IpcClient& operator=(const IpcClient&) = delete;

    void on_line(LineHandler handler) { on_line_ = std::move(handler); }
    void on_connection(ConnectionHandler handler) { on_connection_ = std::move(handler); }

    // Connects, reads and writes without blocking; call every few milliseconds.
    void poll(std::uint64_t now_ms);
    // Queues a line ("\n" appended if missing); false when not connected.
    bool send_line(std::string line);
    bool connected() const { return state_ == State::Connected; }
    void disconnect();

private:
    enum class State { Idle, Connecting, Connected };

    void start_connect(std::uint64_t now_ms);
    void finish_connect(std::uint64_t now_ms);
    void read_available();
    void flush();
    void close_socket(std::uint64_t now_ms, bool notify);

    std::string host_;
    std::uint16_t port_;
    std::uint32_t reconnect_ms_;
    std::uint32_t connect_timeout_ms_;
    std::intptr_t socket_;
    State state_ = State::Idle;
    std::uint64_t next_attempt_ms_ = 0;
    std::uint64_t connect_started_ms_ = 0;
    std::uint64_t now_ms_ = 0;
    LineBuffer input_;
    std::string output_;
    LineHandler on_line_;
    ConnectionHandler on_connection_;
};

}  // namespace station

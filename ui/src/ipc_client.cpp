#include "ipc_client.hpp"

#include <cstdio>
#include <cstring>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace station {
namespace {

#ifdef _WIN32
using socket_t = SOCKET;
const std::intptr_t kInvalid = static_cast<std::intptr_t>(INVALID_SOCKET);

struct WinsockInit {
    WinsockInit()
    {
        WSADATA data;
        WSAStartup(MAKEWORD(2, 2), &data);
    }
    ~WinsockInit() { WSACleanup(); }
};

void ensure_network()
{
    static WinsockInit init;
}

int last_error() { return WSAGetLastError(); }
bool would_block(int error) { return error == WSAEWOULDBLOCK; }
bool in_progress(int error) { return error == WSAEWOULDBLOCK || error == WSAEINPROGRESS; }
void close_handle(std::intptr_t s) { closesocket(static_cast<socket_t>(s)); }

bool set_nonblocking(std::intptr_t s)
{
    u_long mode = 1;
    return ioctlsocket(static_cast<socket_t>(s), FIONBIO, &mode) == 0;
}

int send_bytes(std::intptr_t s, const char* data, std::size_t size)
{
    return send(static_cast<socket_t>(s), data, static_cast<int>(size), 0);
}

int recv_bytes(std::intptr_t s, char* data, std::size_t size)
{
    return recv(static_cast<socket_t>(s), data, static_cast<int>(size), 0);
}

// 1 = connected, 0 = still connecting, -1 = failed.
int connect_status(std::intptr_t s)
{
    fd_set write_set, error_set;
    FD_ZERO(&write_set);
    FD_ZERO(&error_set);
    FD_SET(static_cast<socket_t>(s), &write_set);
    FD_SET(static_cast<socket_t>(s), &error_set);
    timeval timeout{0, 0};
    const int ready = select(0, nullptr, &write_set, &error_set, &timeout);
    if (ready < 0 || FD_ISSET(static_cast<socket_t>(s), &error_set)) return -1;
    if (ready == 0) return 0;
    int error = 0;
    int length = sizeof(error);
    getsockopt(static_cast<socket_t>(s), SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &length);
    return error == 0 ? 1 : -1;
}
#else
using socket_t = int;
const std::intptr_t kInvalid = -1;

void ensure_network() {}
int last_error() { return errno; }
bool would_block(int error) { return error == EAGAIN || error == EWOULDBLOCK || error == EINTR; }
bool in_progress(int error) { return error == EINPROGRESS || error == EINTR; }
void close_handle(std::intptr_t s) { ::close(static_cast<socket_t>(s)); }

bool set_nonblocking(std::intptr_t s)
{
    const int flags = fcntl(static_cast<socket_t>(s), F_GETFL, 0);
    return flags >= 0 && fcntl(static_cast<socket_t>(s), F_SETFL, flags | O_NONBLOCK) == 0;
}

int send_bytes(std::intptr_t s, const char* data, std::size_t size)
{
    return static_cast<int>(::send(static_cast<socket_t>(s), data, size, MSG_NOSIGNAL));
}

int recv_bytes(std::intptr_t s, char* data, std::size_t size)
{
    return static_cast<int>(::recv(static_cast<socket_t>(s), data, size, 0));
}

int connect_status(std::intptr_t s)
{
    pollfd fd{static_cast<socket_t>(s), POLLOUT, 0};
    const int ready = ::poll(&fd, 1, 0);
    if (ready < 0) return -1;
    if (ready == 0) return 0;
    int error = 0;
    socklen_t length = sizeof(error);
    getsockopt(static_cast<socket_t>(s), SOL_SOCKET, SO_ERROR, &error, &length);
    return error == 0 ? 1 : -1;
}
#endif

}  // namespace

IpcClient::IpcClient(std::string host, std::uint16_t port, std::uint32_t reconnect_ms,
                     std::uint32_t connect_timeout_ms)
    : host_(std::move(host)),
      port_(port),
      reconnect_ms_(reconnect_ms),
      connect_timeout_ms_(connect_timeout_ms),
      socket_(kInvalid)
{
    ensure_network();
}

IpcClient::~IpcClient()
{
    if (socket_ != kInvalid) {
        close_handle(socket_);
    }
}

void IpcClient::poll(std::uint64_t now_ms)
{
    now_ms_ = now_ms;
    if (state_ == State::Idle) {
        if (now_ms >= next_attempt_ms_) {
            start_connect(now_ms);
        }
        return;
    }
    if (state_ == State::Connecting) {
        finish_connect(now_ms);
        return;
    }
    read_available();
    if (state_ == State::Connected) {
        flush();
    }
}

void IpcClient::start_connect(std::uint64_t now_ms)
{
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;
    addrinfo* result = nullptr;
    const std::string port = std::to_string(port_);
    if (getaddrinfo(host_.c_str(), port.c_str(), &hints, &result) != 0 || result == nullptr) {
        next_attempt_ms_ = now_ms + reconnect_ms_;
        return;
    }
    const socket_t s = ::socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    socket_ = static_cast<std::intptr_t>(s);
    if (socket_ == kInvalid || !set_nonblocking(socket_)) {
        freeaddrinfo(result);
        close_socket(now_ms, false);
        return;
    }
    int nodelay = 1;
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&nodelay), sizeof(nodelay));
    const int rc = ::connect(s, result->ai_addr, static_cast<int>(result->ai_addrlen));
    freeaddrinfo(result);
    if (rc != 0 && !in_progress(last_error())) {
        close_socket(now_ms, false);
        return;
    }
    state_ = State::Connecting;
    connect_started_ms_ = now_ms;
    finish_connect(now_ms);
}

void IpcClient::finish_connect(std::uint64_t now_ms)
{
    const int status = connect_status(socket_);
    if (status < 0 || (status == 0 && now_ms - connect_started_ms_ > connect_timeout_ms_)) {
        close_socket(now_ms, false);
        return;
    }
    if (status == 0) {
        return;
    }
    state_ = State::Connected;
    input_.clear();
    output_.clear();
    if (on_connection_) {
        on_connection_(true);
    }
}

void IpcClient::read_available()
{
    char buffer[16384];
    for (;;) {
        const int received = recv_bytes(socket_, buffer, sizeof(buffer));
        if (received > 0) {
            if (!input_.append(buffer, static_cast<std::size_t>(received))) {
                std::fprintf(stderr, "station-ui: dropping oversized IPC line\n");
            }
            while (auto line = input_.next_line()) {
                if (on_line_ && !line->empty()) {
                    on_line_(*line);
                }
                if (state_ != State::Connected) {
                    return;
                }
            }
            continue;
        }
        if (received == 0 || !would_block(last_error())) {
            close_socket(now_ms_, true);
        }
        return;
    }
}

void IpcClient::flush()
{
    while (!output_.empty()) {
        const int sent = send_bytes(socket_, output_.data(), output_.size());
        if (sent > 0) {
            output_.erase(0, static_cast<std::size_t>(sent));
            continue;
        }
        if (sent < 0 && would_block(last_error())) {
            return;
        }
        close_socket(now_ms_, true);
        return;
    }
}

bool IpcClient::send_line(std::string line)
{
    if (state_ != State::Connected) {
        return false;
    }
    if (line.empty() || line.back() != '\n') {
        line.push_back('\n');
    }
    output_ += line;
    flush();
    return state_ == State::Connected;
}

void IpcClient::disconnect()
{
    close_socket(now_ms_, true);
}

void IpcClient::close_socket(std::uint64_t now_ms, bool notify)
{
    const bool was_connected = state_ == State::Connected;
    if (socket_ != kInvalid) {
        close_handle(socket_);
        socket_ = kInvalid;
    }
    state_ = State::Idle;
    input_.clear();
    output_.clear();
    next_attempt_ms_ = now_ms + reconnect_ms_;
    if (notify && was_connected && on_connection_) {
        on_connection_(false);
    }
}

}  // namespace station

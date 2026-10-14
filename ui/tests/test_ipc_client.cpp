#include <doctest/doctest.h>

#include <chrono>
#include <string>
#include <thread>
#include <vector>

#include "ipc_client.hpp"

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
using test_socket = SOCKET;
static void close_test_socket(test_socket s) { closesocket(s); }
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
using test_socket = int;
static void close_test_socket(test_socket s) { ::close(s); }
#endif

using namespace station;

namespace {

std::uint64_t now_ms()
{
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count());
}

// Blocking loopback server used only by these tests.
struct TestServer {
    test_socket listener;
    std::uint16_t port = 0;

    TestServer()
    {
        IpcClient warmup("127.0.0.1", 1);  // ensures Winsock is initialised
        listener = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        address.sin_port = 0;
        REQUIRE(::bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0);
        REQUIRE(::listen(listener, 4) == 0);
        socklen_t length = sizeof(address);
        ::getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length);
        port = ntohs(address.sin_port);
    }
    ~TestServer() { close_test_socket(listener); }

    test_socket accept_one() { return ::accept(listener, nullptr, nullptr); }
};

void pump(IpcClient& client, int ms)
{
    const auto end = now_ms() + static_cast<std::uint64_t>(ms);
    while (now_ms() < end) {
        client.poll(now_ms());
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
}

}  // namespace

TEST_CASE("connects, exchanges lines and reconnects")
{
    TestServer server;
    IpcClient client("127.0.0.1", server.port, 100);
    std::vector<std::string> lines;
    std::vector<bool> states;
    client.on_line([&](const std::string& line) { lines.push_back(line); });
    client.on_connection([&](bool up) { states.push_back(up); });

    CHECK_FALSE(client.send_line("early"));
    client.poll(now_ms());
    test_socket peer = server.accept_one();
    pump(client, 50);
    REQUIRE(client.connected());
    CHECK(states == std::vector<bool>{true});

    const std::string hello = "{\"type\":\"hello\",\"protocol\":1}\n{\"type\":\"snap";
    ::send(peer, hello.data(), static_cast<int>(hello.size()), 0);
    pump(client, 50);
    CHECK(lines == std::vector<std::string>{"{\"type\":\"hello\",\"protocol\":1}"});
    const std::string rest = "shot\"}\n";
    ::send(peer, rest.data(), static_cast<int>(rest.size()), 0);
    pump(client, 50);
    REQUIRE(lines.size() == 2);
    CHECK(lines[1] == "{\"type\":\"snapshot\"}");

    CHECK(client.send_line("{\"type\":\"request\"}"));
    pump(client, 20);
    char buffer[64] = {};
    const int received = ::recv(peer, buffer, sizeof(buffer) - 1, 0);
    CHECK(std::string(buffer, received > 0 ? static_cast<std::size_t>(received) : 0) == "{\"type\":\"request\"}\n");

    close_test_socket(peer);
    pump(client, 50);
    CHECK_FALSE(client.connected());
    CHECK(states == std::vector<bool>{true, false});

    pump(client, 150);
    test_socket again = server.accept_one();
    pump(client, 50);
    CHECK(client.connected());
    CHECK(states == std::vector<bool>{true, false, true});
    close_test_socket(again);
}

TEST_CASE("keeps retrying while the service is down")
{
    IpcClient client("127.0.0.1", 1, 20);
    std::vector<bool> states;
    client.on_connection([&](bool up) { states.push_back(up); });
    pump(client, 100);
    CHECK_FALSE(client.connected());
    CHECK(states.empty());
}

#include <doctest/doctest.h>

#include <cstring>

#include "png_writer.hpp"

using namespace station;

namespace {

std::uint32_t read_u32(const std::vector<std::uint8_t>& bytes, std::size_t pos)
{
    return (std::uint32_t(bytes[pos]) << 24) | (std::uint32_t(bytes[pos + 1]) << 16) |
           (std::uint32_t(bytes[pos + 2]) << 8) | std::uint32_t(bytes[pos + 3]);
}

}  // namespace

TEST_CASE("checksums match reference values")
{
    const char* text = "123456789";
    CHECK(crc32(reinterpret_cast<const std::uint8_t*>(text), 9) == 0xCBF43926u);
    CHECK(adler32(reinterpret_cast<const std::uint8_t*>("Wikipedia"), 9) == 0x11E60398u);
    CHECK(crc32(nullptr, 0) == 0);
    CHECK(adler32(nullptr, 0) == 1);
}

TEST_CASE("png structure is valid")
{
    const std::uint8_t pixels[] = {255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9, 0, 0, 0, 255, 255, 255};
    const auto png = encode_png_rgb(3, 2, pixels, 9);
    const std::uint8_t signature[] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    REQUIRE(png.size() > 8);
    CHECK(std::memcmp(png.data(), signature, 8) == 0);
    std::size_t pos = 8;
    std::vector<std::string> chunks;
    while (pos + 12 <= png.size()) {
        const std::uint32_t length = read_u32(png, pos);
        const std::string type(reinterpret_cast<const char*>(&png[pos + 4]), 4);
        const std::uint32_t crc = read_u32(png, pos + 8 + length);
        CHECK(crc == crc32(&png[pos + 4], length + 4));
        if (type == "IHDR") {
            CHECK(read_u32(png, pos + 8) == 3);
            CHECK(read_u32(png, pos + 12) == 2);
            CHECK(png[pos + 16] == 8);
            CHECK(png[pos + 17] == 2);
        }
        if (type == "IDAT") {
            const std::size_t data = pos + 8;
            CHECK(png[data] == 0x78);
            CHECK(png[data + 2] == 1);
            const std::uint16_t len = static_cast<std::uint16_t>(png[data + 3] | (png[data + 4] << 8));
            const std::uint16_t nlen = static_cast<std::uint16_t>(png[data + 5] | (png[data + 6] << 8));
            CHECK(len == 2 * (1 + 9));
            CHECK(static_cast<std::uint16_t>(~len) == nlen);
            CHECK(png[data + 7] == 0);
            CHECK(png[data + 8] == 255);
        }
        chunks.push_back(type);
        pos += 12 + length;
    }
    CHECK(pos == png.size());
    CHECK(chunks == std::vector<std::string>{"IHDR", "IDAT", "IEND"});
}

TEST_CASE("large images are split into stored blocks")
{
    std::vector<std::uint8_t> pixels(800 * 480 * 3, 128);
    const auto png = encode_png_rgb(800, 480, pixels.data(), 800 * 3);
    const std::size_t raw = (800 * 3 + 1) * 480;
    const std::size_t blocks = (raw + 65534) / 65535;
    CHECK(png.size() == 8 + 25 + (12 + 2 + blocks * 5 + raw + 4) + 12);
}

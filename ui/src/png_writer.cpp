#include "png_writer.hpp"

#include <algorithm>
#include <array>
#include <fstream>

namespace station {
namespace {

std::array<std::uint32_t, 256> make_crc_table()
{
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t n = 0; n < 256; ++n) {
        std::uint32_t c = n;
        for (int k = 0; k < 8; ++k) {
            c = (c & 1u) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        }
        table[n] = c;
    }
    return table;
}

void put_u32(std::vector<std::uint8_t>& out, std::uint32_t value)
{
    out.push_back(static_cast<std::uint8_t>(value >> 24));
    out.push_back(static_cast<std::uint8_t>(value >> 16));
    out.push_back(static_cast<std::uint8_t>(value >> 8));
    out.push_back(static_cast<std::uint8_t>(value));
}

void put_chunk(std::vector<std::uint8_t>& out, const char type[4], const std::vector<std::uint8_t>& data)
{
    put_u32(out, static_cast<std::uint32_t>(data.size()));
    const std::size_t start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    put_u32(out, crc32(out.data() + start, out.size() - start));
}

}  // namespace

std::uint32_t crc32(const std::uint8_t* data, std::size_t size, std::uint32_t crc)
{
    static const auto table = make_crc_table();
    crc ^= 0xFFFFFFFFu;
    for (std::size_t i = 0; i < size; ++i) {
        crc = table[(crc ^ data[i]) & 0xFFu] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFFu;
}

std::uint32_t adler32(const std::uint8_t* data, std::size_t size)
{
    std::uint32_t a = 1, b = 0;
    for (std::size_t i = 0; i < size; ++i) {
        a = (a + data[i]) % 65521u;
        b = (b + a) % 65521u;
    }
    return (b << 16) | a;
}

std::vector<std::uint8_t> encode_png_rgb(std::uint32_t width, std::uint32_t height, const std::uint8_t* rgb,
                                         std::size_t stride)
{
    std::vector<std::uint8_t> raw;
    const std::size_t row_bytes = static_cast<std::size_t>(width) * 3;
    raw.reserve((row_bytes + 1) * height);
    for (std::uint32_t y = 0; y < height; ++y) {
        raw.push_back(0);
        const std::uint8_t* row = rgb + static_cast<std::size_t>(y) * stride;
        raw.insert(raw.end(), row, row + row_bytes);
    }

    std::vector<std::uint8_t> zlib = {0x78, 0x01};
    std::size_t offset = 0;
    do {
        const std::size_t block = std::min<std::size_t>(65535, raw.size() - offset);
        const bool last = offset + block == raw.size();
        zlib.push_back(last ? 1 : 0);
        zlib.push_back(static_cast<std::uint8_t>(block));
        zlib.push_back(static_cast<std::uint8_t>(block >> 8));
        zlib.push_back(static_cast<std::uint8_t>(~block));
        zlib.push_back(static_cast<std::uint8_t>(~block >> 8));
        zlib.insert(zlib.end(), raw.begin() + static_cast<std::ptrdiff_t>(offset),
                    raw.begin() + static_cast<std::ptrdiff_t>(offset + block));
        offset += block;
    } while (offset < raw.size());
    put_u32(zlib, adler32(raw.data(), raw.size()));

    std::vector<std::uint8_t> png = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    std::vector<std::uint8_t> header;
    put_u32(header, width);
    put_u32(header, height);
    header.insert(header.end(), {8, 2, 0, 0, 0});
    put_chunk(png, "IHDR", header);
    put_chunk(png, "IDAT", zlib);
    put_chunk(png, "IEND", {});
    return png;
}

bool write_file(const std::string& path, const std::vector<std::uint8_t>& bytes)
{
    std::ofstream file(path, std::ios::binary);
    if (!file) return false;
    file.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return static_cast<bool>(file);
}

}  // namespace station

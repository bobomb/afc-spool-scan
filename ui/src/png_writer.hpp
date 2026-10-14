#pragma once
// Minimal PNG encoder (8-bit RGB, stored deflate blocks) for snapshot mode.

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace station {

std::uint32_t crc32(const std::uint8_t* data, std::size_t size, std::uint32_t crc = 0);
std::uint32_t adler32(const std::uint8_t* data, std::size_t size);

// rgb rows are `stride` bytes apart, 3 bytes per pixel.
std::vector<std::uint8_t> encode_png_rgb(std::uint32_t width, std::uint32_t height, const std::uint8_t* rgb,
                                         std::size_t stride);
bool write_file(const std::string& path, const std::vector<std::uint8_t>& bytes);

}  // namespace station

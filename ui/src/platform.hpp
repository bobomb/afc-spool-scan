#pragma once
// Display/input backends: windows, sdl, drm (one per build) plus headless snapshot mode.

#include <cstdint>
#include <memory>
#include <string>

#include "lvgl.h"

namespace station {

struct PlatformOptions {
    int width = 800;
    int height = 480;
    int zoom = 100;
    std::string drm_card = "/dev/dri/card1";
    std::string touch_device;
};

class Platform {
public:
    virtual ~Platform() = default;
    virtual bool init(const PlatformOptions& options) = 0;
    virtual lv_display_t* display() const = 0;
    virtual const char* name() const = 0;
    virtual void sleep_ms(std::uint32_t ms);
    // Software backlight control (/sys/class/backlight on spoolpi); otherwise unsupported.
    virtual bool has_backlight() const { return false; }
    virtual void set_backlight(int /*percent*/) {}
    // Keypad device for PC keyboards (simulator); nullptr when there is none.
    virtual lv_indev_t* keypad() const { return nullptr; }
};

// Monotonic milliseconds, also used as the LVGL tick.
std::uint32_t tick_ms();
std::uint64_t steady_ms();

// The native backend selected at build time (nullptr for headless builds).
std::unique_ptr<Platform> create_native_platform();

class HeadlessPlatform : public Platform {
public:
    bool init(const PlatformOptions& options) override;
    lv_display_t* display() const override { return display_; }
    const char* name() const override { return "headless"; }

    void press(int x, int y);
    void release();
    // Renders the current frame and writes it as PNG.
    bool save_png(const std::string& path);

private:
    static void flush(lv_display_t* display, const lv_area_t* area, std::uint8_t* pixels);
    static void read_pointer(lv_indev_t* indev, lv_indev_data_t* data);

    lv_display_t* display_ = nullptr;
    lv_indev_t* pointer_ = nullptr;
    std::unique_ptr<std::uint8_t[]> buffer_;
    std::unique_ptr<std::uint8_t[]> frame_;
    std::uint32_t stride_ = 0;
    int width_ = 0;
    int height_ = 0;
    int x_ = 0;
    int y_ = 0;
    bool pressed_ = false;
};

}  // namespace station

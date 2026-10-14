// LVGL Windows driver backend (simulator on the development PC).
#include <windows.h>

#include "platform.hpp"

namespace station {
namespace {

class WindowsPlatform : public Platform {
public:
    bool init(const PlatformOptions& options) override
    {
        display_ = lv_windows_create_display(L"Spool Station", options.width, options.height, options.zoom, false, true);
        if (display_ == nullptr) {
            return false;
        }
        pointer_ = lv_windows_acquire_pointer_indev(display_);
        keypad_ = lv_windows_acquire_keypad_indev(display_);
        return pointer_ != nullptr;
    }
    lv_display_t* display() const override { return display_; }
    const char* name() const override { return "windows"; }
    lv_indev_t* keypad() const override { return keypad_; }
    void sleep_ms(std::uint32_t ms) override { Sleep(ms); }

private:
    lv_display_t* display_ = nullptr;
    lv_indev_t* pointer_ = nullptr;
    lv_indev_t* keypad_ = nullptr;
};

}  // namespace

std::unique_ptr<Platform> create_native_platform()
{
    return std::make_unique<WindowsPlatform>();
}

}  // namespace station

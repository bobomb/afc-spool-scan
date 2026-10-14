// SDL2 backend for Linux/WSL desktops.
#include "platform.hpp"

namespace station {
namespace {

class SdlPlatform : public Platform {
public:
    bool init(const PlatformOptions& options) override
    {
        display_ = lv_sdl_window_create(options.width, options.height);
        if (display_ == nullptr) {
            return false;
        }
        lv_sdl_window_set_title(display_, "Spool Station");
        if (options.zoom != 100) {
            lv_sdl_window_set_zoom(display_, static_cast<float>(options.zoom) / 100.0f);
        }
        pointer_ = lv_sdl_mouse_create();
        keyboard_ = lv_sdl_keyboard_create();
        return pointer_ != nullptr;
    }
    lv_display_t* display() const override { return display_; }
    const char* name() const override { return "sdl"; }
    lv_indev_t* keypad() const override { return keyboard_; }

private:
    lv_display_t* display_ = nullptr;
    lv_indev_t* pointer_ = nullptr;
    lv_indev_t* keyboard_ = nullptr;
};

}  // namespace

std::unique_ptr<Platform> create_native_platform()
{
    return std::make_unique<SdlPlatform>();
}

}  // namespace station

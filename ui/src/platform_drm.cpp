// spoolpi backend: DRM/KMS display, evdev touch, /sys/class/backlight brightness.
#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>

#include "platform.hpp"

namespace station {
namespace {

namespace fs = std::filesystem;

std::string find_backlight()
{
    std::error_code error;
    const fs::path root("/sys/class/backlight");
    if (!fs::is_directory(root, error)) {
        return std::string();
    }
    for (const auto& entry : fs::directory_iterator(root, error)) {
        if (fs::exists(entry.path() / "brightness") && fs::exists(entry.path() / "max_brightness")) {
            return entry.path().string();
        }
    }
    return std::string();
}

int read_int(const fs::path& path, int fallback)
{
    std::ifstream file(path);
    int value = fallback;
    if (file >> value) {
        return value;
    }
    return fallback;
}

class DrmPlatform : public Platform {
public:
    bool init(const PlatformOptions& options) override
    {
        display_ = lv_linux_drm_create();
        if (display_ == nullptr) {
            return false;
        }
        if (lv_linux_drm_set_file(display_, options.drm_card.c_str(), -1) != LV_RESULT_OK) {
            std::fprintf(stderr, "station-ui: cannot open DRM device %s\n", options.drm_card.c_str());
            return false;
        }
        if (!options.touch_device.empty()) {
            attach_pointer(lv_evdev_create(LV_INDEV_TYPE_POINTER, options.touch_device.c_str()));
            if (pointer_ == nullptr) {
                std::fprintf(stderr, "station-ui: cannot open touch device %s\n", options.touch_device.c_str());
            }
        } else if (lv_evdev_discovery_start(on_discovered, this) != LV_RESULT_OK) {
            std::fprintf(stderr, "station-ui: evdev discovery unavailable; pass --touch /dev/input/eventN\n");
        }
        backlight_ = find_backlight();
        if (!backlight_.empty()) {
            max_brightness_ = std::max(1, read_int(fs::path(backlight_) / "max_brightness", 255));
        }
        return true;
    }
    lv_display_t* display() const override { return display_; }
    const char* name() const override { return "drm"; }
    bool has_backlight() const override { return !backlight_.empty(); }

    void set_backlight(int percent) override
    {
        if (backlight_.empty()) {
            return;
        }
        const int value = std::clamp(percent, 0, 100) * max_brightness_ / 100;
        std::ofstream file(fs::path(backlight_) / "brightness");
        file << value;
    }

private:
    static void on_discovered(lv_indev_t* indev, lv_evdev_type_t type, void* user_data)
    {
        auto* self = static_cast<DrmPlatform*>(user_data);
        if (type == LV_EVDEV_TYPE_ABS && self->pointer_ == nullptr) {
            self->attach_pointer(indev);
            return;
        }
        // Discovery opens every /dev/input node (QR scanner, HDMI-CEC remotes); keep only the touchscreen.
        lv_evdev_delete(indev);
    }

    void attach_pointer(lv_indev_t* indev)
    {
        pointer_ = indev;
        if (pointer_ != nullptr) {
            lv_indev_set_display(pointer_, display_);
        }
    }

    lv_display_t* display_ = nullptr;
    lv_indev_t* pointer_ = nullptr;
    std::string backlight_;
    int max_brightness_ = 255;
};

}  // namespace

std::unique_ptr<Platform> create_native_platform()
{
    return std::make_unique<DrmPlatform>();
}

}  // namespace station

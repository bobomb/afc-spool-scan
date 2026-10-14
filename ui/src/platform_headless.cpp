#include <chrono>
#include <cstring>
#include <thread>

#include "platform.hpp"
#include "png_writer.hpp"

namespace station {

std::uint64_t steady_ms()
{
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count());
}

std::uint32_t tick_ms()
{
    return static_cast<std::uint32_t>(steady_ms());
}

void Platform::sleep_ms(std::uint32_t ms)
{
    std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

bool HeadlessPlatform::init(const PlatformOptions& options)
{
    width_ = options.width;
    height_ = options.height;
    display_ = lv_display_create(width_, height_);
    if (display_ == nullptr) {
        return false;
    }
    lv_display_set_color_format(display_, LV_COLOR_FORMAT_XRGB8888);
    stride_ = lv_draw_buf_width_to_stride(static_cast<std::uint32_t>(width_), LV_COLOR_FORMAT_XRGB8888);
    const std::size_t size = static_cast<std::size_t>(stride_) * static_cast<std::size_t>(height_);
    buffer_ = std::make_unique<std::uint8_t[]>(size);
    frame_ = std::make_unique<std::uint8_t[]>(size);
    lv_display_set_buffers(display_, buffer_.get(), nullptr, static_cast<std::uint32_t>(size),
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display_, flush);
    lv_display_set_user_data(display_, this);

    pointer_ = lv_indev_create();
    lv_indev_set_type(pointer_, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(pointer_, read_pointer);
    lv_indev_set_user_data(pointer_, this);
    lv_indev_set_display(pointer_, display_);
    return true;
}

void HeadlessPlatform::flush(lv_display_t* display, const lv_area_t* area, std::uint8_t* pixels)
{
    auto* self = static_cast<HeadlessPlatform*>(lv_display_get_user_data(display));
    LV_UNUSED(area);
    std::memcpy(self->frame_.get(), pixels, static_cast<std::size_t>(self->stride_) * self->height_);
    lv_display_flush_ready(display);
}

void HeadlessPlatform::read_pointer(lv_indev_t* indev, lv_indev_data_t* data)
{
    auto* self = static_cast<HeadlessPlatform*>(lv_indev_get_user_data(indev));
    data->point.x = self->x_;
    data->point.y = self->y_;
    data->state = self->pressed_ ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

void HeadlessPlatform::press(int x, int y)
{
    x_ = x;
    y_ = y;
    pressed_ = true;
}

void HeadlessPlatform::release()
{
    pressed_ = false;
}

bool HeadlessPlatform::save_png(const std::string& path)
{
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display_);
    std::vector<std::uint8_t> rgb(static_cast<std::size_t>(width_) * height_ * 3);
    for (int y = 0; y < height_; ++y) {
        const std::uint8_t* row = frame_.get() + static_cast<std::size_t>(y) * stride_;
        std::uint8_t* out = rgb.data() + static_cast<std::size_t>(y) * width_ * 3;
        for (int x = 0; x < width_; ++x) {
            out[x * 3 + 0] = row[x * 4 + 2];
            out[x * 3 + 1] = row[x * 4 + 1];
            out[x * 3 + 2] = row[x * 4 + 0];
        }
    }
    return write_file(path, encode_png_rgb(static_cast<std::uint32_t>(width_), static_cast<std::uint32_t>(height_),
                                           rgb.data(), static_cast<std::size_t>(width_) * 3));
}

#if defined(STATION_UI_BACKEND_HEADLESS)
std::unique_ptr<Platform> create_native_platform()
{
    return nullptr;
}
#endif

}  // namespace station

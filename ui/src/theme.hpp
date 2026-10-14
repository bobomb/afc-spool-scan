#pragma once
// Palettes, fonts and shared styles (dark default, light variant).

#include <cstdint>

#include "lvgl.h"

namespace station {

struct Palette {
    bool dark = true;
    std::uint32_t bg;
    std::uint32_t surface;
    std::uint32_t surface_alt;
    std::uint32_t border;
    std::uint32_t text;
    std::uint32_t muted;
    std::uint32_t primary;
    std::uint32_t on_primary;
    std::uint32_t ok;
    std::uint32_t warn;
    std::uint32_t error;
    std::uint32_t info;
    std::uint32_t disabled;
};

class Theme {
public:
    Theme();
    // Applies the palette to the display's default theme; call before building widgets.
    void apply(lv_display_t* display, bool dark);

    const Palette& palette() const { return palette_; }
    lv_color_t color(std::uint32_t rgb) const { return lv_color_hex(rgb); }
    lv_color_t bg() const { return color(palette_.bg); }
    lv_color_t surface() const { return color(palette_.surface); }
    lv_color_t surface_alt() const { return color(palette_.surface_alt); }
    lv_color_t border() const { return color(palette_.border); }
    lv_color_t text() const { return color(palette_.text); }
    lv_color_t muted() const { return color(palette_.muted); }
    lv_color_t primary() const { return color(palette_.primary); }
    lv_color_t on_primary() const { return color(palette_.on_primary); }
    lv_color_t ok() const { return color(palette_.ok); }
    lv_color_t warn() const { return color(palette_.warn); }
    lv_color_t error() const { return color(palette_.error); }
    lv_color_t info() const { return color(palette_.info); }
    lv_color_t disabled() const { return color(palette_.disabled); }

    const lv_font_t* small() const { return &lv_font_montserrat_16; }
    const lv_font_t* normal() const { return &lv_font_montserrat_22; }
    const lv_font_t* large() const { return &lv_font_montserrat_28; }
    const lv_font_t* huge() const { return &lv_font_montserrat_48; }

    lv_style_t* card() { return &card_; }
    lv_style_t* button() { return &button_; }
    lv_style_t* button_pressed() { return &button_pressed_; }
    lv_style_t* button_checked() { return &button_checked_; }
    lv_style_t* button_disabled() { return &button_disabled_; }
    lv_style_t* button_primary() { return &button_primary_; }
    lv_style_t* button_danger() { return &button_danger_; }

private:
    Palette palette_;
    lv_style_t card_;
    lv_style_t button_;
    lv_style_t button_pressed_;
    lv_style_t button_checked_;
    lv_style_t button_disabled_;
    lv_style_t button_primary_;
    lv_style_t button_danger_;
};

Palette dark_palette();
Palette light_palette();

}  // namespace station

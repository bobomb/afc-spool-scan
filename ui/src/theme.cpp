#include "theme.hpp"

namespace station {

Palette dark_palette()
{
    Palette p;
    p.dark = true;
    p.bg = 0x0F1216;
    p.surface = 0x1A1F26;
    p.surface_alt = 0x242A33;
    p.border = 0x313945;
    p.text = 0xE9EDF2;
    p.muted = 0x8E98A6;
    p.primary = 0x2F7DF6;
    p.on_primary = 0xFFFFFF;
    p.ok = 0x2EB872;
    p.warn = 0xF2A93B;
    p.error = 0xE5484D;
    p.info = 0x4AA3F0;
    p.disabled = 0x3A414B;
    return p;
}

Palette light_palette()
{
    Palette p;
    p.dark = false;
    p.bg = 0xE9EDF2;
    p.surface = 0xFFFFFF;
    p.surface_alt = 0xF2F4F7;
    p.border = 0xCDD4DD;
    p.text = 0x18202A;
    p.muted = 0x5F6B7A;
    p.primary = 0x1F6FEB;
    p.on_primary = 0xFFFFFF;
    p.ok = 0x17914F;
    p.warn = 0xB86E00;
    p.error = 0xCC2E34;
    p.info = 0x2479C7;
    p.disabled = 0xC5CCD6;
    return p;
}

Theme::Theme() : palette_(dark_palette())
{
    lv_style_init(&card_);
    lv_style_init(&button_);
    lv_style_init(&button_pressed_);
    lv_style_init(&button_checked_);
    lv_style_init(&button_disabled_);
    lv_style_init(&button_primary_);
    lv_style_init(&button_danger_);
}

void Theme::apply(lv_display_t* display, bool dark)
{
    palette_ = dark ? dark_palette() : light_palette();
    lv_theme_t* base = lv_theme_default_init(display, primary(), info(), dark, small());
    lv_display_set_theme(display, base);

    lv_style_reset(&card_);
    lv_style_set_bg_color(&card_, surface());
    lv_style_set_bg_opa(&card_, LV_OPA_COVER);
    lv_style_set_border_color(&card_, border());
    lv_style_set_border_width(&card_, 1);
    lv_style_set_radius(&card_, 12);
    lv_style_set_pad_all(&card_, 10);
    lv_style_set_shadow_width(&card_, 0);
    lv_style_set_text_color(&card_, text());

    lv_style_reset(&button_);
    lv_style_set_bg_color(&button_, surface_alt());
    lv_style_set_bg_opa(&button_, LV_OPA_COVER);
    lv_style_set_border_color(&button_, border());
    lv_style_set_border_width(&button_, 1);
    lv_style_set_radius(&button_, 10);
    lv_style_set_shadow_width(&button_, 0);
    lv_style_set_text_color(&button_, text());
    lv_style_set_text_font(&button_, small());
    lv_style_set_pad_all(&button_, 6);

    lv_style_reset(&button_pressed_);
    lv_style_set_bg_color(&button_pressed_, lv_color_mix(primary(), surface_alt(), LV_OPA_40));
    lv_style_set_translate_y(&button_pressed_, 1);

    lv_style_reset(&button_checked_);
    lv_style_set_bg_color(&button_checked_, lv_color_mix(primary(), surface(), LV_OPA_30));
    lv_style_set_border_color(&button_checked_, primary());
    lv_style_set_border_width(&button_checked_, 2);
    lv_style_set_outline_width(&button_checked_, 0);
    lv_style_set_text_color(&button_checked_, text());

    lv_style_reset(&button_disabled_);
    lv_style_set_bg_color(&button_disabled_, surface());
    lv_style_set_text_color(&button_disabled_, disabled());
    lv_style_set_border_color(&button_disabled_, border());

    lv_style_reset(&button_primary_);
    lv_style_set_bg_color(&button_primary_, primary());
    lv_style_set_border_color(&button_primary_, primary());
    lv_style_set_text_color(&button_primary_, on_primary());

    lv_style_reset(&button_danger_);
    lv_style_set_bg_color(&button_danger_, error());
    lv_style_set_border_color(&button_danger_, error());
    lv_style_set_text_color(&button_danger_, on_primary());
}

}  // namespace station

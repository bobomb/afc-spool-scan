#include "ui.hpp"

#include "format.hpp"

namespace station::ui {
namespace {

void click_trampoline(lv_event_t* e)
{
    auto* callback = static_cast<std::function<void()>*>(lv_event_get_user_data(e));
    if (callback && *callback) {
        (*callback)();
    }
}

void delete_callback(lv_event_t* e)
{
    delete static_cast<std::function<void()>*>(lv_event_get_user_data(e));
}

}  // namespace

lv_obj_t* container(lv_obj_t* parent)
{
    lv_obj_t* obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_scrollable(obj, false);
    lv_obj_set_clickable(obj, false);
    return obj;
}

lv_obj_t* panel(lv_obj_t* parent, Theme& theme)
{
    lv_obj_t* obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_add_style(obj, theme.card(), 0);
    lv_obj_set_scrollable(obj, false);
    lv_obj_set_clickable(obj, false);
    return obj;
}

lv_obj_t* label(lv_obj_t* parent, const lv_font_t* font, lv_color_t color, const std::string& text)
{
    lv_obj_t* obj = lv_label_create(parent);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_color(obj, color, 0);
    lv_label_set_text(obj, text.c_str());
    return obj;
}

lv_obj_t* button(lv_obj_t* parent, Theme& theme, const std::string& text, ButtonStyle style, const lv_font_t* font)
{
    lv_obj_t* obj = lv_button_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_add_style(obj, theme.button(), 0);
    if (style == ButtonStyle::Primary) {
        lv_obj_add_style(obj, theme.button_primary(), 0);
    } else if (style == ButtonStyle::Danger) {
        lv_obj_add_style(obj, theme.button_danger(), 0);
    }
    lv_obj_add_style(obj, theme.button_pressed(), LV_STATE_PRESSED);
    lv_obj_add_style(obj, theme.button_checked(), LV_STATE_CHECKED);
    lv_obj_add_style(obj, theme.button_disabled(), LV_STATE_DISABLED);
    lv_obj_set_scroll_on_focus(obj, false);
    if (!text.empty()) {
        lv_obj_t* text_label = lv_label_create(obj);
        lv_label_set_text(text_label, text.c_str());
        lv_obj_set_style_text_font(text_label, font ? font : theme.small(), 0);
        lv_obj_set_style_text_align(text_label, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_center(text_label);
    }
    return obj;
}

lv_obj_t* button_label(lv_obj_t* button)
{
    return lv_obj_get_child_count(button) > 0 ? lv_obj_get_child(button, 0) : nullptr;
}

lv_obj_t* dot(lv_obj_t* parent, int size, lv_color_t color)
{
    lv_obj_t* obj = container(parent);
    lv_obj_set_size(obj, size, size);
    lv_obj_set_style_radius(obj, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(obj, color, 0);
    return obj;
}

lv_obj_t* chip(lv_obj_t* parent, Theme& theme, const std::string& text, lv_color_t color)
{
    lv_obj_t* obj = container(parent);
    lv_obj_set_size(obj, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_radius(obj, 8, 0);
    lv_obj_set_style_pad_hor(obj, 8, 0);
    lv_obj_set_style_pad_ver(obj, 2, 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_20, 0);
    lv_obj_set_style_border_width(obj, 1, 0);
    lv_obj_t* text_label = label(obj, theme.small(), color, text);
    LV_UNUSED(text_label);
    set_chip(obj, text, color);
    return obj;
}

void set_chip(lv_obj_t* chip, const std::string& text, lv_color_t color)
{
    lv_obj_set_style_bg_color(chip, color, 0);
    lv_obj_set_style_border_color(chip, color, 0);
    lv_obj_t* text_label = lv_obj_get_child(chip, 0);
    lv_obj_set_style_text_color(text_label, color, 0);
    set_text(text_label, text);
}

void on_click(lv_obj_t* obj, std::function<void()> callback)
{
    auto* stored = new std::function<void()>(std::move(callback));
    lv_obj_set_clickable(obj, true);
    lv_obj_add_event_cb(obj, click_trampoline, LV_EVENT_CLICKED, stored);
    lv_obj_add_event_cb(obj, delete_callback, LV_EVENT_DELETE, stored);
}

void set_text(lv_obj_t* label, const std::string& text)
{
    const char* current = lv_label_get_text(label);
    if (current == nullptr || text != current) {
        lv_label_set_text(label, text.c_str());
    }
}

void set_hidden(lv_obj_t* obj, bool hidden)
{
    lv_obj_set_hidden(obj, hidden);
}

void set_disabled(lv_obj_t* obj, bool disabled)
{
    if (disabled) {
        lv_obj_add_state(obj, LV_STATE_DISABLED);
    } else {
        lv_obj_remove_state(obj, LV_STATE_DISABLED);
    }
}

void set_checked(lv_obj_t* obj, bool checked)
{
    if (checked) {
        lv_obj_add_state(obj, LV_STATE_CHECKED);
    } else {
        lv_obj_remove_state(obj, LV_STATE_CHECKED);
    }
}

lv_obj_t* modal(lv_obj_t* layer, Theme& theme, int width, int height, lv_obj_t** dimmer)
{
    lv_obj_t* shade = container(layer);
    lv_obj_set_size(shade, layout::kWidth, layout::kHeight);
    lv_obj_set_style_bg_color(shade, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(shade, LV_OPA_60, 0);
    lv_obj_set_clickable(shade, true);
    lv_obj_t* dialog = panel(shade, theme);
    lv_obj_set_size(dialog, width, height);
    lv_obj_center(dialog);
    lv_obj_set_style_radius(dialog, 16, 0);
    lv_obj_set_style_pad_all(dialog, 16, 0);
    lv_obj_set_style_border_color(dialog, theme.border(), 0);
    lv_obj_set_clickable(dialog, true);
    *dimmer = shade;
    return dialog;
}

lv_color_t swatch_color(const std::string& hex, Theme& theme)
{
    const std::uint32_t fallback = theme.palette().surface_alt;
    return lv_color_hex(parse_hex_color(hex, fallback));
}

}  // namespace station::ui

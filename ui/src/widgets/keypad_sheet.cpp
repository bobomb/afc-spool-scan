#include "app.hpp"
#include "ui.hpp"

namespace station {
namespace {

constexpr int kDialogW = 400;
constexpr int kDialogH = 440;
constexpr int kKeyW = 112;
constexpr int kKeyH = 60;
constexpr int kKeysX = 24;
constexpr int kKeysY = 144;

}  // namespace

void KeypadSheet::show()
{
    if (dimmer_ != nullptr) {
        return;
    }
    Theme& theme = app_.theme();
    lv_obj_t* dialog = ui::modal(lv_layer_top(), theme, kDialogW, kDialogH, &dimmer_);
    lv_obj_set_style_pad_all(dialog, 0, 0);
    lv_obj_set_style_radius(dialog, 20, 0);
    lv_obj_set_style_border_width(dialog, 0, 0);
    ui::on_click(dimmer_, [this] { app_.close_keypad(); });

    lv_obj_t* title = ui::label(dialog, theme.small(), theme.muted(), "Type a spool ID, or scan a QR code");
    lv_obj_set_pos(title, kKeysX, 24);
    lv_obj_t* close = ui::button(dialog, theme, LV_SYMBOL_CLOSE, ui::ButtonStyle::Normal);
    lv_obj_set_size(close, 40, 36);
    lv_obj_set_pos(close, kDialogW - 40 - 20, 14);
    ui::on_click(close, [this] { app_.close_keypad(); });

    lv_obj_t* display = ui::container(dialog);
    lv_obj_set_pos(display, kKeysX, 60);
    lv_obj_set_size(display, kDialogW - 2 * kKeysX, 72);
    lv_obj_set_style_radius(display, 12, 0);
    lv_obj_set_style_bg_color(display, theme.bg(), 0);
    lv_obj_set_style_bg_opa(display, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_left(display, 18, 0);
    lv_obj_set_style_pad_right(display, 6, 0);
    lv_obj_set_flex_flow(display, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(display, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(display, 6, 0);
    digits_ = ui::label(display, theme.huge(), theme.text(), "");
    lv_obj_t* caret = ui::container(display);
    lv_obj_set_size(caret, 3, 44);
    lv_obj_set_style_radius(caret, 2, 0);
    lv_obj_set_style_bg_color(caret, theme.primary(), 0);
    lv_obj_set_style_bg_opa(caret, LV_OPA_COVER, 0);
    lv_obj_t* spacer = ui::container(display);
    lv_obj_set_height(spacer, 1);
    lv_obj_set_flex_grow(spacer, 1);
    lv_obj_t* backspace = ui::button(display, theme, LV_SYMBOL_BACKSPACE, ui::ButtonStyle::Ghost, theme.normal());
    lv_obj_set_size(backspace, 60, 56);
    lv_obj_set_style_border_width(backspace, 0, 0);
    lv_obj_set_style_text_color(ui::button_label(backspace), theme.muted(), 0);
    ui::on_click(backspace, [this] { app_.entry_backspace(); });

    const char* const digits = "789456123";
    for (int i = 0; i < 9; ++i) {
        const char digit = digits[i];
        lv_obj_t* key = ui::button(dialog, theme, std::string(1, digit), ui::ButtonStyle::Normal, theme.large());
        lv_obj_set_size(key, kKeyW, kKeyH);
        lv_obj_set_pos(key, kKeysX + (i % 3) * (kKeyW + 8), kKeysY + (i / 3) * (kKeyH + 8));
        ui::on_click(key, [this, digit] { app_.entry_digit(digit); });
    }
    const int bottom = kKeysY + 3 * (kKeyH + 8);
    lv_obj_t* clear = ui::button(dialog, theme, "Clear", ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(clear, kKeyW, kKeyH);
    lv_obj_set_pos(clear, kKeysX, bottom);
    lv_obj_set_style_text_color(ui::button_label(clear), theme.muted(), 0);
    ui::on_click(clear, [this] { app_.entry_clear(); });
    lv_obj_t* zero = ui::button(dialog, theme, "0", ui::ButtonStyle::Normal, theme.large());
    lv_obj_set_size(zero, kKeyW, kKeyH);
    lv_obj_set_pos(zero, kKeysX + kKeyW + 8, bottom);
    ui::on_click(zero, [this] { app_.entry_digit('0'); });
    lookup_ = ui::button(dialog, theme, LV_SYMBOL_NEW_LINE "  Look up", ui::ButtonStyle::Primary, theme.medium());
    lv_obj_set_size(lookup_, kKeyW, kKeyH);
    lv_obj_set_pos(lookup_, kKeysX + 2 * (kKeyW + 8), bottom);
    ui::on_click(lookup_, [this] { app_.entry_submit(); });
    update(app_.entry());
}

void KeypadSheet::update(const std::string& entry)
{
    if (dimmer_ == nullptr) {
        return;
    }
    ui::set_text(digits_, entry);
    ui::set_disabled(lookup_, entry.empty());
}

void KeypadSheet::close()
{
    if (dimmer_ != nullptr) {
        lv_obj_delete_async(dimmer_);
        dimmer_ = nullptr;
        digits_ = nullptr;
        lookup_ = nullptr;
    }
}

}  // namespace station

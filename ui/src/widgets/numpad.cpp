#include "app.hpp"
#include "ui.hpp"

namespace station {
namespace {

const char* const kMap[] = {"7", "8", "9", "\n", "4", "5", "6", "\n", "1", "2", "3", "\n",
                            "C", "0", LV_SYMBOL_NEW_LINE, ""};

}  // namespace

Numpad::Numpad(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app)
{
    Theme& theme = app.theme();
    matrix_ = lv_buttonmatrix_create(parent);
    lv_obj_remove_style_all(matrix_);
    lv_obj_set_pos(matrix_, x, y);
    lv_obj_set_size(matrix_, w, h);
    lv_buttonmatrix_set_map(matrix_, kMap);
    lv_obj_set_style_pad_row(matrix_, 6, 0);
    lv_obj_set_style_pad_column(matrix_, 6, 0);

    lv_obj_set_style_bg_color(matrix_, theme.surface_alt(), LV_PART_ITEMS);
    lv_obj_set_style_bg_opa(matrix_, LV_OPA_COVER, LV_PART_ITEMS);
    lv_obj_set_style_border_color(matrix_, theme.border(), LV_PART_ITEMS);
    lv_obj_set_style_border_width(matrix_, 1, LV_PART_ITEMS);
    lv_obj_set_style_radius(matrix_, 10, LV_PART_ITEMS);
    lv_obj_set_style_text_font(matrix_, theme.large(), LV_PART_ITEMS);
    lv_obj_set_style_text_color(matrix_, theme.text(), LV_PART_ITEMS);
    lv_obj_set_style_shadow_width(matrix_, 0, LV_PART_ITEMS);
    lv_obj_set_style_bg_color(matrix_, lv_color_mix(theme.primary(), theme.surface_alt(), LV_OPA_40),
                              static_cast<lv_style_selector_t>(LV_PART_ITEMS) | LV_STATE_PRESSED);
    lv_obj_set_style_bg_color(matrix_, theme.surface(), static_cast<lv_style_selector_t>(LV_PART_ITEMS) |
                                                            LV_STATE_DISABLED);
    lv_obj_set_style_text_color(matrix_, theme.disabled(), static_cast<lv_style_selector_t>(LV_PART_ITEMS) |
                                                                LV_STATE_DISABLED);
    lv_obj_add_event_cb(matrix_, on_event, LV_EVENT_VALUE_CHANGED, this);
}

void Numpad::on_event(lv_event_t* e)
{
    auto* self = static_cast<Numpad*>(lv_event_get_user_data(e));
    const std::uint32_t index = lv_buttonmatrix_get_selected_button(self->matrix_);
    if (index == LV_BUTTONMATRIX_BUTTON_NONE) {
        return;
    }
    const char* text = lv_buttonmatrix_get_button_text(self->matrix_, index);
    if (text == nullptr) {
        return;
    }
    const std::string key(text);
    if (key == "C") {
        self->app_.handle_key("clear");
    } else if (key == LV_SYMBOL_NEW_LINE) {
        self->app_.handle_key("enter");
    } else {
        self->app_.handle_key(key);
    }
}

}  // namespace station

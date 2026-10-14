#include "app.hpp"
#include "ui.hpp"

namespace station {

void StatusOverlay::set_offline(bool offline, const std::string& text)
{
    Theme& theme = app_.theme();
    if (!offline) {
        if (offline_ != nullptr) {
            lv_obj_delete_async(offline_);
            offline_ = nullptr;
            offline_text_ = nullptr;
        }
        return;
    }
    if (offline_ == nullptr) {
        offline_ = ui::container(lv_layer_sys());
        lv_obj_set_size(offline_, layout::kWidth, layout::kHeight - layout::kHeaderH);
        lv_obj_set_pos(offline_, 0, layout::kHeaderH);
        lv_obj_set_style_bg_color(offline_, theme.bg(), 0);
        lv_obj_set_style_bg_opa(offline_, LV_OPA_80, 0);
        lv_obj_set_clickable(offline_, true);
        lv_obj_t* box = ui::panel(offline_, theme);
        lv_obj_set_size(box, 480, 180);
        lv_obj_center(box);
        lv_obj_t* spinner = lv_spinner_create(box);
        lv_obj_set_size(spinner, 56, 56);
        lv_spinner_set_anim_params(spinner, 1200, 270);
        lv_obj_set_style_arc_color(spinner, theme.primary(), LV_PART_INDICATOR);
        lv_obj_set_style_arc_color(spinner, theme.surface_alt(), 0);
        lv_obj_align(spinner, LV_ALIGN_TOP_MID, 0, 6);
        offline_text_ = ui::label(box, theme.normal(), theme.text(), "");
        lv_obj_set_width(offline_text_, 440);
        lv_obj_set_style_text_align(offline_text_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(offline_text_, LV_ALIGN_BOTTOM_MID, 0, -14);
    }
    ui::set_text(offline_text_, text);
}

void StatusOverlay::set_blank(bool blank)
{
    if (!blank) {
        if (blank_ != nullptr) {
            lv_obj_delete_async(blank_);
            blank_ = nullptr;
        }
        return;
    }
    if (blank_ == nullptr) {
        blank_ = ui::container(lv_layer_sys());
        lv_obj_set_size(blank_, layout::kWidth, layout::kHeight);
        lv_obj_set_style_bg_color(blank_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(blank_, LV_OPA_COVER, 0);
        lv_obj_set_clickable(blank_, true);
        ui::on_click(blank_, [this] { app_.idle().wake(); });
    }
    lv_obj_move_foreground(blank_);
}

void StatusOverlay::reset()
{
    set_offline(false, std::string());
    set_blank(false);
}

}  // namespace station

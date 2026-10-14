#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {

ScaleTile::ScaleTile(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app)
{
    Theme& theme = app.theme();
    lv_obj_t* root = ui::panel(parent, theme);
    lv_obj_set_pos(root, x, y);
    lv_obj_set_size(root, w, h);
    lv_obj_set_style_pad_all(root, 10, 0);

    lv_obj_t* title = ui::label(root, theme.small(), theme.muted(), "SCALE");
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 2, 0);
    chip_ = ui::chip(root, theme, "Off", theme.muted());
    lv_obj_align(chip_, LV_ALIGN_TOP_RIGHT, 0, -2);

    weight_ = ui::label(root, theme.huge(), theme.text(), "--");
    lv_obj_align(weight_, LV_ALIGN_LEFT_MID, 0, 4);
    unit_ = ui::label(root, theme.normal(), theme.muted(), "g");
    lv_obj_align_to(unit_, weight_, LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -8);

    detail_ = ui::label(root, theme.small(), theme.muted(), "");
    lv_obj_align(detail_, LV_ALIGN_BOTTOM_LEFT, 2, 2);
}

void ScaleTile::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    const ScaleState& scale = state.scale;
    const std::string status_label = online ? scale_status_label(scale.status) : "Offline";
    lv_color_t chip_color = theme.muted();
    if (online) {
        if (scale.status == "stable") chip_color = theme.ok();
        else if (scale.status == "motion" || scale.status == "under" || scale.status == "over" ||
                 scale.status == "rezero") chip_color = theme.warn();
        else if (scale.status == "fault" || scale.status == "calibrate") chip_color = theme.error();
    }
    ui::set_chip(chip_, status_label, chip_color);

    const bool has_weight = online && scale.present && scale.grams.has_value();
    ui::set_text(weight_, has_weight ? fmt_number(*scale.grams, 1) : "--.-");
    lv_obj_set_style_text_color(weight_, has_weight && scale.status != "motion" ? theme.text() : theme.muted(), 0);
    ui::set_text(unit_, scale.source_unit == "oz" && has_weight ? "g  (oz scale)" : "g");
    lv_obj_align_to(unit_, weight_, LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -8);

    std::string detail;
    lv_color_t detail_color = theme.muted();
    if (has_weight && scale.net_g && *scale.grams > 0) {
        if (*scale.net_g < 0) {
            detail = "below tare by " + fmt_grams(-*scale.net_g);
            detail_color = theme.warn();
        } else {
            detail = "filament ~ " + fmt_grams(*scale.net_g);
            if (scale.tare_g) detail += "  (tare " + fmt_grams(*scale.tare_g) + ")";
        }
    } else if (has_weight && scale.check == "tare_unknown") {
        detail = "tare unknown";
        detail_color = theme.warn();
    } else if (online && !scale.present) {
        detail = "Turn the scale on";
    }
    ui::set_text(detail_, detail);
    lv_obj_set_style_text_color(detail_, detail_color, 0);
}

}  // namespace station

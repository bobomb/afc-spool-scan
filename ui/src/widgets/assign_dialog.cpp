#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {

void AssignDialog::show(int spool_id, const std::string& printer, const std::string& lane)
{
    close();
    spool_id_ = spool_id;
    printer_ = printer;
    lane_ = lane;
    const State& state = app_.state();
    if (printer_.empty() || app_.model().printer(printer_) == nullptr) {
        printer_ = state.printers.empty() ? std::string() : state.printers.front().key;
    }
    build();
}

void AssignDialog::build()
{
    Theme& theme = app_.theme();
    lv_obj_t* dialog = ui::modal(lv_layer_top(), theme, 640, 420, &dimmer_);
    const std::string title = spool_id_ > 0 ? "Assign spool #" + std::to_string(spool_id_) + " to a lane"
                                            : "Assign a spool to a lane";
    ui::label(dialog, theme.normal(), theme.text(), title);
    hint_ = ui::label(dialog, theme.small(), theme.muted(), "");
    lv_obj_set_pos(hint_, 0, 32);
    lv_obj_set_size(hint_, 600, 20);
    lv_label_set_long_mode(hint_, LV_LABEL_LONG_MODE_DOTS);

    printer_row_ = ui::container(dialog);
    lv_obj_set_pos(printer_row_, 0, 60);
    lv_obj_set_size(printer_row_, 608, 52);
    lv_obj_set_flex_flow(printer_row_, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(printer_row_, 8, 0);

    lane_grid_ = ui::container(dialog);
    lv_obj_set_pos(lane_grid_, 0, 122);
    lv_obj_set_size(lane_grid_, 608, 136);
    lv_obj_set_flex_flow(lane_grid_, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_style_pad_column(lane_grid_, 8, 0);
    lv_obj_set_style_pad_row(lane_grid_, 8, 0);

    lv_obj_t* cancel = ui::button(dialog, theme, "Cancel", ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(cancel, 200, 60);
    lv_obj_align(cancel, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    ui::on_click(cancel, [this] { close(); });
    assign_ = ui::button(dialog, theme, "Assign", ui::ButtonStyle::Primary, theme.normal());
    lv_obj_set_size(assign_, 300, 60);
    lv_obj_align(assign_, LV_ALIGN_BOTTOM_RIGHT, 0, 0);
    ui::on_click(assign_, [this] {
        if (spool_id_ > 0 && !printer_.empty() && !lane_.empty()) {
            const int spool = spool_id_;
            const std::string printer = printer_;
            const std::string lane = lane_;
            close();
            app_.assign(spool, printer, lane);
        }
    });
    refresh(app_.state());
}

void AssignDialog::select_printer(const std::string& key)
{
    if (key != printer_) {
        printer_ = key;
        lane_.clear();
        lv_async_call(refresh_async, this);
    }
}

void AssignDialog::refresh_async(void* self)
{
    auto* dialog = static_cast<AssignDialog*>(self);
    if (dialog->app_.alive()) {
        dialog->refresh(dialog->app_.state());
    }
}

void AssignDialog::refresh(const State& state)
{
    if (!open()) {
        return;
    }
    Theme& theme = app_.theme();
    lv_obj_clean(printer_row_);
    for (const Printer& printer : state.printers) {
        lv_obj_t* button = ui::button(printer_row_, theme, printer.name, ui::ButtonStyle::Segment, theme.normal());
        lv_obj_set_height(button, 52);
        lv_obj_set_flex_grow(button, 1);
        ui::set_checked(button, printer.key == printer_);
        ui::set_disabled(button, !printer.connected);
        const std::string key = printer.key;
        ui::on_click(button, [this, key] { select_printer(key); });
    }

    lv_obj_clean(lane_grid_);
    const Printer* printer = app_.model().printer(printer_);
    if (printer != nullptr) {
        for (const Lane& lane : printer->lanes) {
            lv_obj_t* button = ui::button(lane_grid_, theme, "", ui::ButtonStyle::Segment);
            lv_obj_set_size(button, 296, 64);
            lv_obj_t* swatch = ui::container(button);
            lv_obj_set_size(swatch, 16, 44);
            lv_obj_align(swatch, LV_ALIGN_LEFT_MID, 4, 0);
            lv_obj_set_style_radius(swatch, 4, 0);
            lv_obj_set_style_bg_opa(swatch, static_cast<lv_opa_t>(lane.spool_id ? LV_OPA_COVER : LV_OPA_30), 0);
            lv_obj_set_style_bg_color(swatch, lane.spool_id ? ui::swatch_color(lane.color, theme) : theme.muted(), 0);
            std::string name = lane.lane + (lane.map.empty() ? "" : "  " + lane.map);
            lv_obj_t* title = ui::label(button, theme.normal(), theme.text(), name);
            lv_obj_align(title, LV_ALIGN_TOP_LEFT, 30, 4);
            std::string detail = lane.spool_id ? "now #" + std::to_string(*lane.spool_id) +
                                                     (lane.material.empty() ? "" : " " + lane.material)
                                               : "empty";
            if (lane.spool_id && spool_id_ > 0 && *lane.spool_id == spool_id_) detail = "already this spool";
            lv_obj_t* sub = ui::label(button, theme.small(), theme.muted(), detail);
            lv_obj_align(sub, LV_ALIGN_BOTTOM_LEFT, 30, -4);
            ui::set_checked(button, lane.lane == lane_);
            const std::string lane_name = lane.lane;
            ui::on_click(button, [this, lane_name] {
                lane_ = lane_name;
                lv_async_call(refresh_async, this);
            });
        }
    }

    std::string hint;
    if (spool_id_ <= 0) {
        hint = "Enter or scan a spool ID on the main screen first.";
    } else if (printer == nullptr || !printer->connected) {
        hint = "The printer is offline.";
    } else if (lane_.empty()) {
        hint = "Choose the printer and lane the spool is in.";
    } else {
        hint = "Sends SET_SPOOL_ID LANE=" + lane_ + " SPOOL_ID=" + std::to_string(spool_id_) + " to " + printer->name;
    }
    ui::set_text(hint_, hint);
    ui::set_disabled(assign_, spool_id_ <= 0 || lane_.empty() || printer == nullptr || !printer->connected);
}

void AssignDialog::close()
{
    if (dimmer_ != nullptr) {
        lv_obj_delete_async(dimmer_);
        dimmer_ = nullptr;
    }
}

}  // namespace station

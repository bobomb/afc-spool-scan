#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {
namespace {

constexpr int kRowH = 54;
constexpr int kRowGap = 5;
constexpr int kBarMax = 1000;

}  // namespace

PrinterCard::PrinterCard(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app), width_(w)
{
    Theme& theme = app.theme();
    root_ = ui::panel(parent, theme);
    lv_obj_set_pos(root_, x, y);
    lv_obj_set_size(root_, w, h);
    lv_obj_set_style_pad_all(root_, 10, 0);

    dot_ = ui::dot(root_, 12, theme.muted());
    lv_obj_set_pos(dot_, 0, 9);
    name_ = ui::label(root_, theme.normal(), theme.text(), "");
    lv_obj_set_pos(name_, 20, 0);
    lv_obj_set_style_max_width(name_, w / 2, 0);
    lv_obj_set_height(name_, lv_font_get_line_height(theme.normal()));
    lv_label_set_long_mode(name_, LV_LABEL_LONG_MODE_DOTS);
    print_ = ui::chip(root_, theme, "", theme.muted());
    lv_obj_align(print_, LV_ALIGN_TOP_RIGHT, 0, 2);

    status_ = ui::label(root_, theme.small(), theme.muted(), "");
    lv_obj_set_pos(status_, 0, 32);
    lv_obj_set_size(status_, w - 20, 20);
    lv_label_set_long_mode(status_, LV_LABEL_LONG_MODE_DOTS);

    lv_obj_t* pending_box = ui::container(root_);
    lv_obj_set_pos(pending_box, 0, 56);
    lv_obj_set_size(pending_box, w - 20, 40);
    lv_obj_set_style_radius(pending_box, 8, 0);
    lv_obj_set_style_bg_color(pending_box, theme.surface_alt(), 0);
    lv_obj_set_style_bg_opa(pending_box, LV_OPA_COVER, 0);
    pending_ = ui::label(pending_box, theme.small(), theme.text(), "");
    lv_obj_align(pending_, LV_ALIGN_LEFT_MID, 10, 0);
    clear_ = ui::button(pending_box, theme, LV_SYMBOL_CLOSE "  Clear", ui::ButtonStyle::Normal);
    lv_obj_set_size(clear_, 100, 34);
    lv_obj_align(clear_, LV_ALIGN_RIGHT_MID, -3, 0);
    ui::on_click(clear_, [this] { app_.clear_pending(key_); });

    lanes_box_ = ui::container(root_);
    lv_obj_set_pos(lanes_box_, 0, 102);
    lv_obj_set_size(lanes_box_, w - 20, h - 20 - 102);
}

void PrinterCard::build_lanes(std::size_t count)
{
    Theme& theme = app_.theme();
    lv_obj_clean(lanes_box_);
    lanes_.clear();
    const int row_w = width_ - 20;
    for (std::size_t i = 0; i < count; ++i) {
        LaneRow row{};
        row.root = ui::button(lanes_box_, theme, "", ui::ButtonStyle::Normal);
        lv_obj_set_pos(row.root, 0, static_cast<int>(i) * (kRowH + kRowGap));
        lv_obj_set_size(row.root, row_w, kRowH);
        lv_obj_set_style_pad_all(row.root, 0, 0);
        lv_obj_set_style_bg_color(row.root, theme.surface(), 0);

        row.swatch = ui::container(row.root);
        lv_obj_set_size(row.swatch, 22, kRowH - 14);
        lv_obj_align(row.swatch, LV_ALIGN_LEFT_MID, 8, 0);
        lv_obj_set_style_radius(row.swatch, 6, 0);
        lv_obj_set_style_bg_opa(row.swatch, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(row.swatch, 1, 0);
        lv_obj_set_style_border_color(row.swatch, theme.border(), 0);

        row.name = ui::label(row.root, theme.small(), theme.muted(), "");
        lv_obj_set_pos(row.name, 40, 5);
        row.spool = ui::label(row.root, theme.normal(), theme.text(), "");
        lv_obj_set_pos(row.spool, 40, 24);
        lv_obj_set_size(row.spool, row_w - 40 - 130, 28);
        lv_label_set_long_mode(row.spool, LV_LABEL_LONG_MODE_DOTS);

        row.low = ui::chip(row.root, theme, "LOW", theme.warn());
        lv_obj_align(row.low, LV_ALIGN_TOP_RIGHT, -84, 4);
        row.weight = ui::label(row.root, theme.small(), theme.text(), "");
        lv_obj_align(row.weight, LV_ALIGN_TOP_RIGHT, -10, 5);
        row.bar = lv_bar_create(row.root);
        lv_obj_set_size(row.bar, 112, 6);
        lv_obj_align(row.bar, LV_ALIGN_RIGHT_MID, -10, 2);
        lv_bar_set_range(row.bar, 0, kBarMax);
        lv_obj_set_style_bg_color(row.bar, theme.surface_alt(), 0);
        lv_obj_set_style_bg_opa(row.bar, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(row.bar, 3, 0);
        lv_obj_set_style_radius(row.bar, 3, LV_PART_INDICATOR);
        row.status = ui::label(row.root, theme.small(), theme.muted(), "");
        lv_obj_align(row.status, LV_ALIGN_BOTTOM_RIGHT, -10, -3);

        lv_obj_t* button = row.root;
        ui::on_click(button, [this, i] {
            if (i < lanes_.size()) {
                app_.open_assign(key_, lanes_[i].lane);
            }
        });
        lanes_.push_back(row);
    }
}

void PrinterCard::update(const Printer& printer, const Settings& settings, bool online)
{
    Theme& theme = app_.theme();
    key_ = printer.key;
    const bool up = online && printer.connected;
    lv_obj_set_style_bg_color(dot_, !online ? theme.muted() : !printer.connected ? theme.error()
                                  : printer.afc_error.empty() ? theme.ok() : theme.warn(), 0);
    ui::set_text(name_, printer.label());

    std::string print_text = up ? print_state_label(printer.print_state, printer.progress) : "Offline";
    lv_color_t print_color = theme.muted();
    if (up && printer.print_state == "printing") print_color = theme.info();
    else if (up && printer.print_state == "paused") print_color = theme.warn();
    else if (up && printer.print_state == "error") print_color = theme.error();
    else if (up && printer.print_state == "complete") print_color = theme.ok();
    else if (!up) print_color = theme.error();
    ui::set_chip(print_, print_text, print_color);

    std::string status;
    lv_color_t status_color = theme.muted();
    if (!online) {
        status = "Service offline";
    } else if (!printer.connected) {
        status = printer.klippy_state.empty() || printer.klippy_state == "disconnected"
                     ? "Moonraker unreachable - retrying"
                     : "Klipper " + printer.klippy_state;
        status_color = theme.error();
    } else if (!printer.afc_error.empty()) {
        status = LV_SYMBOL_WARNING " " + printer.afc_error;
        status_color = theme.warn();
    } else {
        status = "AFC " + (printer.afc_state.empty() ? std::string("unknown") : printer.afc_state);
        status += printer.current_load.empty() ? "  |  nothing loaded" : "  |  " + printer.current_load + " loaded";
    }
    lv_obj_set_style_text_color(status_, status_color, 0);
    ui::set_text(status_, status);

    if (printer.pending_spool) {
        ui::set_text(pending_, "Next spool  #" + std::to_string(*printer.pending_spool) +
                                   (printer.pending_confirmed ? "  " LV_SYMBOL_OK : "  (sent)"));
        lv_obj_set_style_text_color(pending_, theme.info(), 0);
    } else {
        ui::set_text(pending_, "No pending spool");
        lv_obj_set_style_text_color(pending_, theme.muted(), 0);
    }
    ui::set_disabled(clear_, !up || !printer.pending_spool);
    lv_obj_set_style_opa(lanes_box_, static_cast<lv_opa_t>(up ? LV_OPA_COVER : LV_OPA_40), 0);
    lv_obj_set_style_opa(lv_obj_get_parent(pending_), static_cast<lv_opa_t>(up ? LV_OPA_COVER : LV_OPA_40), 0);

    if (lanes_.size() != printer.lanes.size()) {
        build_lanes(printer.lanes.size());
    }
    for (std::size_t i = 0; i < printer.lanes.size(); ++i) {
        const Lane& lane = printer.lanes[i];
        LaneRow& row = lanes_[i];
        row.lane = lane.lane;
        const bool has_spool = lane.spool_id.has_value();
        lv_obj_set_style_bg_color(row.swatch, has_spool ? ui::swatch_color(lane.color, theme) : theme.surface_alt(), 0);
        lv_obj_set_style_bg_opa(row.swatch, static_cast<lv_opa_t>(has_spool ? LV_OPA_COVER : LV_OPA_50), 0);
        std::string name = lane.lane;
        if (!lane.map.empty()) name += "  " + lane.map;
        ui::set_text(row.name, name);
        if (has_spool) {
            std::string text = "#" + std::to_string(*lane.spool_id);
            if (!lane.material.empty()) text += "  " + lane.material;
            ui::set_text(row.spool, text);
            lv_obj_set_style_text_color(row.spool, theme.text(), 0);
        } else {
            ui::set_text(row.spool, lane.prep ? "Untagged" : "Empty");
            lv_obj_set_style_text_color(row.spool, theme.muted(), 0);
        }
        ui::set_text(row.weight, lane.remaining_g ? fmt_grams(lane.remaining_g) : "");
        lv_obj_set_style_text_color(row.weight, lane.low_stock ? theme.warn() : theme.text(), 0);
        ui::set_hidden(row.bar, !lane.remaining_g);
        if (lane.remaining_g) {
            lv_bar_set_value(row.bar, static_cast<int32_t>(std::min<double>(*lane.remaining_g, kBarMax)), LV_ANIM_OFF);
            lv_obj_set_style_bg_color(row.bar, lane.low_stock ? theme.warn() : theme.ok(), LV_PART_INDICATOR);
        }
        ui::set_hidden(row.low, !lane.low_stock);
        ui::set_text(row.status, lane.filament_status);
        lv_obj_set_style_text_color(row.status, lane.tool_loaded ? theme.info() : theme.muted(), 0);
        const bool loaded = lane.tool_loaded || (!printer.current_load.empty() && printer.current_load == lane.lane);
        lv_obj_set_style_border_color(row.root, loaded ? theme.primary() : theme.border(), 0);
        lv_obj_set_style_border_width(row.root, loaded ? 2 : 1, 0);
        ui::set_disabled(row.root, !up);
    }
    LV_UNUSED(settings);
}

}  // namespace station

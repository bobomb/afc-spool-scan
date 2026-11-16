#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kRowH = 54;
constexpr int kRowGap = 5;
constexpr int kCellGap = 6;
constexpr int kBarMax = 1000;
constexpr int kNarrowW = 300;
constexpr int kGridColumns = 3;

}  // namespace

PrinterCard::PrinterCard(App& app, lv_obj_t* parent, int x, int y, int w, int h)
    : app_(app), width_(w), height_(h), narrow_(w < kNarrowW)
{
    Theme& theme = app.theme();
    root_ = ui::panel(parent, theme);
    lv_obj_set_pos(root_, x, y);
    lv_obj_set_size(root_, w, h);
    lv_obj_set_style_pad_all(root_, 10, 0);

    dot_ = ui::dot(root_, 12, theme.muted());
    lv_obj_set_pos(dot_, 0, 9);
    name_ = ui::label(root_, narrow_ ? theme.small() : theme.normal(), theme.text(), "");
    lv_obj_set_pos(name_, 20, narrow_ ? 3 : 0);
    lv_obj_set_style_max_width(name_, narrow_ ? w - 132 : w / 2, 0);
    lv_obj_set_height(name_, lv_font_get_line_height(narrow_ ? theme.small() : theme.normal()));
    lv_label_set_long_mode(name_, LV_LABEL_LONG_MODE_DOTS);
    print_ = ui::chip(root_, theme, "", theme.muted());
    lv_obj_align(print_, LV_ALIGN_TOP_RIGHT, 0, 2);

    status_ = ui::label(root_, narrow_ ? theme.caption() : theme.small(), theme.muted(), "");
    lv_obj_set_pos(status_, 0, 32);
    lv_obj_set_size(status_, w - 20, 20);
    lv_label_set_long_mode(status_, LV_LABEL_LONG_MODE_DOTS);

    lv_obj_t* pending_box = ui::container(root_);
    lv_obj_set_pos(pending_box, 0, 56);
    lv_obj_set_size(pending_box, w - 20, 40);
    lv_obj_set_style_radius(pending_box, 8, 0);
    lv_obj_set_style_bg_color(pending_box, theme.surface_alt(), 0);
    lv_obj_set_style_bg_opa(pending_box, LV_OPA_COVER, 0);
    pending_ = ui::label(pending_box, narrow_ ? theme.caption() : theme.small(), theme.text(), "");
    lv_obj_align(pending_, LV_ALIGN_LEFT_MID, 10, 0);
    clear_ = ui::button(pending_box, theme, LV_SYMBOL_CLOSE "  Clear", ui::ButtonStyle::Normal,
                        narrow_ ? theme.caption() : nullptr);
    lv_obj_set_size(clear_, narrow_ ? 78 : 100, 34);
    lv_obj_align(clear_, LV_ALIGN_RIGHT_MID, -3, 0);
    ui::on_click(clear_, [this] { app_.clear_pending(key_); });

    lanes_box_ = ui::container(root_);
    lv_obj_set_pos(lanes_box_, 0, 102);
    lv_obj_set_size(lanes_box_, w - 20, h - 20 - 102);
}

void PrinterCard::build_lanes(std::size_t count, bool grid)
{
    Theme& theme = app_.theme();
    lv_obj_clean(lanes_box_);
    lanes_.clear();
    grid_ = grid;
    const int box_w = width_ - 20;
    const int box_h = height_ - 20 - 102;
    const int rows = grid ? (static_cast<int>(count) + kGridColumns - 1) / kGridColumns : 0;
    const int cell_w = (box_w - (kGridColumns - 1) * kCellGap) / kGridColumns;
    cell_w_ = cell_w;
    const int cell_h = rows > 0 ? std::min(110, (box_h - (rows - 1) * kCellGap) / rows) : 0;
    for (std::size_t i = 0; i < count; ++i) {
        LaneRow row{};
        row.grad = {};
        row.root = ui::button(lanes_box_, theme, "", ui::ButtonStyle::Normal);
        lv_obj_set_style_pad_all(row.root, 0, 0);
        lv_obj_set_style_bg_color(row.root, theme.surface(), 0);
        lv_obj_set_style_border_color(row.root, theme.border(), 0);
        if (grid) {
            const int column = static_cast<int>(i) % kGridColumns;
            const int line = static_cast<int>(i) / kGridColumns;
            lv_obj_set_pos(row.root, column * (cell_w + kCellGap), line * (cell_h + kCellGap));
            lv_obj_set_size(row.root, cell_w, cell_h);
            lv_obj_set_style_radius(row.root, 10, 0);
            lv_obj_set_style_outline_color(row.root, theme.primary(), 0);
            lv_obj_set_style_outline_pad(row.root, 1, 0);
            row.name = ui::label(row.root, theme.tiny(), theme.text(), "");
            lv_obj_set_pos(row.name, 7, 4);
            row.spool = ui::label(row.root, theme.small(), theme.text(), "");
            lv_obj_set_pos(row.spool, 7, 20);
            lv_obj_set_width(row.spool, cell_w - 10);
            lv_label_set_long_mode(row.spool, LV_LABEL_LONG_MODE_CLIP);
            row.material = ui::label(row.root, theme.tiny(), theme.text(), "");
            lv_obj_set_pos(row.material, 7, 40);
            lv_obj_set_width(row.material, cell_w - 10);
            lv_label_set_long_mode(row.material, LV_LABEL_LONG_MODE_CLIP);
            row.weight = ui::label(row.root, theme.tiny(), theme.text(), "");
            lv_obj_set_pos(row.weight, 7, 55);
            row.status = ui::label(row.root, theme.tiny(), theme.text(), "");
            lv_obj_align(row.status, LV_ALIGN_BOTTOM_LEFT, 7, -4);
            row.low = ui::label(row.root, theme.tiny(), lv_color_hex(0x1A1206), "LOW");
            lv_obj_set_style_bg_color(row.low, theme.warn(), 0);
            lv_obj_set_style_bg_opa(row.low, LV_OPA_COVER, 0);
            lv_obj_set_style_radius(row.low, 6, 0);
            lv_obj_set_style_pad_hor(row.low, 3, 0);
            lv_obj_set_style_outline_width(row.low, 1, 0);
            lv_obj_align(row.low, LV_ALIGN_BOTTOM_LEFT, 7, -4);
            row.pending = ui::dot(row.root, 10, theme.warn());
            lv_obj_set_style_border_width(row.pending, 2, 0);
            lv_obj_align(row.pending, LV_ALIGN_TOP_RIGHT, -4, 4);
        } else {
            const int row_w = box_w;
            lv_obj_set_pos(row.root, 0, static_cast<int>(i) * (kRowH + kRowGap));
            lv_obj_set_size(row.root, row_w, kRowH);
            row.swatch = ui::container(row.root);
            lv_obj_set_size(row.swatch, narrow_ ? 14 : 22, kRowH - 14);
            lv_obj_align(row.swatch, LV_ALIGN_LEFT_MID, 8, 0);
            lv_obj_set_style_radius(row.swatch, 6, 0);
            lv_obj_set_style_bg_opa(row.swatch, LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(row.swatch, 1, 0);
            lv_obj_set_style_border_color(row.swatch, theme.border(), 0);

            const int text_x = narrow_ ? 30 : 40;
            row.name = ui::label(row.root, narrow_ ? theme.tiny() : theme.small(), theme.muted(), "");
            lv_obj_set_pos(row.name, text_x, 5);
            row.spool = ui::label(row.root, narrow_ ? theme.small() : theme.normal(), theme.text(), "");
            lv_obj_set_pos(row.spool, text_x, narrow_ ? 25 : 24);
            lv_obj_set_size(row.spool, row_w - text_x - (narrow_ ? 70 : 130), 28);
            lv_label_set_long_mode(row.spool, LV_LABEL_LONG_MODE_DOTS);

            row.low = ui::chip(row.root, theme, "LOW", theme.warn());
            lv_obj_align(row.low, LV_ALIGN_TOP_RIGHT, -84, 4);
            row.weight = ui::label(row.root, narrow_ ? theme.caption() : theme.small(), theme.text(), "");
            lv_obj_align(row.weight, LV_ALIGN_TOP_RIGHT, -8, 5);
            row.bar = lv_bar_create(row.root);
            lv_obj_set_size(row.bar, narrow_ ? 60 : 112, 6);
            lv_obj_align(row.bar, LV_ALIGN_RIGHT_MID, -8, 2);
            lv_bar_set_range(row.bar, 0, kBarMax);
            lv_obj_set_style_bg_color(row.bar, theme.surface_alt(), 0);
            lv_obj_set_style_bg_opa(row.bar, LV_OPA_COVER, 0);
            lv_obj_set_style_radius(row.bar, 3, 0);
            lv_obj_set_style_radius(row.bar, 3, LV_PART_INDICATOR);
            row.status = ui::label(row.root, narrow_ ? theme.tiny() : theme.small(), theme.muted(), "");
            lv_obj_align(row.status, LV_ALIGN_BOTTOM_RIGHT, -8, -3);
        }
        ui::on_click(row.root, [this, i] {
            if (i < lanes_.size()) {
                app_.open_assign(key_, lanes_[i].lane);
            }
        });
        lanes_.push_back(std::move(row));
    }
}

std::string PrinterCard::status_text(const Printer& printer, bool online, lv_color_t& color) const
{
    Theme& theme = app_.theme();
    color = theme.muted();
    if (!online) {
        return "Service offline";
    }
    if (printer.off) {
        return "Printer off";
    }
    if (!printer.connected) {
        color = theme.error();
        if (printer.bambu()) return "Bambuddy unreachable - retrying";
        return printer.klippy_state.empty() || printer.klippy_state == "disconnected"
                   ? "Moonraker unreachable - retrying"
                   : "Klipper " + printer.klippy_state;
    }
    if (!printer.afc_error.empty()) {
        color = theme.warn();
        return LV_SYMBOL_WARNING " " + printer.afc_error;
    }
    std::string text = printer.bambu() ? "AMS 3H"
                                       : "AFC " + (printer.afc_state.empty() ? std::string("unknown") : printer.afc_state);
    return text + (printer.current_load.empty() ? "  |  nothing loaded" : "  |  " + printer.current_load + " loaded");
}

void PrinterCard::update(const Printer& printer, const Settings& settings, bool online)
{
    Theme& theme = app_.theme();
    key_ = printer.key;
    const bool up = online && printer.connected;
    const bool off = online && printer.off;
    lv_obj_set_style_bg_color(dot_, !online || off ? theme.muted() : !printer.connected ? theme.error()
                                  : printer.afc_error.empty() ? theme.ok() : theme.warn(), 0);
    ui::set_text(name_, printer.label());

    std::string print_text = off ? "Off" : up ? print_state_label(printer.print_state, printer.progress) : "Offline";
    lv_color_t print_color = theme.muted();
    if (up && printer.print_state == "printing") print_color = theme.info();
    else if (up && printer.print_state == "paused") print_color = theme.warn();
    else if (up && printer.print_state == "error") print_color = theme.error();
    else if (up && printer.print_state == "complete") print_color = theme.ok();
    else if (!up && !off) print_color = theme.error();
    ui::set_chip(print_, print_text, print_color);
    if (narrow_) {
        // The chip's width depends on its text; the name gets what is left of the header row.
        lv_obj_update_layout(print_);
        lv_obj_set_style_max_width(name_, std::max(40, width_ - 20 - 20 - lv_obj_get_width(print_) - 6), 0);
    }

    lv_color_t status_color;
    const std::string status = status_text(printer, online, status_color);
    lv_obj_set_style_text_color(status_, status_color, 0);
    ui::set_text(status_, status);

    if (printer.pending_spool) {
        const std::string prefix = narrow_ ? "Next #" : "Next spool  #";
        ui::set_text(pending_, prefix + std::to_string(*printer.pending_spool) +
                                   (printer.pending_confirmed ? "  " LV_SYMBOL_OK : "  (sent)"));
        lv_obj_set_style_text_color(pending_, theme.info(), 0);
    } else {
        ui::set_text(pending_, narrow_ ? "No next spool" : "No pending spool");
        lv_obj_set_style_text_color(pending_, theme.muted(), 0);
    }
    ui::set_disabled(clear_, !up || !printer.pending_spool);
    lv_obj_set_style_opa(lanes_box_, static_cast<lv_opa_t>(up ? LV_OPA_COVER : LV_OPA_40), 0);
    lv_obj_set_style_opa(lv_obj_get_parent(pending_), static_cast<lv_opa_t>(up ? LV_OPA_COVER : LV_OPA_40), 0);

    const bool grid = printer.bambu();
    if (lanes_.size() != printer.lanes.size() || grid_ != grid) {
        build_lanes(printer.lanes.size(), grid);
    }
    for (std::size_t i = 0; i < printer.lanes.size(); ++i) {
        const Lane& lane = printer.lanes[i];
        LaneRow& row = lanes_[i];
        row.lane = lane.lane;
        const bool loaded = lane.tool_loaded || (!printer.current_load.empty() && printer.current_load == lane.lane);
        if (grid) {
            update_cell(row, lane, loaded);
        } else {
            update_row(row, lane, loaded);
        }
        ui::set_disabled(row.root, !up);
    }
    LV_UNUSED(settings);
}

void PrinterCard::update_row(LaneRow& row, const Lane& lane, bool loaded)
{
    Theme& theme = app_.theme();
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
    ui::set_hidden(row.low, narrow_ || !lane.low_stock);
    const bool pending = has_spool && lane.settings_pending;
    ui::set_text(row.status, pending ? "Settings after print" : lane.filament_status);
    lv_obj_set_style_text_color(row.status, pending ? theme.warn() : lane.tool_loaded ? theme.info() : theme.muted(),
                                0);
    lv_obj_set_style_border_color(row.root, loaded ? theme.primary() : theme.border(), 0);
    lv_obj_set_style_border_width(row.root, loaded ? 2 : 1, 0);
}

void PrinterCard::update_cell(LaneRow& row, const Lane& lane, bool loaded)
{
    Theme& theme = app_.theme();
    lv_color_t mark = theme.muted();
    const bool has_spool = lane.spool_id.has_value();
    if (has_spool) {
        std::vector<std::uint32_t> colors = parse_colors(lane.colors);
        if (colors.empty()) colors.push_back(theme.palette().surface_alt);
        mark = ui::fill(row.root, colors, row.grad, theme, theme.palette().surface);
        ui::set_text(row.spool, "#" + std::to_string(*lane.spool_id));
        ui::set_text(row.material, lane.material.empty() ? "--" : lane.material);
        ui::set_text(row.weight, lane.remaining_g ? fmt_grams(lane.remaining_g) : "");
        ui::set_text(row.status, lane.settings_pending ? "Pending" : lane.filament_status);
    } else {
        lv_obj_set_style_bg_grad(row.root, nullptr, 0);
        lv_obj_set_style_bg_color(row.root, lane.prep ? theme.surface_alt() : theme.bg(), 0);
        lv_obj_set_style_bg_opa(row.root, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(row.root, lane.prep ? 0 : 1, 0);
        ui::set_text(row.spool, "");
        ui::set_text(row.material, lane.prep ? "No tag" : "Empty");
        ui::set_text(row.weight, "");
        ui::set_text(row.status, "");
    }
    lv_obj_set_style_text_font(row.material, has_spool ? theme.tiny() : theme.caption(), 0);
    lv_obj_set_pos(row.material, has_spool ? 7 : 4, has_spool ? 40 : 24);
    lv_obj_set_width(row.material, cell_w_ - (has_spool ? 10 : 5));
    if (!has_spool && lane.prep) lv_obj_set_style_text_font(row.material, theme.tiny(), 0);
    lv_obj_set_style_text_opa(row.name, LV_OPA_80, 0);
    for (lv_obj_t* label : {row.name, row.spool, row.material, row.weight, row.status}) {
        lv_obj_set_style_text_color(label, mark, 0);
    }
    lv_obj_set_style_outline_color(row.low, mark, 0);
    lv_obj_set_style_border_color(row.pending, mark, 0);
    ui::set_text(row.name, lane.lane);
    const bool low = has_spool && lane.low_stock;
    ui::set_hidden(row.low, !low);
    ui::set_hidden(row.status, low);
    ui::set_hidden(row.pending, !(has_spool && lane.settings_pending));
    lv_obj_set_style_outline_width(row.root, loaded ? 2 : 0, 0);
}

}  // namespace station

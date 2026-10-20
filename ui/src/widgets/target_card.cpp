#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kTileW = 71;
constexpr int kTileH = 96;
constexpr int kTileGap = 8;
constexpr int kLanesY = 50;
constexpr int kInset = 16;
constexpr int kOutline = 4;

}  // namespace

TargetCard::TargetCard(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app), width_(w)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, x, y);
    lv_obj_set_size(root_, w, h);
    lv_obj_set_style_radius(root_, 16, 0);
    lv_obj_set_style_bg_color(root_, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);

    lv_obj_t* head = ui::container(root_);
    lv_obj_set_pos(head, kInset + 2, 10);
    lv_obj_set_size(head, w - 2 * kInset, 30);
    lv_obj_set_flex_flow(head, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(head, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(head, 10, 0);
    dot_ = ui::dot(head, 10, theme.muted());
    name_ = ui::label(head, theme.normal(), theme.text(), "");
    lv_obj_set_style_max_width(name_, (w - 2 * kInset) / 2, 0);
    lv_obj_set_height(name_, lv_font_get_line_height(theme.normal()));
    lv_label_set_long_mode(name_, LV_LABEL_LONG_MODE_DOTS);
    state_ = ui::label(head, theme.caption(), theme.muted(), "");

    // Room around the tiles for the in-tool outline, which would otherwise be clipped.
    lanes_box_ = ui::container(root_);
    lv_obj_set_pos(lanes_box_, kInset - kOutline, kLanesY - kOutline);
    lv_obj_set_size(lanes_box_, w - 2 * kInset + 2 * kOutline, kTileH + 2 * kOutline);

    footer_ = ui::label(root_, theme.caption(), theme.info(), "");
    lv_obj_set_pos(footer_, kInset + 2, h - 24);
    lv_obj_set_size(footer_, w - 2 * kInset, 18);
    lv_label_set_long_mode(footer_, LV_LABEL_LONG_MODE_DOTS);
}

void TargetCard::build_tiles(std::size_t count)
{
    Theme& theme = app_.theme();
    lv_obj_clean(lanes_box_);
    tiles_.clear();
    const int inner = width_ - 2 * kInset;
    const int n = static_cast<int>(count);
    const int tile_w = n == 0 ? kTileW : std::min(kTileW, (inner - (n - 1) * kTileGap) / n);
    const int ring = std::min(48, tile_w - 12);
    for (int i = 0; i < n; ++i) {
        auto tile = std::make_unique<LaneTile>();
        tile->grad = {};
        tile->root = ui::container(lanes_box_);
        lv_obj_set_pos(tile->root, kOutline + i * (tile_w + kTileGap), kOutline);
        lv_obj_set_size(tile->root, tile_w, kTileH);
        lv_obj_set_style_radius(tile->root, 12, 0);
        lv_obj_set_style_border_color(tile->root, theme.border(), 0);
        lv_obj_set_style_outline_color(tile->root, theme.primary(), 0);
        lv_obj_set_style_outline_pad(tile->root, 2, 0);

        tile->ring = ui::ring(tile->root, ring, 6);
        lv_obj_align(tile->ring, LV_ALIGN_TOP_MID, 0, 7);
        lv_obj_t* center = ui::container(tile->ring);
        lv_obj_set_size(center, ring - 12, ring - 12);
        lv_obj_center(center);
        lv_obj_set_flex_flow(center, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(center, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        tile->value = ui::label(center, theme.caption(), theme.text(), "");
        tile->unit = ui::label(center, theme.tiny(), theme.text(), "");
        lv_obj_set_style_margin_top(tile->unit, -4, 0);
        lv_obj_set_style_translate_y(center, 2, 0);
        tile->material = ui::label(tile->root, theme.caption(), theme.text(), "");
        lv_obj_set_size(tile->material, tile_w - 4, 18);
        lv_obj_set_style_text_align(tile->material, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(tile->material, LV_LABEL_LONG_MODE_DOTS);
        lv_obj_set_pos(tile->material, 2, 59);

        lv_obj_t* row = ui::container(tile->root);
        lv_obj_set_size(row, tile_w, 16);
        lv_obj_set_pos(row, 0, 77);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(row, 4, 0);
        tile->id = ui::label(row, theme.tiny(), theme.text(), "");
        tile->low = ui::label(row, theme.tiny(), lv_color_hex(0x1A1206), "LOW");
        lv_obj_set_style_bg_color(tile->low, theme.warn(), 0);
        lv_obj_set_style_bg_opa(tile->low, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(tile->low, 6, 0);
        lv_obj_set_style_pad_hor(tile->low, 4, 0);
        lv_obj_set_style_outline_width(tile->low, 1, 0);
        tiles_.push_back(std::move(tile));
    }
}

void TargetCard::update(const Printer& printer, bool online)
{
    Theme& theme = app_.theme();
    key_ = printer.key;
    const bool up = online && printer.connected;
    lv_obj_set_style_bg_color(dot_, !online ? theme.muted() : !printer.connected ? theme.error()
                                  : printer.afc_error.empty() ? theme.ok() : theme.warn(), 0);
    ui::set_text(name_, printer.label());

    std::string status = up ? print_state_label(printer.print_state, printer.progress) : "Offline";
    lv_color_t status_color = theme.muted();
    if (!up) status_color = theme.error();
    else if (!printer.afc_error.empty()) {
        status = "AFC error";
        status_color = theme.warn();
    } else if (printer.print_state == "printing") status_color = theme.info();
    else if (printer.print_state == "paused") status_color = theme.warn();
    else if (printer.print_state == "error") status_color = theme.error();
    lv_obj_set_style_text_color(state_, status_color, 0);
    ui::set_text(state_, status);

    lv_obj_set_style_opa(lanes_box_, static_cast<lv_opa_t>(up ? LV_OPA_COVER : 115), 0);

    if (printer.pending_spool) {
        ui::set_text(footer_, LV_SYMBOL_DOWNLOAD "  Next spool #" + std::to_string(*printer.pending_spool) +
                                  (printer.pending_confirmed ? "" : "  (sent)"));
        lv_obj_set_style_text_color(footer_, theme.info(), 0);
    } else {
        ui::set_text(footer_, "No pending spool");
        lv_obj_set_style_text_color(footer_, theme.muted(), 0);
    }

    if (tiles_.size() != printer.lanes.size()) {
        build_tiles(printer.lanes.size());
    }
    for (std::size_t i = 0; i < printer.lanes.size(); ++i) {
        const Lane& lane = printer.lanes[i];
        LaneTile& tile = *tiles_[i];
        const bool in_tool = lane.tool_loaded || (!printer.current_load.empty() && printer.current_load == lane.lane);
        lv_obj_set_style_outline_width(tile.root, in_tool ? 2 : 0, 0);
        lv_color_t mark = theme.muted();
        if (lane.spool_id) {
            std::vector<std::uint32_t> colors = parse_colors(lane.colors);
            if (colors.empty()) colors.push_back(theme.palette().surface_alt);
            mark = ui::fill(tile.root, colors, tile.grad, theme, theme.palette().surface);
            ui::set_ring(tile.ring, lane.remaining_pct, mark);
            if (lane.remaining_g) {
                const auto [value, unit] = compact_weight(*lane.remaining_g);
                ui::set_text(tile.value, value);
                ui::set_text(tile.unit, unit);
            } else {
                ui::set_text(tile.value, "?");
                ui::set_text(tile.unit, "");
            }
            lv_obj_set_style_text_font(tile.material, theme.caption(), 0);
            ui::set_text(tile.material, lane.material.empty() ? "--" : lane.material);
            ui::set_text(tile.id, "#" + std::to_string(*lane.spool_id));
        } else {
            lv_obj_set_style_bg_grad(tile.root, nullptr, 0);
            const bool untagged = lane.prep;
            lv_obj_set_style_bg_color(tile.root, theme.surface_alt(), 0);
            lv_obj_set_style_bg_opa(tile.root, static_cast<lv_opa_t>(untagged ? LV_OPA_COVER : LV_OPA_TRANSP), 0);
            lv_obj_set_style_border_width(tile.root, untagged ? 0 : 2, 0);
            ui::set_ring(tile.ring, std::nullopt, theme.muted());
            ui::set_text(tile.value, untagged ? "?" : "-");
            ui::set_text(tile.unit, "");
            lv_obj_set_style_text_font(tile.material, untagged ? theme.tiny() : theme.caption(), 0);
            ui::set_text(tile.material, untagged ? "Untagged" : "Empty");
            ui::set_text(tile.id, "");
        }
        lv_obj_set_style_text_color(tile.value, mark, 0);
        lv_obj_set_style_text_color(tile.unit, mark, 0);
        lv_obj_set_style_text_color(tile.material, mark, 0);
        lv_obj_set_style_text_color(tile.id, mark, 0);
        lv_obj_set_style_outline_color(tile.low, mark, 0);
        ui::set_hidden(tile.low, !(lane.spool_id && lane.low_stock));
    }
}

}  // namespace station

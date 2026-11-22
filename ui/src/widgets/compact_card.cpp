#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kHeadW = 122;
constexpr int kInsetY = 7;
constexpr int kRightInset = 10;
constexpr int kTileGap = 5;
constexpr int kMaxTileW = 58;
constexpr int kRing = 38;
constexpr int kRingY = 18;
constexpr int kLineY = kRingY + kRing + 2;
constexpr int kOutline = 4;

}  // namespace

CompactCard::CompactCard(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app), width_(w), height_(h)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, x, y);
    lv_obj_set_size(root_, w, h);
    lv_obj_set_style_radius(root_, 16, 0);
    lv_obj_set_style_bg_color(root_, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);

    dot_ = ui::dot(root_, 9, theme.muted());
    lv_obj_set_pos(dot_, 14, 17);
    name_ = ui::label(root_, theme.small(), theme.text(), "");
    lv_obj_set_pos(name_, 29, 9);
    lv_obj_set_size(name_, kHeadW - 33, lv_font_get_line_height(theme.small()));
    lv_label_set_long_mode(name_, LV_LABEL_LONG_MODE_DOTS);
    state_ = ui::label(root_, theme.tiny(), theme.muted(), "");
    lv_obj_set_pos(state_, 14, 36);
    lv_obj_set_size(state_, kHeadW - 16, 16);
    lv_label_set_long_mode(state_, LV_LABEL_LONG_MODE_DOTS);
    next_ = ui::label(root_, theme.tiny(), theme.info(), "");
    lv_obj_set_pos(next_, 14, 58);
    lv_obj_set_size(next_, kHeadW - 16, 16);
    lv_label_set_long_mode(next_, LV_LABEL_LONG_MODE_DOTS);

    // Room around the tiles for the in-tool outline, which would otherwise be clipped.
    lanes_box_ = ui::container(root_);
    lv_obj_set_pos(lanes_box_, kHeadW - kOutline, kInsetY - kOutline);
    lv_obj_set_size(lanes_box_, w - kHeadW - kRightInset + 2 * kOutline, h - 2 * kInsetY + 2 * kOutline);
}

void CompactCard::build_tiles(std::size_t count)
{
    Theme& theme = app_.theme();
    lv_obj_clean(lanes_box_);
    tiles_.clear();
    const int area = width_ - kHeadW - kRightInset;
    const int n = std::max(1, static_cast<int>(count));
    const int tile_w = std::min(kMaxTileW, (area - (n - 1) * kTileGap) / n);
    const int tile_h = height_ - 2 * kInsetY;
    for (std::size_t i = 0; i < count; ++i) {
        auto tile = std::make_unique<Tile>();
        tile->grad = {};
        tile->root = ui::container(lanes_box_);
        lv_obj_set_pos(tile->root, kOutline + static_cast<int>(i) * (tile_w + kTileGap), kOutline);
        lv_obj_set_size(tile->root, tile_w, tile_h);
        lv_obj_set_style_radius(tile->root, 10, 0);
        lv_obj_set_style_border_color(tile->root, theme.border(), 0);
        lv_obj_set_style_outline_color(tile->root, theme.primary(), 0);
        lv_obj_set_style_outline_pad(tile->root, 2, 0);

        tile->tool = ui::label(tile->root, theme.tiny(), theme.text(), "");
        lv_obj_set_size(tile->tool, tile_w - 2, 15);
        lv_obj_set_style_text_align(tile->tool, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(tile->tool, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_pos(tile->tool, 1, 2);
        tile->ring = ui::ring(tile->root, kRing, 5);
        lv_obj_align(tile->ring, LV_ALIGN_TOP_MID, 0, kRingY);
        tile->value = ui::label(tile->ring, theme.tiny(), theme.text(), "");
        lv_obj_center(tile->value);
        tile->line1 = ui::label(tile->root, theme.tiny(), theme.text(), "");
        lv_obj_set_size(tile->line1, tile_w - 2, 15);
        lv_obj_set_style_text_align(tile->line1, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(tile->line1, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_pos(tile->line1, 1, kLineY);
        tile->low = ui::label(tile->root, theme.tiny(), lv_color_hex(0x1A1206), "LOW");
        lv_obj_set_style_bg_color(tile->low, theme.warn(), 0);
        lv_obj_set_style_bg_opa(tile->low, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(tile->low, 6, 0);
        lv_obj_set_style_pad_hor(tile->low, 3, 0);
        lv_obj_set_style_outline_width(tile->low, 1, 0);
        lv_obj_align(tile->low, LV_ALIGN_TOP_MID, 0, kLineY);
        tile->line2 = ui::label(tile->root, theme.tiny(), theme.text(), "");
        lv_obj_set_size(tile->line2, tile_w - 2, 15);
        lv_obj_set_style_text_align(tile->line2, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(tile->line2, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_pos(tile->line2, 1, kLineY + 15);
        tile->pending = ui::dot(tile->root, 9, theme.warn());
        lv_obj_align(tile->pending, LV_ALIGN_TOP_RIGHT, -2, kRingY);
        lv_obj_set_style_border_width(tile->pending, 2, 0);
        tiles_.push_back(std::move(tile));
    }
}

void CompactCard::update(const Printer& printer, bool online)
{
    Theme& theme = app_.theme();
    const bool up = online && printer.connected;
    const bool off = online && printer.off;
    lv_obj_set_style_bg_color(dot_, !online || off ? theme.muted() : !printer.connected ? theme.error()
                                  : printer.afc_error.empty() ? theme.ok() : theme.warn(), 0);
    ui::set_text(name_, printer.label());

    std::string status = off ? "Off" : up ? print_state_label(printer.print_state, printer.progress) : "Offline";
    lv_color_t status_color = theme.muted();
    if (!up && !off) status_color = theme.error();
    else if (up && !printer.afc_error.empty()) {
        status = "Error";
        status_color = theme.warn();
    } else if (up && printer.print_state == "printing") status_color = theme.info();
    else if (up && printer.print_state == "paused") status_color = theme.warn();
    else if (up && printer.print_state == "complete") status_color = theme.ok();
    else if (up && printer.print_state == "error") status_color = theme.error();
    lv_obj_set_style_text_color(state_, status_color, 0);
    ui::set_text(state_, status);
    ui::set_text(next_, printer.pending_spool ? LV_SYMBOL_DOWNLOAD " #" + std::to_string(*printer.pending_spool) : "");

    lv_obj_set_style_opa(lanes_box_, static_cast<lv_opa_t>(up ? LV_OPA_COVER : 115), 0);
    if (tiles_.size() != printer.lanes.size()) {
        build_tiles(printer.lanes.size());
    }
    for (std::size_t i = 0; i < printer.lanes.size(); ++i) {
        const Lane& lane = printer.lanes[i];
        Tile& tile = *tiles_[i];
        const bool in_tool = lane.tool_loaded || (!printer.current_load.empty() && printer.current_load == lane.lane);
        lv_obj_set_style_outline_width(tile.root, in_tool ? 2 : 0, 0);
        lv_color_t mark = theme.muted();
        const bool low = lane.spool_id && lane.low_stock;
        if (lane.spool_id) {
            std::vector<std::uint32_t> colors = parse_colors(lane.colors);
            if (colors.empty()) colors.push_back(theme.palette().surface_alt);
            mark = ui::fill(tile.root, colors, tile.grad, theme, theme.palette().surface);
            ui::set_ring(tile.ring, lane.remaining_pct, mark);
            if (lane.remaining_g) {
                const auto [value, unit] = compact_weight(*lane.remaining_g);
                ui::set_text(tile.value, unit == "kg" ? value + "k" : value);
            } else {
                ui::set_text(tile.value, "?");
            }
            ui::set_text(tile.line1, lane.material.empty() ? "--" : lane.material);
            ui::set_text(tile.line2, "#" + std::to_string(*lane.spool_id));
        } else {
            lv_obj_set_style_bg_grad(tile.root, nullptr, 0);
            const bool untagged = lane.prep;
            lv_obj_set_style_bg_color(tile.root, theme.surface_alt(), 0);
            lv_obj_set_style_bg_opa(tile.root, static_cast<lv_opa_t>(untagged ? LV_OPA_COVER : LV_OPA_TRANSP), 0);
            lv_obj_set_style_border_width(tile.root, untagged ? 0 : 2, 0);
            ui::set_ring(tile.ring, std::nullopt, theme.muted());
            ui::set_text(tile.value, untagged ? "?" : "-");
            ui::set_text(tile.line1, untagged ? "No tag" : "Empty");
            ui::set_text(tile.line2, "");
        }
        lv_obj_set_style_text_color(tile.value, mark, 0);
        lv_obj_set_style_text_color(tile.line1, mark, 0);
        lv_obj_set_style_text_color(tile.line2, mark, 0);
        ui::set_text(tile.tool, lane.map + (lane.nozzle.empty() ? "" : " " + lane.nozzle));
        lv_obj_set_style_text_color(tile.tool, mark, 0);
        lv_obj_set_style_outline_color(tile.low, mark, 0);
        lv_obj_set_style_border_color(tile.pending, mark, 0);
        ui::set_hidden(tile.low, !low);
        ui::set_hidden(tile.line1, low);
        ui::set_hidden(tile.pending, !(lane.spool_id && lane.settings_pending));
    }
}

}  // namespace station

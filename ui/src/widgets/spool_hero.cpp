#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kTile = 104;
constexpr int kRing = 80;
constexpr int kTextX = 130;
constexpr int kDividerX = 504;
constexpr int kScaleX = 522;

lv_obj_t* make_pill(lv_obj_t* parent, Theme& theme)
{
    lv_obj_t* pill = ui::container(parent);
    lv_obj_set_size(pill, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_radius(pill, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_pad_hor(pill, 10, 0);
    lv_obj_set_style_pad_ver(pill, 3, 0);
    lv_obj_set_style_bg_opa(pill, 41, 0);
    ui::label(pill, theme.caption(), theme.text(), "");
    return pill;
}

void set_pill(lv_obj_t* pill, const std::string& text, lv_color_t color)
{
    lv_obj_set_style_bg_color(pill, color, 0);
    lv_obj_t* text_label = lv_obj_get_child(pill, 0);
    lv_obj_set_style_text_color(text_label, color, 0);
    ui::set_text(text_label, text);
}

std::string weight_text(double grams)
{
    return fmt_number(grams, grams >= 1000 || grams <= -1000 ? 0 : 1);
}

}  // namespace

SpoolHero::SpoolHero(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, x, y);
    lv_obj_set_size(root_, w, h);
    lv_obj_set_style_radius(root_, 16, 0);
    lv_obj_set_style_bg_color(root_, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(root_, theme.surface_alt(), LV_STATE_PRESSED);
    ui::on_click(root_, [this] { app_.open_keypad(); });

    tile_ = ui::container(root_);
    lv_obj_set_pos(tile_, 12, (h - kTile) / 2);
    lv_obj_set_size(tile_, kTile, kTile);
    lv_obj_set_style_radius(tile_, 18, 0);
    lv_obj_set_style_border_color(tile_, theme.border(), 0);
    ring_ = ui::ring(tile_, kRing, 9);
    lv_obj_center(ring_);
    lv_obj_t* center = ui::container(tile_);
    lv_obj_set_size(center, kRing, kRing);
    lv_obj_center(center);
    lv_obj_set_flex_flow(center, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(center, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    pct_ = ui::label(center, theme.normal(), theme.text(), "");
    sub_ = ui::label(center, theme.caption(), theme.text(), "");

    lv_obj_t* head = ui::container(root_);
    lv_obj_set_pos(head, kTextX, 10);
    lv_obj_set_size(head, kDividerX - kTextX - 8, 22);
    lv_obj_set_flex_flow(head, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(head, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(head, 8, 0);
    line1_ = ui::label(head, theme.caption(), theme.muted(), "");
    tags_ = ui::container(head);
    lv_obj_set_size(tags_, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(tags_, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(tags_, 6, 0);

    title_ = ui::label(root_, theme.large(), theme.text(), "");
    lv_obj_set_pos(title_, kTextX - 2, 30);
    lv_obj_set_size(title_, kDividerX - kTextX - 10, 34);
    lv_label_set_long_mode(title_, LV_LABEL_LONG_MODE_DOTS);
    line3_ = ui::label(root_, theme.small(), theme.muted(), "");
    lv_obj_set_pos(line3_, kTextX, 72);
    lv_obj_set_size(line3_, kDividerX - kTextX - 10, 20);
    lv_label_set_long_mode(line3_, LV_LABEL_LONG_MODE_DOTS);
    line4_ = ui::label(root_, theme.small(), theme.text(), "");
    lv_obj_set_pos(line4_, kTextX, 96);
    lv_obj_set_size(line4_, kDividerX - kTextX - 10, 20);
    lv_label_set_long_mode(line4_, LV_LABEL_LONG_MODE_DOTS);

    lv_obj_t* divider = ui::container(root_);
    lv_obj_set_pos(divider, kDividerX, 16);
    lv_obj_set_size(divider, 1, h - 32);
    lv_obj_set_style_bg_color(divider, theme.surface_alt(), 0);
    lv_obj_set_style_bg_opa(divider, LV_OPA_COVER, 0);

    lv_obj_t* cap = ui::label(root_, theme.caption(), theme.muted(), "ON SCALE");
    lv_obj_set_style_text_letter_space(cap, 1, 0);
    lv_obj_set_pos(cap, kScaleX, 14);
    lv_obj_t* reading = ui::container(root_);
    lv_obj_set_pos(reading, kScaleX - 2, 30);
    lv_obj_set_size(reading, w - kScaleX - 8, 58);
    lv_obj_set_flex_flow(reading, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(reading, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_END);
    lv_obj_set_style_pad_column(reading, 6, 0);
    weight_ = ui::label(reading, theme.huge(), theme.text(), "");
    unit_ = ui::label(reading, theme.normal(), theme.muted(), "g");
    lv_obj_set_style_pad_bottom(unit_, 8, 0);
    check_ = make_pill(root_, theme);
    lv_obj_set_pos(check_, kScaleX, 92);

    lv_obj_t* hint = ui::label(root_, theme.small(), theme.muted(), LV_SYMBOL_KEYBOARD);
    lv_obj_align(hint, LV_ALIGN_TOP_RIGHT, -12, 8);
}

void SpoolHero::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    const auto& spool = state.spool;
    lv_obj_clean(tags_);

    if (spool && spool->found) {
        std::vector<std::uint32_t> colors = parse_colors(spool->colors);
        if (colors.empty()) colors.push_back(theme.palette().surface_alt);
        const lv_color_t mark = ui::fill(tile_, colors, grad_, theme, theme.palette().surface);
        const auto pct = spool_remaining_pct(*spool);
        ui::set_hidden(ring_, false);
        ui::set_ring(ring_, pct, mark);
        lv_obj_set_style_text_font(pct_, theme.normal(), 0);
        ui::set_text(pct_, pct ? fmt_percent(*pct) : fmt_grams(spool->remaining_g));
        ui::set_text(sub_, "left");
        lv_obj_set_style_text_color(pct_, mark, 0);
        lv_obj_set_style_text_color(sub_, mark, 0);

        std::string head = "#" + std::to_string(spool->id);
        if (!spool->vendor.empty()) head += "  \xE2\x80\xA2  " + spool->vendor;
        lv_obj_set_style_text_letter_space(line1_, 0, 0);
        ui::set_text(line1_, head);
        if (spool->low_stock) ui::label(tags_, theme.caption(), theme.warn(), "LOW");
        if (spool->archived) ui::label(tags_, theme.caption(), theme.muted(), "ARCHIVED");
        ui::set_text(title_, spool->name.empty() ? "Unnamed filament" : spool->name);
        std::vector<std::string> details;
        if (!spool->material.empty()) details.push_back(spool->material);
        if (!spool->location.empty()) details.push_back(spool->location);
        ui::set_text(line3_, join(details, "  \xE2\x80\xA2  "));
        std::string amounts = fmt_grams(spool->remaining_g) + " left  \xE2\x80\xA2  ";
        amounts += spool->spool_weight_g ? "tare " + fmt_grams(spool->spool_weight_g) : "tare unknown";
        ui::set_text(line4_, amounts);
        lv_obj_set_style_text_color(line4_, spool->low_stock ? theme.warn() : theme.text(), 0);
    } else {
        lv_obj_set_style_bg_grad(tile_, nullptr, 0);
        ui::set_hidden(ring_, true);
        lv_obj_set_style_text_font(pct_, theme.large(), 0);
        lv_obj_set_style_text_color(pct_, theme.muted(), 0);
        lv_obj_set_style_text_color(sub_, theme.muted(), 0);
        lv_obj_set_style_text_letter_space(line1_, 1, 0);
        lv_obj_set_style_text_color(line4_, theme.text(), 0);
        if (spool) {
            lv_obj_set_style_bg_color(tile_, theme.surface_alt(), 0);
            lv_obj_set_style_bg_opa(tile_, LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(tile_, 0, 0);
            ui::set_text(pct_, "?");
            ui::set_text(sub_, "not found");
            ui::set_text(line1_, "SPOOL #" + std::to_string(spool->id));
            ui::set_text(title_, "Not found in Spoolman");
            ui::set_text(line3_, "Check the ID, or scan the spool's QR code");
        } else {
            lv_obj_set_style_bg_opa(tile_, LV_OPA_TRANSP, 0);
            lv_obj_set_style_border_width(tile_, 2, 0);
            ui::set_text(pct_, LV_SYMBOL_KEYBOARD);
            ui::set_text(sub_, "Type ID");
            ui::set_text(line1_, "NO SPOOL SELECTED");
            ui::set_text(title_, "Scan a spool");
            ui::set_text(line3_, "or tap here to type its ID");
        }
        ui::set_text(line4_, "");
    }

    const ScaleState& scale = state.scale;
    const bool present = online && scale.present && scale.grams;
    const bool empty_scale = present && *scale.grams <= 0;
    ui::set_text(weight_, present ? weight_text(*scale.grams) : "--");
    lv_obj_set_style_text_color(weight_, present && !empty_scale ? theme.text() : theme.muted(), 0);
    ui::set_hidden(unit_, !present);

    std::string check;
    lv_color_t check_color = theme.muted();
    if (!online || !scale.present) {
        check = "Scale off";
    } else if (spool && spool->found && scale.check == "ok" && scale.stable) {
        check = LV_SYMBOL_OK " Matches Spoolman";
        check_color = theme.ok();
    } else if (spool && spool->found && scale.check == "warn" && scale.delta_g) {
        check = LV_SYMBOL_WARNING " Off by " + fmt_delta(*scale.delta_g);
        check_color = theme.warn();
    } else if (spool && spool->found && scale.check == "tare_unknown" && scale.stable) {
        check = "Tare unknown";
    } else if (empty_scale) {
        check = "Scale empty";
    } else {
        check = scale_status_label(scale.status);
        if (scale.status == "stable") check_color = theme.ok();
        else if (scale.status != "motion") check_color = theme.warn();
    }
    set_pill(check_, check, check_color);
}

}  // namespace station

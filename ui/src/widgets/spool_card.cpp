#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {

SpoolCard::SpoolCard(App& app, lv_obj_t* parent, int x, int y, int w) : app_(app)
{
    Theme& theme = app.theme();

    lv_obj_t* entry = ui::panel(parent, theme);
    lv_obj_set_pos(entry, x, y);
    lv_obj_set_size(entry, w, kEntryH);
    lv_obj_set_style_pad_hor(entry, 12, 0);
    lv_obj_set_style_pad_ver(entry, 4, 0);
    lv_obj_t* caption = ui::label(entry, theme.small(), theme.muted(), "SPOOL");
    lv_obj_align(caption, LV_ALIGN_LEFT_MID, 0, 0);
    digits_ = ui::label(entry, theme.large(), theme.text(), "");
    lv_obj_align(digits_, LV_ALIGN_LEFT_MID, 70, 0);
    placeholder_ = ui::label(entry, theme.small(), theme.muted(), "Scan a QR code or type an ID");
    lv_obj_align(placeholder_, LV_ALIGN_LEFT_MID, 70, 0);
    backspace_ = ui::button(entry, theme, LV_SYMBOL_BACKSPACE, ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(backspace_, 72, 44);
    lv_obj_align(backspace_, LV_ALIGN_RIGHT_MID, 6, 0);
    ui::on_click(backspace_, [this] { app_.handle_key("backspace"); });

    card_ = ui::panel(parent, theme);
    lv_obj_set_pos(card_, x, y + kEntryH + 6);
    lv_obj_set_size(card_, w, kCardH);
    lv_obj_set_style_pad_all(card_, 10, 0);

    swatch_ = ui::container(card_);
    lv_obj_set_size(swatch_, 34, kCardH - 20);
    lv_obj_align(swatch_, LV_ALIGN_LEFT_MID, 0, 0);
    lv_obj_set_style_radius(swatch_, 8, 0);
    lv_obj_set_style_bg_opa(swatch_, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(swatch_, 1, 0);
    lv_obj_set_style_border_color(swatch_, theme.border(), 0);

    const int text_x = 48;
    const int text_w = w - 20 - text_x;
    line1_ = ui::label(card_, theme.small(), theme.muted(), "");
    lv_obj_set_pos(line1_, text_x, 0);
    lv_obj_set_size(line1_, text_w - 170, 20);
    lv_label_set_long_mode(line1_, LV_LABEL_LONG_MODE_DOTS);
    tags_ = ui::container(card_);
    lv_obj_set_size(tags_, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(tags_, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(tags_, 6, 0);
    lv_obj_align(tags_, LV_ALIGN_TOP_RIGHT, 0, -2);
    line2_ = ui::label(card_, theme.normal(), theme.text(), "");
    lv_obj_set_pos(line2_, text_x, 20);
    lv_obj_set_size(line2_, text_w, 28);
    lv_label_set_long_mode(line2_, LV_LABEL_LONG_MODE_DOTS);
    line3_ = ui::label(card_, theme.small(), theme.text(), "");
    lv_obj_set_pos(line3_, text_x, 50);
    lv_obj_set_size(line3_, text_w, 20);
    lv_label_set_long_mode(line3_, LV_LABEL_LONG_MODE_DOTS);
    line4_ = ui::label(card_, theme.small(), theme.warn(), "");
    lv_obj_set_pos(line4_, text_x, 71);
    lv_obj_set_size(line4_, text_w, 20);
    lv_label_set_long_mode(line4_, LV_LABEL_LONG_MODE_DOTS);
}

void SpoolCard::update(const State& state, const std::string& entry)
{
    Theme& theme = app_.theme();
    ui::set_text(digits_, entry);
    ui::set_hidden(placeholder_, !entry.empty());
    ui::set_disabled(backspace_, entry.empty());

    lv_obj_clean(tags_);
    const auto& spool = state.spool;
    const bool stale = spool && !entry.empty() && std::to_string(spool->id) != entry;
    lv_obj_set_style_opa(card_, static_cast<lv_opa_t>(stale ? LV_OPA_50 : LV_OPA_COVER), 0);

    if (!spool) {
        lv_obj_set_style_bg_color(swatch_, theme.surface_alt(), 0);
        ui::set_text(line1_, "NO SPOOL");
        ui::set_text(line2_, entry.empty() ? "Nothing looked up yet" : "Spool " + entry);
        ui::set_text(line3_, entry.empty() ? "Scan a spool, or type its ID and press " LV_SYMBOL_NEW_LINE
                                           : "Press " LV_SYMBOL_NEW_LINE " to look it up");
        ui::set_text(line4_, "");
        return;
    }
    if (!spool->found) {
        lv_obj_set_style_bg_color(swatch_, theme.surface_alt(), 0);
        ui::set_text(line1_, "SPOOL " + std::to_string(spool->id));
        ui::set_text(line2_, "Not found in Spoolman");
        ui::set_text(line3_, "Check the ID and try again");
        lv_obj_set_style_text_color(line4_, theme.error(), 0);
        ui::set_text(line4_, "");
        ui::chip(tags_, theme, "NOT FOUND", theme.error());
        return;
    }

    lv_obj_set_style_bg_color(swatch_, ui::swatch_color(spool->color, theme), 0);
    std::string head = "#" + std::to_string(spool->id);
    if (!spool->vendor.empty()) head += "  " + spool->vendor;
    const std::string used = local_date(spool->last_used);
    head += used.empty() ? "  |  never used" : "  |  used " + used;
    ui::set_text(line1_, head);
    std::string title = spool->name.empty() ? "Unnamed filament" : spool->name;
    if (!spool->material.empty() && title.find(spool->material) == std::string::npos) {
        title += "  " + spool->material;
    }
    ui::set_text(line2_, title);

    std::vector<std::string> facts;
    facts.push_back(fmt_grams(spool->remaining_g) + " left");
    facts.push_back(spool->spool_weight_g ? "tare " + fmt_grams(spool->spool_weight_g) : "tare unknown");
    if (!spool->location.empty()) facts.push_back(spool->location);
    ui::set_text(line3_, join(facts, "  |  "));
    lv_obj_set_style_text_color(line3_, spool->low_stock ? theme.warn() : theme.text(), 0);

    if (spool->low_stock) ui::chip(tags_, theme, "LOW", theme.warn());
    if (spool->archived) ui::chip(tags_, theme, "ARCHIVED", theme.muted());
    lv_obj_update_layout(tags_);
    const int32_t card_w = lv_obj_get_content_width(card_);
    const int32_t tags_w = lv_obj_get_child_count(tags_) ? lv_obj_get_width(tags_) + 8 : 0;
    lv_obj_set_width(line1_, card_w - lv_obj_get_x(line1_) - tags_w);

    const ScaleState& scale = state.scale;
    std::string warning;
    lv_color_t warning_color = theme.warn();
    if (stale) {
        warning = "Press " LV_SYMBOL_NEW_LINE " to look up spool " + entry;
        warning_color = theme.info();
    } else if (scale.check == "warn" && scale.delta_g && scale.expected_g) {
        warning = LV_SYMBOL_WARNING " Scale differs by " + fmt_delta(*scale.delta_g) + " from expected " +
                  fmt_grams(*scale.expected_g);
    } else if (scale.check == "ok" && scale.delta_g && scale.stable) {
        warning = LV_SYMBOL_OK " Scale matches expected (" + fmt_delta(*scale.delta_g) + ")";
        warning_color = theme.ok();
    } else if (scale.check == "tare_unknown" && scale.stable) {
        warning = LV_SYMBOL_WARNING " Tare unknown: weight cannot be checked";
    }
    lv_obj_set_style_text_color(line4_, warning_color, 0);
    ui::set_text(line4_, warning);
}

}  // namespace station

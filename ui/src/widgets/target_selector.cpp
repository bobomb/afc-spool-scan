#include "app.hpp"
#include "ui.hpp"

namespace station {

TargetSelector::TargetSelector(App& app, lv_obj_t* parent, int x, int y, int w, int h) : app_(app)
{
    Theme& theme = app.theme();
    lv_obj_t* caption = ui::label(parent, theme.small(), theme.muted(), "TARGET");
    lv_obj_set_pos(caption, x + 2, y + (h - 18) / 2);
    row_ = ui::container(parent);
    lv_obj_set_pos(row_, x + 72, y);
    lv_obj_set_size(row_, w - 72, h);
    lv_obj_set_flex_flow(row_, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(row_, 6, 0);
}

void TargetSelector::rebuild(const State& state)
{
    Theme& theme = app_.theme();
    lv_obj_clean(row_);
    options_.clear();
    keys_.clear();
    std::vector<std::pair<std::string, std::string>> choices;
    for (const Printer& printer : state.printers) {
        choices.emplace_back(printer.key, printer.name);
    }
    choices.emplace_back("both", state.printers.size() > 2 ? "All" : "Both");
    for (const auto& [key, name] : choices) {
        lv_obj_t* button = ui::button(row_, theme, "", ui::ButtonStyle::Segment);
        lv_obj_set_height(button, lv_pct(100));
        lv_obj_set_flex_grow(button, 1);
        lv_obj_t* title = ui::label(button, theme.small(), theme.text(), name);
        lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 4);
        lv_obj_t* detail = ui::label(button, theme.small(), theme.muted(), "");
        lv_obj_align(detail, LV_ALIGN_BOTTOM_MID, 0, -2);
        const std::string target = key;
        ui::on_click(button, [this, target] { app_.set_setting("target", target); });
        options_.push_back({key, button, title, detail});
        keys_.push_back(key);
    }
}

void TargetSelector::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    std::vector<std::string> keys;
    for (const Printer& printer : state.printers) keys.push_back(printer.key);
    keys.push_back("both");
    if (keys != keys_) {
        rebuild(state);
    }
    for (Option& option : options_) {
        ui::set_checked(option.button, option.key == state.settings.target);
        ui::set_disabled(option.button, !online);
        std::string detail;
        lv_color_t color = theme.muted();
        if (option.key == "both") {
            int pending = 0;
            for (const Printer& printer : state.printers) pending += printer.pending_spool.has_value();
            detail = pending ? std::to_string(pending) + " pending" : "all printers";
        } else if (const Printer* printer = app_.model().printer(option.key)) {
            if (!printer->connected) {
                detail = "offline";
                color = theme.error();
            } else if (printer->pending_spool) {
                detail = "next #" + std::to_string(*printer->pending_spool);
                color = theme.info();
            } else {
                detail = "no pending";
            }
        }
        lv_obj_set_style_text_color(option.detail, color, 0);
        ui::set_text(option.detail, detail);
    }
}

}  // namespace station

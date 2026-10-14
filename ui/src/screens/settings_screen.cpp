#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {
namespace {

double setting_value(const Settings& settings, const std::string& key)
{
    if (key == "sanity_threshold_g") return settings.sanity_threshold_g;
    if (key == "sanity_threshold_pct") return settings.sanity_threshold_pct;
    if (key == "low_stock_g") return settings.low_stock_g;
    if (key == "undo_depth") return settings.undo_depth;
    if (key == "idle_dim_s") return settings.idle_dim_s;
    if (key == "idle_off_s") return settings.idle_off_s;
    return 0;
}

std::string setting_text(const std::string& key, double value)
{
    const std::string number = fmt_number(value, value == static_cast<long long>(value) ? 0 : 1);
    if (key == "sanity_threshold_g" || key == "low_stock_g") return number + " g";
    if (key == "sanity_threshold_pct") return number + " %";
    if (key == "idle_dim_s" || key == "idle_off_s") return value <= 0 ? "never" : number + " s";
    return number;
}

const std::string& segment_value(const Settings& settings, const std::string& key)
{
    if (key == "scan_mode") return settings.scan_mode;
    if (key == "theme") return settings.theme;
    return settings.target;
}

}  // namespace

SettingsScreen::SettingsScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, 0, layout::kHeaderH);
    lv_obj_set_size(root_, layout::kWidth, layout::kBodyH);

    list_ = ui::panel(root_, theme);
    lv_obj_set_pos(list_, layout::kPad, 4);
    lv_obj_set_size(list_, layout::kWidth - 2 * layout::kPad, layout::kBodyH - 8);
    lv_obj_set_style_pad_all(list_, 6, 0);
    lv_obj_set_scrollable(list_, true);
    lv_obj_set_scroll_dir(list_, LV_DIR_VER);
    lv_obj_set_flex_flow(list_, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(list_, 4, 0);

    target_row_ = row("Target printer", "Used by Load, Weigh + Load and scans");
    add_segment("scan_mode", "Scan mode", "What a QR scan does",
                {{"immediate", "Immediate"}, {"countdown", "Countdown"}, {"fill", "Fill only"}});
    add_segment("theme", "Theme", "Display colours", {{"dark", "Dark"}, {"light", "Light"}});
    add_stepper("sanity_threshold_g", "Sanity check (grams)", "Confirm when the weight is off by more", 10, 0, 1000);
    add_stepper("sanity_threshold_pct", "Sanity check (percent)", "...or by this share of the expected weight", 1, 0,
                100);
    add_stepper("low_stock_g", "Low stock below", "Highlight spools and lanes", 25, 0, 5000);
    add_stepper("undo_depth", "Undo depth", "Recent actions that can be undone", 5, 1, 100);
    add_stepper("idle_dim_s", "Dim after", "Needs a software backlight", 30, 0, 3600);
    add_stepper("idle_off_s", "Screen off after", "Touch, scan or scale change wakes it", 60, 0, 7200);
    lv_obj_t* about = row("Service", "");
    service_ = ui::label(about, theme.small(), theme.muted(), "");
    lv_obj_align(service_, LV_ALIGN_RIGHT_MID, -10, 0);
}

lv_obj_t* SettingsScreen::row(const std::string& title, const std::string& hint)
{
    Theme& theme = app_.theme();
    lv_obj_t* row = ui::container(list_);
    lv_obj_set_size(row, layout::kWidth - 2 * layout::kPad - 12, 62);
    lv_obj_set_style_radius(row, 8, 0);
    lv_obj_set_style_bg_color(row, theme.surface_alt(), 0);
    lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);
    lv_obj_t* name = ui::label(row, theme.small(), theme.text(), title);
    lv_obj_set_pos(name, 12, hint.empty() ? 21 : 9);
    if (!hint.empty()) {
        lv_obj_t* detail = ui::label(row, theme.small(), theme.muted(), hint);
        lv_obj_set_pos(detail, 12, 33);
    }
    return row;
}

void SettingsScreen::add_segment(const std::string& key, const std::string& title, const std::string& hint,
                                 const std::vector<std::pair<std::string, std::string>>& options)
{
    Theme& theme = app_.theme();
    lv_obj_t* parent = row(title, hint);
    lv_obj_t* group = ui::container(parent);
    lv_obj_set_size(group, 390, 50);
    lv_obj_align(group, LV_ALIGN_RIGHT_MID, -6, 0);
    lv_obj_set_flex_flow(group, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(group, 6, 0);
    Segment segment{key, {}};
    for (const auto& [value, text] : options) {
        lv_obj_t* button = ui::button(group, theme, text, ui::ButtonStyle::Segment);
        lv_obj_set_height(button, 50);
        lv_obj_set_flex_grow(button, 1);
        const std::string setting = key;
        const std::string choice = value;
        ui::on_click(button, [this, setting, choice] { app_.set_setting(setting, choice); });
        segment.options.emplace_back(value, button);
    }
    segments_.push_back(std::move(segment));
}

void SettingsScreen::add_stepper(const std::string& key, const std::string& title, const std::string& hint,
                                 double step, double min, double max)
{
    Theme& theme = app_.theme();
    lv_obj_t* parent = row(title, hint);
    Stepper stepper{key, nullptr, nullptr, nullptr};
    stepper.plus = ui::button(parent, theme, LV_SYMBOL_PLUS, ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(stepper.plus, 64, 50);
    lv_obj_align(stepper.plus, LV_ALIGN_RIGHT_MID, -6, 0);
    stepper.value = ui::label(parent, theme.normal(), theme.text(), "");
    lv_obj_set_width(stepper.value, 120);
    lv_obj_set_style_text_align(stepper.value, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(stepper.value, LV_ALIGN_RIGHT_MID, -76, 0);
    stepper.minus = ui::button(parent, theme, LV_SYMBOL_MINUS, ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(stepper.minus, 64, 50);
    lv_obj_align(stepper.minus, LV_ALIGN_RIGHT_MID, -202, 0);
    auto change = [this, key, step, min, max](double direction) {
        const double current = setting_value(app_.state().settings, key);
        double next = current + direction * step;
        next = std::max(min, std::min(max, next));
        if (next != current) {
            app_.set_setting(key, next == static_cast<long long>(next) ? json(static_cast<long long>(next))
                                                                       : json(next));
        }
    };
    ui::on_click(stepper.minus, [change] { change(-1); });
    ui::on_click(stepper.plus, [change] { change(1); });
    steppers_.push_back(stepper);
}

void SettingsScreen::rebuild_targets(const State& state)
{
    lv_obj_t* group = lv_obj_get_child_count(target_row_) > 2 ? lv_obj_get_child(target_row_, -1) : nullptr;
    if (group != nullptr) {
        lv_obj_delete(group);
    }
    for (auto it = segments_.begin(); it != segments_.end(); ++it) {
        if (it->key == "target") {
            segments_.erase(it);
            break;
        }
    }
    Theme& theme = app_.theme();
    group = ui::container(target_row_);
    lv_obj_set_size(group, 390, 50);
    lv_obj_align(group, LV_ALIGN_RIGHT_MID, -6, 0);
    lv_obj_set_flex_flow(group, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(group, 6, 0);
    Segment segment{"target", {}};
    target_keys_.clear();
    std::vector<std::pair<std::string, std::string>> options;
    for (const Printer& printer : state.printers) options.emplace_back(printer.key, printer.name);
    options.emplace_back("both", "Both");
    for (const auto& [value, text] : options) {
        lv_obj_t* button = ui::button(group, theme, text, ui::ButtonStyle::Segment);
        lv_obj_set_height(button, 50);
        lv_obj_set_flex_grow(button, 1);
        const std::string choice = value;
        ui::on_click(button, [this, choice] { app_.set_setting("target", choice); });
        segment.options.emplace_back(value, button);
        target_keys_.push_back(value);
    }
    segments_.push_back(std::move(segment));
}

void SettingsScreen::update(const State& state, bool online)
{
    std::vector<std::string> keys;
    for (const Printer& printer : state.printers) keys.push_back(printer.key);
    keys.push_back("both");
    if (keys != target_keys_) {
        rebuild_targets(state);
    }
    for (Segment& segment : segments_) {
        const std::string& current = segment_value(state.settings, segment.key);
        for (auto& [value, button] : segment.options) {
            ui::set_checked(button, value == current);
            ui::set_disabled(button, !online);
        }
    }
    for (Stepper& stepper : steppers_) {
        const double value = setting_value(state.settings, stepper.key);
        ui::set_text(stepper.value, setting_text(stepper.key, value));
        ui::set_disabled(stepper.minus, !online);
        ui::set_disabled(stepper.plus, !online);
    }
    const ServiceInfo& service = state.service;
    std::string text = "v" + (service.version.empty() ? std::string("?") : service.version) + "  |  hardware " +
                       service.hardware + "  |  printers " + service.printers + "  |  writes " +
                       (service.dry_run ? "off (dry run)" : "on");
    ui::set_text(service_, text);
}

}  // namespace station

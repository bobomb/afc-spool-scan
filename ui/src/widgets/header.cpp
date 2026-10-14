#include "app.hpp"
#include "ui.hpp"

namespace station {

Header::Header(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    lv_obj_t* root = ui::container(parent);
    lv_obj_set_pos(root, 0, 0);
    lv_obj_set_size(root, layout::kWidth, layout::kHeaderH);
    lv_obj_set_style_bg_color(root, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root, LV_OPA_COVER, 0);
    lv_obj_set_style_border_side(root, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_width(root, 1, 0);
    lv_obj_set_style_border_color(root, theme.border(), 0);

    health_ = ui::container(root);
    lv_obj_set_pos(health_, 12, 0);
    lv_obj_set_size(health_, 420, layout::kHeaderH);
    lv_obj_set_flex_flow(health_, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(health_, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(health_, 6, 0);

    badge_ = ui::chip(health_, theme, "SIM", theme.info());

    const char* names[3] = {"Main", "Printers", "Log"};
    const ScreenId screens[3] = {ScreenId::Main, ScreenId::Printers, ScreenId::Log};
    for (int i = 0; i < 3; ++i) {
        tabs_[i] = ui::button(root, theme, names[i], ui::ButtonStyle::Segment);
        lv_obj_set_size(tabs_[i], 100, 44);
        lv_obj_set_pos(tabs_[i], 436 + i * 104, 6);
        const ScreenId target = screens[i];
        ui::on_click(tabs_[i], [this, target] { app_.show(target); });
    }
    gear_ = ui::button(root, theme, LV_SYMBOL_SETTINGS, ui::ButtonStyle::Segment, theme.normal());
    lv_obj_set_size(gear_, 44, 44);
    lv_obj_set_pos(gear_, 748, 6);
    ui::on_click(gear_, [this] { app_.show(ScreenId::Settings); });
}

void Header::rebuild_items(const std::vector<std::string>& names)
{
    Theme& theme = app_.theme();
    for (Item& item : items_) {
        lv_obj_delete(lv_obj_get_parent(item.dot));
    }
    items_.clear();
    for (const std::string& name : names) {
        lv_obj_t* group = ui::container(health_);
        lv_obj_set_size(group, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(group, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(group, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(group, 5, 0);
        lv_obj_set_style_pad_right(group, 6, 0);
        Item item{ui::dot(group, 10, theme.muted()), ui::label(group, theme.small(), theme.text(), name)};
        items_.push_back(item);
    }
    lv_obj_move_foreground(badge_);
    names_ = names;
}

void Header::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    std::vector<std::string> names = {"Spoolman"};
    for (const Printer& printer : state.printers) {
        names.push_back(printer.name);
    }
    names.push_back("Scale");
    const bool scanner_down = online && !state.health.scanner;
    if (scanner_down) {
        names.push_back("Scanner");
    }
    if (names != names_) {
        rebuild_items(names);
    }

    auto color_for = [&](std::size_t index) -> lv_color_t {
        if (!online) return theme.muted();
        if (index == 0) return state.health.spoolman ? theme.ok() : theme.error();
        if (index <= state.printers.size()) {
            const Printer& printer = state.printers[index - 1];
            if (!printer.connected) return theme.error();
            return printer.afc_error.empty() ? theme.ok() : theme.warn();
        }
        if (index == state.printers.size() + 1) {
            const std::string& status = state.scale.status;
            if (!state.scale.present || status == "fault" || status == "calibrate") return theme.error();
            if (status == "under" || status == "over" || status == "rezero") return theme.warn();
            return theme.ok();
        }
        return theme.error();
    };
    for (std::size_t i = 0; i < items_.size(); ++i) {
        lv_obj_set_style_bg_color(items_[i].dot, color_for(i), 0);
    }

    std::string badge;
    const ServiceInfo& service = state.service;
    if (service.dry_run) {
        badge = "DRY RUN";
    } else if (service.hardware == "sim" || service.printers == "sim" || service.spoolman == "sim") {
        badge = "SIM";
    }
    ui::set_hidden(badge_, !online || badge.empty());
    if (!badge.empty()) {
        ui::set_chip(badge_, badge, service.dry_run ? theme.warn() : theme.info());
    }
}

void Header::set_active(ScreenId screen)
{
    const ScreenId screens[3] = {ScreenId::Main, ScreenId::Printers, ScreenId::Log};
    for (int i = 0; i < 3; ++i) {
        ui::set_checked(tabs_[i], screens[i] == screen);
    }
    ui::set_checked(gear_, screen == ScreenId::Settings);
}

}  // namespace station

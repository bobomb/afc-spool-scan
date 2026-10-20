#include "app.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kItemW = 56;
constexpr int kItemH = 60;

}  // namespace

SideRail::SideRail(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    lv_obj_t* root = ui::container(parent);
    lv_obj_set_pos(root, 0, 0);
    lv_obj_set_size(root, layout::kRailW, layout::kHeight);
    lv_obj_set_style_bg_color(root, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root, LV_OPA_COVER, 0);

    struct Spec {
        ScreenId screen;
        const char* icon;
        const lv_font_t* font;
        const char* text;
        int y;
    };
    const Spec specs[] = {
        {ScreenId::Main, LV_SYMBOL_HOME, theme.normal(), "Station", 12},
        {ScreenId::Printers, STATION_SYMBOL_PRINTER, theme.icons(), "Printers", 80},
        {ScreenId::Log, LV_SYMBOL_LIST, theme.normal(), "Log", 148},
        {ScreenId::Settings, LV_SYMBOL_SETTINGS, theme.normal(), "Settings", layout::kHeight - kItemH - 12},
    };
    for (const Spec& spec : specs) {
        Item item{spec.screen, ui::container(root), nullptr, nullptr};
        lv_obj_set_pos(item.root, (layout::kRailW - kItemW) / 2, spec.y);
        lv_obj_set_size(item.root, kItemW, kItemH);
        lv_obj_set_style_radius(item.root, 14, 0);
        lv_obj_set_style_bg_color(item.root, theme.surface_alt(), LV_STATE_PRESSED);
        lv_obj_set_style_bg_opa(item.root, LV_OPA_COVER, LV_STATE_PRESSED);
        lv_obj_set_flex_flow(item.root, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(item.root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_row(item.root, 4, 0);
        item.icon = ui::label(item.root, spec.font, theme.muted(), spec.icon);
        item.text = ui::label(item.root, theme.tiny(), theme.muted(), spec.text);
        const ScreenId target = spec.screen;
        ui::on_click(item.root, [this, target] { app_.show(target); });
        items_.push_back(item);
    }

    badge_ = ui::label(root, theme.tiny(), theme.info(), "");
    lv_obj_set_width(badge_, layout::kRailW);
    lv_obj_set_style_text_align(badge_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(badge_, 0, 300);

    status_dot_ = ui::dot(root, 10, theme.muted());
    lv_obj_set_pos(status_dot_, (layout::kRailW - 10) / 2, 330);
    status_text_ = ui::label(root, theme.tiny(), theme.muted(), "");
    lv_obj_set_width(status_text_, layout::kRailW - 8);
    lv_obj_set_style_max_height(status_text_, 3 * lv_font_get_line_height(theme.tiny()), 0);
    lv_obj_set_style_text_align(status_text_, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(status_text_, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_pos(status_text_, 4, 346);
}

void SideRail::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    const HealthSummary summary = summarize_health(state, online);
    lv_color_t color = theme.ok();
    switch (summary.level) {
    case HealthSummary::Level::Ok:
        break;
    case HealthSummary::Level::Note:
        color = theme.muted();
        break;
    case HealthSummary::Level::Warn:
        color = theme.warn();
        break;
    case HealthSummary::Level::Error:
        color = theme.error();
        break;
    }
    lv_obj_set_style_bg_color(status_dot_, color, 0);
    lv_obj_set_style_text_color(status_text_, summary.level == HealthSummary::Level::Ok ? theme.muted() : color, 0);
    ui::set_text(status_text_, summary.text);

    std::string badge;
    const ServiceInfo& service = state.service;
    if (online && service.dry_run) {
        badge = "DRY RUN";
    } else if (online && (service.hardware == "sim" || service.printers == "sim" || service.spoolman == "sim")) {
        badge = "SIM";
    }
    ui::set_text(badge_, badge);
    lv_obj_set_style_text_color(badge_, service.dry_run ? theme.warn() : theme.info(), 0);
}

void SideRail::set_active(ScreenId screen)
{
    Theme& theme = app_.theme();
    for (Item& item : items_) {
        const bool active = item.screen == screen;
        lv_obj_set_style_bg_color(item.root, theme.primary(), 0);
        lv_obj_set_style_bg_opa(item.root, static_cast<lv_opa_t>(active ? LV_OPA_20 : LV_OPA_TRANSP), 0);
        lv_obj_set_style_text_color(item.icon, active ? theme.info() : theme.muted(), 0);
        lv_obj_set_style_text_color(item.text, active ? theme.text() : theme.muted(), 0);
    }
}

}  // namespace station

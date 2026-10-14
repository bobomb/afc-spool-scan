#include "app.hpp"
#include "ui.hpp"

namespace station {

ResultBanner::ResultBanner(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::panel(parent, theme);
    lv_obj_set_pos(root_, layout::kPad, layout::kHeight - layout::kBannerH + 2);
    lv_obj_set_size(root_, layout::kWidth - 2 * layout::kPad, layout::kBannerH - 8);
    lv_obj_set_style_pad_hor(root_, 12, 0);
    lv_obj_set_style_pad_ver(root_, 0, 0);
    lv_obj_set_style_radius(root_, 10, 0);

    icon_ = ui::label(root_, theme.normal(), theme.muted(), LV_SYMBOL_BELL);
    lv_obj_align(icon_, LV_ALIGN_LEFT_MID, 0, 0);
    text_ = ui::label(root_, theme.small(), theme.text(), "Ready");
    lv_obj_set_size(text_, layout::kWidth - 2 * layout::kPad - 24 - 40 - 110, 20);
    lv_label_set_long_mode(text_, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_align(text_, LV_ALIGN_LEFT_MID, 34, 0);
    undo_ = ui::button(root_, theme, LV_SYMBOL_LOOP "  Undo", ui::ButtonStyle::Normal);
    lv_obj_set_size(undo_, 104, 36);
    lv_obj_align(undo_, LV_ALIGN_RIGHT_MID, 4, 0);
    ui::on_click(undo_, [this] {
        if (!message_.activity_id.empty()) {
            app_.undo(message_.activity_id);
        }
    });
    ui::set_hidden(undo_, true);
}

void ResultBanner::show(const BannerMessage& message)
{
    Theme& theme = app_.theme();
    message_ = message;
    lv_color_t color = theme.muted();
    const char* symbol = LV_SYMBOL_BELL;
    switch (message.kind) {
    case BannerMessage::Kind::Ok:
        color = theme.ok();
        symbol = LV_SYMBOL_OK;
        break;
    case BannerMessage::Kind::Warn:
        color = theme.warn();
        symbol = LV_SYMBOL_WARNING;
        break;
    case BannerMessage::Kind::Error:
        color = theme.error();
        symbol = LV_SYMBOL_CLOSE;
        break;
    case BannerMessage::Kind::Info:
        color = theme.info();
        symbol = LV_SYMBOL_REFRESH;
        break;
    case BannerMessage::Kind::Idle:
        break;
    }
    lv_obj_set_style_text_color(icon_, color, 0);
    ui::set_text(icon_, symbol);
    lv_obj_set_style_border_color(root_, color, 0);
    lv_obj_set_style_bg_color(root_, lv_color_mix(color, theme.surface(), LV_OPA_10), 0);
    ui::set_text(text_, message.text);
    refresh(app_.state());
}

void ResultBanner::refresh(const State& state)
{
    bool undoable = false;
    if (!message_.activity_id.empty()) {
        for (const ActivityEntry& entry : state.activity) {
            if (entry.id == message_.activity_id) {
                undoable = entry.undoable && !entry.undone;
                break;
            }
        }
    }
    ui::set_hidden(undo_, !undoable);
    ui::set_disabled(undo_, !app_.online());
}

}  // namespace station

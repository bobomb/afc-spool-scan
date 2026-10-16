#include "app.hpp"
#include "ui.hpp"

namespace station {

ResultBanner::ResultBanner(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    const int width = layout::kContentW - 2 * layout::kMargin;
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, layout::kContentX + layout::kMargin, layout::kHeight - layout::kBannerH + 8);
    lv_obj_set_size(root_, width, layout::kBannerH - 16);
    lv_obj_set_style_bg_color(root_, theme.surface(), 0);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_left(root_, 14, 0);
    lv_obj_set_style_pad_right(root_, 4, 0);
    lv_obj_set_style_radius(root_, 12, 0);

    icon_ = ui::label(root_, theme.small(), theme.muted(), LV_SYMBOL_BELL);
    lv_obj_align(icon_, LV_ALIGN_LEFT_MID, 0, 0);
    text_ = ui::label(root_, theme.small(), theme.text(), "Ready");
    lv_obj_set_size(text_, width - 14 - 4 - 30 - 112, 20);
    lv_label_set_long_mode(text_, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_align(text_, LV_ALIGN_LEFT_MID, 30, 0);
    undo_ = ui::button(root_, theme, LV_SYMBOL_LOOP "  Undo", ui::ButtonStyle::Normal, theme.caption());
    lv_obj_set_size(undo_, 96, 32);
    lv_obj_align(undo_, LV_ALIGN_RIGHT_MID, 0, 0);
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
    const bool alert = message.kind == BannerMessage::Kind::Warn || message.kind == BannerMessage::Kind::Error;
    lv_obj_set_style_bg_color(root_, alert ? lv_color_mix(color, theme.surface(), LV_OPA_20) : theme.surface(), 0);
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

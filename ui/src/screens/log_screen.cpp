#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {

LogScreen::LogScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, layout::kContentX, 0);
    lv_obj_set_size(root_, layout::kContentW, layout::kBodyH);

    lv_obj_t* title = ui::label(root_, theme.normal(), theme.text(), "Recent activity");
    lv_obj_set_pos(title, layout::kMargin + 4, 14);
    count_ = ui::label(root_, theme.small(), theme.muted(), "");
    lv_obj_align(count_, LV_ALIGN_TOP_RIGHT, -layout::kMargin - 4, 18);

    list_ = ui::panel(root_, theme);
    lv_obj_set_pos(list_, layout::kMargin, 50);
    lv_obj_set_size(list_, layout::kContentW - 2 * layout::kMargin, layout::kBodyH - 54);
    lv_obj_set_style_pad_all(list_, 6, 0);
    lv_obj_set_scrollable(list_, true);
    lv_obj_set_scroll_dir(list_, LV_DIR_VER);
    lv_obj_set_flex_flow(list_, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(list_, 4, 0);

    empty_ = ui::label(root_, theme.normal(), theme.muted(), "Nothing yet. Weigh, load or scan a spool.");
    lv_obj_center(empty_);
}

void LogScreen::update(const State& state, bool online)
{
    Theme& theme = app_.theme();
    lv_obj_clean(list_);
    ui::set_hidden(empty_, !state.activity.empty());
    ui::set_hidden(list_, state.activity.empty());
    int undoable = 0;
    const int row_w = layout::kContentW - 2 * layout::kMargin - 12;
    for (const ActivityEntry& entry : state.activity) {
        undoable += entry.undoable && !entry.undone;
        lv_obj_t* row = ui::container(list_);
        lv_obj_set_size(row, row_w, 58);
        lv_obj_set_style_radius(row, 8, 0);
        lv_obj_set_style_bg_color(row, theme.surface_alt(), 0);
        lv_obj_set_style_bg_opa(row, LV_OPA_COVER, 0);

        lv_color_t color = entry.undone ? theme.muted() : entry.dry_run ? theme.warn()
                                         : entry.ok ? theme.ok() : theme.error();
        lv_obj_t* marker = ui::container(row);
        lv_obj_set_size(marker, 5, 42);
        lv_obj_align(marker, LV_ALIGN_LEFT_MID, 6, 0);
        lv_obj_set_style_radius(marker, 2, 0);
        lv_obj_set_style_bg_opa(marker, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(marker, color, 0);

        lv_obj_t* time = ui::label(row, theme.small(), theme.muted(), local_time_of_day(entry.at));
        lv_obj_set_pos(time, 20, 7);
        std::string title = action_label(entry.action);
        if (entry.spool_id) title += "  #" + std::to_string(*entry.spool_id);
        if (!entry.printers.empty()) title += "  " + join(entry.printers, ", ");
        lv_obj_t* head = ui::label(row, theme.small(), theme.text(), title);
        lv_obj_set_pos(head, 110, 7);
        lv_obj_t* message = ui::label(row, theme.small(), entry.ok ? theme.muted() : theme.error(), entry.message);
        lv_obj_set_pos(message, 110, 31);
        lv_obj_set_size(message, row_w - 110 - 130, 20);
        lv_label_set_long_mode(message, LV_LABEL_LONG_MODE_DOTS);

        if (entry.undone || entry.dry_run) {
            lv_obj_t* tag = ui::chip(row, theme, entry.undone ? "UNDONE" : "DRY RUN",
                                     entry.undone ? theme.muted() : theme.warn());
            lv_obj_align(tag, LV_ALIGN_RIGHT_MID, -12, 0);
        } else if (entry.undoable) {
            lv_obj_t* undo = ui::button(row, theme, LV_SYMBOL_LOOP "  Undo", ui::ButtonStyle::Normal);
            lv_obj_set_size(undo, 112, 44);
            lv_obj_align(undo, LV_ALIGN_RIGHT_MID, -6, 0);
            ui::set_disabled(undo, !online);
            const std::string id = entry.id;
            ui::on_click(undo, [this, id] { app_.undo(id); });
        }
    }
    ui::set_text(count_, std::to_string(state.activity.size()) + " entries  |  " + std::to_string(undoable) +
                             " undoable");
}

}  // namespace station

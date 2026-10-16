#include "app.hpp"
#include "ui.hpp"

namespace station {
namespace {

constexpr int kMenuX = layout::kContentX + layout::kMargin;
constexpr int kMenuW = 272;
constexpr int kRowH = 64;
constexpr int kMenuBottom = 352;

lv_obj_t* menu_row(lv_obj_t* menu, Theme& theme, int y, const std::string& title, lv_color_t color,
                   const std::string& detail)
{
    lv_obj_t* row = ui::container(menu);
    lv_obj_set_pos(row, 0, y);
    lv_obj_set_size(row, kMenuW, kRowH);
    lv_obj_set_style_radius(row, 16, 0);
    lv_obj_set_style_bg_color(row, theme.border(), LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(row, LV_OPA_COVER, LV_STATE_PRESSED);
    lv_obj_t* name = ui::label(row, theme.medium(), color, title);
    lv_obj_set_pos(name, 16, 10);
    lv_obj_t* hint = ui::label(row, theme.caption(), theme.muted(), detail);
    lv_obj_set_pos(hint, 16, 36);
    return row;
}

}  // namespace

void MoreMenu::show(int spool_id)
{
    if (catcher_ != nullptr) {
        return;
    }
    Theme& theme = app_.theme();
    catcher_ = ui::container(lv_layer_top());
    lv_obj_set_size(catcher_, layout::kWidth, layout::kHeight);
    ui::on_click(catcher_, [this] { close(); });

    lv_obj_t* menu = ui::container(catcher_);
    lv_obj_set_pos(menu, kMenuX, kMenuBottom - 2 * kRowH);
    lv_obj_set_size(menu, kMenuW, 2 * kRowH);
    lv_obj_set_style_radius(menu, 16, 0);
    lv_obj_set_style_bg_color(menu, theme.surface_alt(), 0);
    lv_obj_set_style_bg_opa(menu, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(menu, 1, 0);
    lv_obj_set_style_border_color(menu, theme.border(), 0);
    lv_obj_set_style_shadow_width(menu, 24, 0);
    lv_obj_set_style_shadow_opa(menu, LV_OPA_50, 0);
    lv_obj_set_style_shadow_color(menu, lv_color_black(), 0);
    lv_obj_set_clickable(menu, true);

    const std::string id = "#" + std::to_string(spool_id);
    lv_obj_t* assign = menu_row(menu, theme, 0, "Assign to lane...", theme.text(), "Pick a printer lane for " + id);
    ui::on_click(assign, [this] {
        close();
        app_.open_assign();
    });
    lv_obj_t* divider = ui::container(menu);
    lv_obj_set_pos(divider, 16, kRowH);
    lv_obj_set_size(divider, kMenuW - 32, 1);
    lv_obj_set_style_bg_color(divider, theme.border(), 0);
    lv_obj_set_style_bg_opa(divider, LV_OPA_COVER, 0);
    lv_obj_t* empty = menu_row(menu, theme, kRowH, "Record empty spool", theme.error(),
                               "Weigh the core, then archive " + id);
    ui::on_click(empty, [this] {
        close();
        app_.empty_spool();
    });
}

void MoreMenu::close()
{
    if (catcher_ != nullptr) {
        lv_obj_delete_async(catcher_);
        catcher_ = nullptr;
    }
}

}  // namespace station

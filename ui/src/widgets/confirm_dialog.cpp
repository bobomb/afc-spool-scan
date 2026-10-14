#include "app.hpp"
#include "ui.hpp"

namespace station {

void ConfirmDialog::show(Spec spec)
{
    close();
    spec_ = std::move(spec);
    Theme& theme = app_.theme();
    const int rows = static_cast<int>(spec_.rows.size());
    const int height = 170 + rows * 28 + (spec_.message.empty() ? 0 : 56);
    lv_obj_t* dialog = ui::modal(lv_layer_top(), theme, 560, std::min(height, 440), &dimmer_);

    lv_obj_t* title = ui::label(dialog, theme.normal(), spec_.danger ? theme.error() : theme.text(), spec_.title);
    lv_obj_set_size(title, 528, 28);
    lv_label_set_long_mode(title, LV_LABEL_LONG_MODE_DOTS);
    int y = 38;
    if (!spec_.message.empty()) {
        lv_obj_t* message = ui::label(dialog, theme.small(), theme.muted(), spec_.message);
        lv_obj_set_pos(message, 0, y);
        lv_obj_set_width(message, 528);
        lv_label_set_long_mode(message, LV_LABEL_LONG_MODE_WRAP);
        y += 56;
    }
    for (const auto& [name, value] : spec_.rows) {
        lv_obj_t* left = ui::label(dialog, theme.small(), theme.muted(), name);
        lv_obj_set_pos(left, 0, y);
        lv_obj_t* right = ui::label(dialog, theme.normal(), theme.text(), value);
        lv_obj_set_pos(right, 220, y - 3);
        y += 28;
    }

    lv_obj_t* cancel = ui::button(dialog, theme, spec_.cancel_text, ui::ButtonStyle::Normal, theme.normal());
    lv_obj_set_size(cancel, 200, 60);
    lv_obj_align(cancel, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_obj_t* confirm = ui::button(dialog, theme, spec_.confirm_text,
                                   spec_.danger ? ui::ButtonStyle::Danger : ui::ButtonStyle::Primary, theme.normal());
    lv_obj_set_size(confirm, 300, 60);
    lv_obj_align(confirm, LV_ALIGN_BOTTOM_RIGHT, 0, 0);

    ui::on_click(cancel, [this] {
        auto callback = spec_.on_cancel;
        close();
        if (callback) callback();
    });
    ui::on_click(confirm, [this] {
        auto callback = spec_.on_confirm;
        close();
        if (callback) callback();
    });
}

void ConfirmDialog::close()
{
    if (dimmer_ != nullptr) {
        lv_obj_delete_async(dimmer_);
        dimmer_ = nullptr;
    }
    spec_.key.clear();
}

}  // namespace station

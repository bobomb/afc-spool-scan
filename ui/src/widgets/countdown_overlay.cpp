#include "app.hpp"
#include "format.hpp"
#include "ui.hpp"

namespace station {

void CountdownOverlay::update(const State& state, bool online)
{
    const auto& countdown = state.scan.countdown;
    if (!online || !countdown) {
        close();
        return;
    }
    Theme& theme = app_.theme();
    if (dimmer_ == nullptr) {
        lv_obj_t* dialog = ui::modal(lv_layer_top(), theme, 440, 300, &dimmer_);
        lv_obj_t* title = ui::label(dialog, theme.normal(), theme.text(), "");
        lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_set_user_data(dimmer_, title);
        number_ = ui::label(dialog, theme.huge(), theme.primary(), "");
        lv_obj_align(number_, LV_ALIGN_TOP_MID, 0, 40);
        detail_ = ui::label(dialog, theme.small(), theme.muted(), "");
        lv_obj_align(detail_, LV_ALIGN_TOP_MID, 0, 112);
        lv_obj_t* cancel = ui::button(dialog, theme, LV_SYMBOL_CLOSE "  Cancel", ui::ButtonStyle::Danger, theme.normal());
        lv_obj_set_size(cancel, 400, 64);
        lv_obj_align(cancel, LV_ALIGN_BOTTOM_MID, 0, 0);
        ui::on_click(cancel, [this] { app_.cancel_countdown(); });
    }
    auto* title = static_cast<lv_obj_t*>(lv_obj_get_user_data(dimmer_));
    ui::set_text(title, action_label(countdown->action) + "  spool #" + std::to_string(countdown->spool_id));
    ui::set_text(number_, std::to_string(countdown->remaining_s));
    ui::set_text(detail_, "Starting in " + std::to_string(countdown->remaining_s) + " s unless cancelled");
}

void CountdownOverlay::close()
{
    if (dimmer_ != nullptr) {
        lv_obj_delete_async(dimmer_);
        dimmer_ = nullptr;
        number_ = nullptr;
        detail_ = nullptr;
    }
}

}  // namespace station

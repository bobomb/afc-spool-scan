#include "app.hpp"
#include "ui.hpp"

namespace station {

PrintersScreen::PrintersScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, 0, layout::kHeaderH);
    lv_obj_set_size(root_, layout::kWidth, layout::kBodyH);
    empty_ = ui::label(root_, theme.normal(), theme.muted(), "No printers configured");
    lv_obj_center(empty_);
}

void PrintersScreen::update(const State& state, bool online)
{
    const std::size_t count = std::min<std::size_t>(state.printers.size(), 2);
    if (cards_.size() != count) {
        cards_.clear();
        for (lv_obj_t* child = lv_obj_get_child(root_, -1); child != nullptr && child != empty_;
             child = lv_obj_get_child(root_, -1)) {
            lv_obj_delete(child);
        }
        const int gap = layout::kPad;
        const int width = count == 1 ? layout::kWidth - 2 * gap : (layout::kWidth - 3 * gap) / 2;
        for (std::size_t i = 0; i < count; ++i) {
            cards_.push_back(std::make_unique<PrinterCard>(app_, root_, gap + static_cast<int>(i) * (width + gap), 4,
                                                           width, layout::kBodyH - 8));
        }
    }
    ui::set_hidden(empty_, count != 0);
    for (std::size_t i = 0; i < count; ++i) {
        cards_[i]->update(state.printers[i], state.settings, online);
    }
}

}  // namespace station

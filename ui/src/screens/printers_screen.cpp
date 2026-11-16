#include "app.hpp"
#include "ui.hpp"

namespace station {

PrintersScreen::PrintersScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, layout::kContentX, 0);
    lv_obj_set_size(root_, layout::kContentW, layout::kBodyH);
    empty_ = ui::label(root_, theme.normal(), theme.muted(), "No printers configured");
    lv_obj_center(empty_);
}

void PrintersScreen::update(const State& state, bool online)
{
    const std::size_t count = std::min<std::size_t>(state.printers.size(), 3);
    if (cards_.size() != count) {
        // Delete the widgets before the cards: slot cells' gradients live in the cards.
        for (lv_obj_t* child = lv_obj_get_child(root_, -1); child != nullptr && child != empty_;
             child = lv_obj_get_child(root_, -1)) {
            lv_obj_delete(child);
        }
        cards_.clear();
        const int margin = layout::kMargin;
        const int gap = layout::kPad;
        const int inner = layout::kContentW - 2 * margin;
        const int columns = static_cast<int>(std::max<std::size_t>(count, 1));
        const int width = (inner - (columns - 1) * gap) / columns;
        for (std::size_t i = 0; i < count; ++i) {
            cards_.push_back(std::make_unique<PrinterCard>(app_, root_, margin + static_cast<int>(i) * (width + gap),
                                                           12, width, layout::kBodyH - 16));
        }
    }
    ui::set_hidden(empty_, count != 0);
    for (std::size_t i = 0; i < count; ++i) {
        cards_[i]->update(state.printers[i], state.settings, online);
    }
}

}  // namespace station

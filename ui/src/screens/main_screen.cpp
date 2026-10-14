#include "app.hpp"
#include "ui.hpp"

namespace station {

MainScreen::MainScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, 0, layout::kHeaderH);
    lv_obj_set_size(root_, layout::kWidth, layout::kBodyH);

    const int left_x = layout::kPad;
    const int left_w = 292;
    const int right_x = left_x + left_w + layout::kPad;
    const int right_w = layout::kWidth - right_x - layout::kPad;

    scale_ = std::make_unique<ScaleTile>(app, root_, left_x, 4, left_w, 100);
    numpad_ = std::make_unique<Numpad>(app, root_, left_x, 110, left_w, 258);
    card_ = std::make_unique<SpoolCard>(app, root_, right_x, 4, right_w);
    target_ = std::make_unique<TargetSelector>(app, root_, right_x, 182, right_w, 58);

    struct Spec {
        const char* text;
        ui::ButtonStyle style;
        int x;
        int y;
        int w;
        int h;
        std::function<void()> action;
    };
    const int row1 = 246;
    const int row2 = 312;
    const int gap = 6;
    const int half = (right_w - gap) / 2;
    const Spec specs[] = {
        {"WEIGH", ui::ButtonStyle::Normal, right_x, row1, 150, 60, [this] { app_.weigh(); }},
        {"WEIGH + LOAD", ui::ButtonStyle::Primary, right_x + 150 + gap, row1, 180, 60, [this] { app_.weigh_load(); }},
        {"LOAD", ui::ButtonStyle::Normal, right_x + 336 + gap, row1, right_w - 336 - gap, 60, [this] { app_.load(); }},
        {"Assign lane...", ui::ButtonStyle::Normal, right_x, row2, half, 56, [this] { app_.open_assign(); }},
        {"Empty spool", ui::ButtonStyle::Normal, right_x + half + gap, row2, half, 56, [this] { app_.empty_spool(); }},
    };
    for (const Spec& spec : specs) {
        lv_obj_t* button = ui::button(root_, theme, spec.text, spec.style, theme.normal());
        lv_obj_set_pos(button, spec.x, spec.y);
        lv_obj_set_size(button, spec.w, spec.h);
        ui::on_click(button, spec.action);
        actions_.push_back(button);
    }
}

void MainScreen::update(const State& state, std::uint32_t topics, bool online, const std::string& entry)
{
    if (topics & (kTopicScale | kTopicConnection | kTopicService)) {
        scale_->update(state, online);
    }
    card_->update(state, entry);
    if (topics & (kTopicPrinters | kTopicSettings | kTopicConnection | kTopicService)) {
        target_->update(state, online);
    }
    const auto id = app_.spool_id();
    const bool known_missing = id && state.spool && !state.spool->found && state.spool->id == *id;
    const bool has_id = id.has_value() && !known_missing;
    for (std::size_t i = 0; i < actions_.size(); ++i) {
        const bool needs_id = i != 3;
        ui::set_disabled(actions_[i], !online || (needs_id && !has_id));
    }
}

}  // namespace station

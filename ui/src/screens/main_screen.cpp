#include <cstdint>

#include "app.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kHeroY = 12;
constexpr int kHeroH = 128;
constexpr int kGap = 8;
constexpr int kCardsY = kHeroY + kHeroH + kGap;
constexpr int kBarH = 46;
constexpr int kBarY = layout::kBodyH - kBarH;
constexpr int kCardH = kBarY - kGap - kCardsY;
constexpr std::size_t kMaxCards = 2;
constexpr std::size_t kMaxLanes = 4;
constexpr int kRowH = (kCardH - kGap) / 2;

struct Slot {
    std::size_t printer;
    int x;
    int y;
    int w;
    int h;
};

// Two rows: printers with up to four lanes pair up side by side (in PRINTERS order, wherever they are
// listed), others take a full row; rows follow the order of their first printer.
std::vector<Slot> compact_layout(const std::vector<Printer>& printers, int x, int w)
{
    std::vector<std::vector<std::size_t>> rows;
    std::size_t open = SIZE_MAX;
    for (std::size_t i = 0; i < printers.size(); ++i) {
        if (printers[i].lanes.size() > kMaxLanes) {
            rows.push_back({i});
        } else if (open != SIZE_MAX) {
            rows[open].push_back(i);
            open = SIZE_MAX;
        } else {
            open = rows.size();
            rows.push_back({i});
        }
    }
    std::vector<Slot> slots;
    const int half = (w - 2 * kGap) / 2;
    for (std::size_t r = 0; r < rows.size() && r < 2; ++r) {
        const int y = kCardsY + static_cast<int>(r) * (kRowH + kGap);
        if (rows[r].size() == 2) {
            slots.push_back({rows[r][0], x, y, half, kRowH});
            slots.push_back({rows[r][1], x + half + 2 * kGap, y, half, kRowH});
        } else {
            const bool small = printers[rows[r][0]].lanes.size() <= kMaxLanes;
            slots.push_back({rows[r][0], x, y, small && printers.size() > 1 ? half : w, kRowH});
        }
    }
    return slots;
}

}  // namespace

MainScreen::MainScreen(App& app, lv_obj_t* parent) : app_(app)
{
    Theme& theme = app.theme();
    root_ = ui::container(parent);
    lv_obj_set_pos(root_, layout::kContentX, 0);
    lv_obj_set_size(root_, layout::kContentW, layout::kBodyH);
    const int x = layout::kMargin;
    const int w = layout::kContentW - 2 * layout::kMargin;

    hero_ = std::make_unique<SpoolHero>(app, root_, x, kHeroY, w, kHeroH);

    no_printers_ = ui::label(root_, theme.normal(), theme.muted(), "No printers configured");
    lv_obj_set_pos(no_printers_, x, kCardsY + 70);

    const int more_w = 96;
    more_ = ui::button(root_, theme, "More", ui::ButtonStyle::Ghost, theme.medium());
    lv_obj_set_size(more_, more_w, kBarH);
    lv_obj_set_pos(more_, x, kBarY);
    ui::on_click(more_, [this] { app_.open_more(); });

    // What the next scan does; the service resets it to Weigh + Load when the station sleeps.
    const int caption_x = x + more_w + kGap;
    const int caption_w = 76;
    lv_obj_t* caption = ui::container(root_);
    lv_obj_set_pos(caption, caption_x, kBarY);
    lv_obj_set_size(caption, caption_w, kBarH);
    lv_obj_center(ui::label(caption, theme.caption(), theme.muted(), "ON SCAN"));
    const int segments_x = caption_x + caption_w;
    const int segment_w = (x + w - segments_x - 2 * kGap) / 3;
    const std::pair<const char*, const char*> actions[] = {
        {"weigh", "Weigh"}, {"load", "Load"}, {"weigh_load", "Weigh + Load"}};
    for (int i = 0; i < 3; ++i) {
        lv_obj_t* button = ui::button(root_, theme, actions[i].second, ui::ButtonStyle::Segment, theme.medium());
        lv_obj_set_size(button, segment_w, kBarH);
        lv_obj_set_pos(button, segments_x + i * (segment_w + kGap), kBarY);
        const std::string value = actions[i].first;
        ui::on_click(button, [this, value] { app_.set_scan_action(value); });
        scan_actions_.emplace_back(value, button);
    }
}

void MainScreen::update(const State& state, std::uint32_t topics, bool online)
{
    hero_->update(state, online);

    const auto& printers = state.printers;
    bool compact = printers.size() > kMaxCards;
    std::string key = std::to_string(printers.size());
    for (const Printer& printer : printers) {
        compact = compact || printer.lanes.size() > kMaxLanes;
        key += printer.lanes.size() > kMaxLanes ? "L" : "s";
    }
    if (!compact) key = std::to_string(printers.size());
    const bool rebuilt = key != layout_key_;
    if (rebuilt) {
        layout_key_ = key;
        for (const auto& card : cards_) lv_obj_delete(card->root());
        for (const auto& card : compact_) lv_obj_delete(card->root());
        cards_.clear();
        compact_.clear();
        shown_.clear();
        const int x = layout::kMargin;
        const int w = layout::kContentW - 2 * layout::kMargin;
        if (compact) {
            for (const Slot& slot : compact_layout(printers, x, w)) {
                compact_.push_back(std::make_unique<CompactCard>(app_, root_, slot.x, slot.y, slot.w, slot.h));
                shown_.push_back(slot.printer);
            }
        } else {
            const std::size_t count = printers.size();
            const int card_w = count <= 1 ? w : (w - 2 * kGap) / 2;
            for (std::size_t i = 0; i < count; ++i) {
                cards_.push_back(std::make_unique<TargetCard>(
                    app_, root_, x + static_cast<int>(i) * (card_w + 2 * kGap), kCardsY, card_w, kCardH));
                shown_.push_back(i);
            }
        }
    }
    ui::set_hidden(no_printers_, !shown_.empty());
    if (rebuilt || (topics & (kTopicPrinters | kTopicConnection | kTopicService))) {
        for (std::size_t i = 0; i < shown_.size(); ++i) {
            const Printer& printer = printers[shown_[i]];
            if (compact) compact_[i]->update(printer, online);
            else cards_[i]->update(printer, online);
        }
    }

    const bool has_spool = online && app_.spool_id().has_value();
    ui::set_disabled(more_, !has_spool);
    for (const auto& [value, button] : scan_actions_) {
        ui::set_checked(button, value == state.scan.action);
        ui::set_disabled(button, !online);
    }
}

}  // namespace station

#include <cstdint>

#include "app.hpp"
#include "ui.hpp"
#include "view_model.hpp"

namespace station {
namespace {

constexpr int kHeroY = 12;
constexpr int kHeroH = 128;
constexpr int kLabelY = 150;
constexpr int kCardsY = 174;
constexpr int kCardH = 178;
constexpr int kBarY = 364;
constexpr int kBarH = 60;
constexpr int kGap = 8;
constexpr std::size_t kMaxCards = 2;
constexpr std::size_t kMaxLanes = 4;
constexpr int kRowH = 85;

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

    targets_label_ = ui::container(root_);
    lv_obj_set_pos(targets_label_, x, kLabelY);
    lv_obj_set_size(targets_label_, w, 20);
    lv_obj_set_flex_flow(targets_label_, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(targets_label_, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(targets_label_, 10, 0);
    lv_obj_t* cap = ui::label(targets_label_, theme.caption(), theme.muted(), "PRINTERS");
    lv_obj_set_style_text_letter_space(cap, 1, 0);
    targets_hint_ = ui::label(targets_label_, theme.caption(), theme.muted(), "");
    no_printers_ = ui::label(root_, theme.normal(), theme.muted(), "No printers configured");
    lv_obj_set_pos(no_printers_, x, kCardsY + 70);

    const int more_w = 96;
    const int button_w = 150;
    more_ = ui::button(root_, theme, "More", ui::ButtonStyle::Ghost, theme.medium());
    lv_obj_set_size(more_, more_w, kBarH);
    lv_obj_set_pos(more_, x, kBarY);
    ui::on_click(more_, [this] { app_.open_more(); });
    weigh_ = ui::button(root_, theme, "Weigh", ui::ButtonStyle::Normal, theme.medium());
    lv_obj_set_size(weigh_, button_w, kBarH);
    lv_obj_set_pos(weigh_, x + more_w + kGap, kBarY);
    ui::on_click(weigh_, [this] { app_.weigh(); });
    load_ = ui::button(root_, theme, "Load", ui::ButtonStyle::Normal, theme.medium());
    lv_obj_set_size(load_, button_w, kBarH);
    lv_obj_set_pos(load_, x + more_w + button_w + 2 * kGap, kBarY);
    ui::on_click(load_, [this] { app_.load(); });
    const int primary_x = x + more_w + 2 * button_w + 3 * kGap;
    weigh_load_ = ui::button(root_, theme, "Weigh + Load", ui::ButtonStyle::Primary, theme.normal());
    lv_obj_set_size(weigh_load_, x + w - primary_x, kBarH);
    lv_obj_set_pos(weigh_load_, primary_x, kBarY);
    ui::on_click(weigh_load_, [this] { app_.weigh_load(); });
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
        ui::set_text(targets_hint_, printers.size() == 2 ? "\xE2\x80\xA2  Load sets the next spool on both"
                                                         : "\xE2\x80\xA2  Load sets the next spool on every printer");
    }
    ui::set_hidden(no_printers_, !shown_.empty());
    ui::set_hidden(targets_label_, shown_.empty());
    if (rebuilt || (topics & (kTopicPrinters | kTopicConnection | kTopicService))) {
        for (std::size_t i = 0; i < shown_.size(); ++i) {
            const Printer& printer = printers[shown_[i]];
            if (compact) compact_[i]->update(printer, online);
            else cards_[i]->update(printer, online);
        }
    }

    const bool has_spool = online && app_.spool_id().has_value();
    ui::set_disabled(more_, !has_spool);
    ui::set_disabled(weigh_, !has_spool);
    ui::set_disabled(load_, !has_spool);
    ui::set_disabled(weigh_load_, !has_spool);
}

}  // namespace station

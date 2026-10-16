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
    lv_obj_t* cap = ui::label(targets_label_, theme.caption(), theme.muted(), "LOAD TO");
    lv_obj_set_style_text_letter_space(cap, 1, 0);
    ui::label(targets_label_, theme.caption(), theme.muted(), "\xE2\x80\xA2  tap a printer to include or exclude it");
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

    const std::size_t count = std::min(state.printers.size(), kMaxCards);
    const bool rebuilt = cards_.size() != count;
    if (rebuilt) {
        for (const auto& card : cards_) {
            lv_obj_delete(card->root());
        }
        cards_.clear();
        const int x = layout::kMargin;
        const int w = layout::kContentW - 2 * layout::kMargin;
        const int card_w = count <= 1 ? w : (w - 2 * kGap) / 2;
        for (std::size_t i = 0; i < count; ++i) {
            cards_.push_back(std::make_unique<TargetCard>(app_, root_, x + static_cast<int>(i) * (card_w + 2 * kGap),
                                                          kCardsY, card_w, kCardH));
        }
    }
    ui::set_hidden(no_printers_, count != 0);
    ui::set_hidden(targets_label_, count == 0);
    if (rebuilt || (topics & (kTopicPrinters | kTopicSettings | kTopicConnection | kTopicService))) {
        std::vector<std::string> keys;
        for (const Printer& printer : state.printers) keys.push_back(printer.key);
        const std::vector<std::string> included = included_printers(state.settings.target, keys);
        for (std::size_t i = 0; i < count; ++i) {
            const Printer& printer = state.printers[i];
            const bool in = std::find(included.begin(), included.end(), printer.key) != included.end();
            cards_[i]->update(printer, in, online);
        }
    }

    const bool has_spool = online && app_.spool_id().has_value();
    ui::set_disabled(more_, !has_spool);
    ui::set_disabled(weigh_, !has_spool);
    ui::set_disabled(load_, !has_spool);
    ui::set_disabled(weigh_load_, !has_spool);
}

}  // namespace station

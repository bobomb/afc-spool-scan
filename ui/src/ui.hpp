#pragma once
// Widgets and screens of the touch UI. Each class has its own source file.

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "lvgl.h"
#include "model.hpp"
#include "theme.hpp"

namespace station {

class App;

enum class ScreenId { Main, Printers, Log, Settings };

namespace layout {
inline constexpr int kWidth = 800;
inline constexpr int kHeight = 480;
inline constexpr int kHeaderH = 56;
inline constexpr int kBannerH = 52;
inline constexpr int kBodyH = kHeight - kHeaderH - kBannerH;
inline constexpr int kPad = 8;
}  // namespace layout

namespace ui {

enum class ButtonStyle { Normal, Primary, Danger, Segment };

lv_obj_t* container(lv_obj_t* parent);
lv_obj_t* panel(lv_obj_t* parent, Theme& theme);
lv_obj_t* label(lv_obj_t* parent, const lv_font_t* font, lv_color_t color, const std::string& text = std::string());
lv_obj_t* button(lv_obj_t* parent, Theme& theme, const std::string& text, ButtonStyle style = ButtonStyle::Normal,
                 const lv_font_t* font = nullptr);
lv_obj_t* button_label(lv_obj_t* button);
lv_obj_t* dot(lv_obj_t* parent, int size, lv_color_t color);
lv_obj_t* chip(lv_obj_t* parent, Theme& theme, const std::string& text, lv_color_t color);
void set_chip(lv_obj_t* chip, const std::string& text, lv_color_t color);
void on_click(lv_obj_t* obj, std::function<void()> callback);
void set_text(lv_obj_t* label, const std::string& text);
void set_hidden(lv_obj_t* obj, bool hidden);
void set_disabled(lv_obj_t* obj, bool disabled);
void set_checked(lv_obj_t* obj, bool checked);
// Full-screen dimmer on `layer` with a centered dialog panel; returns the panel.
lv_obj_t* modal(lv_obj_t* layer, Theme& theme, int width, int height, lv_obj_t** dimmer);
lv_color_t swatch_color(const std::string& hex, Theme& theme);

}  // namespace ui

struct BannerMessage {
    enum class Kind { Idle, Info, Ok, Warn, Error };
    Kind kind = Kind::Info;
    std::string text;
    std::string activity_id;
};

class Header {
public:
    Header(App& app, lv_obj_t* parent);
    void update(const State& state, bool online);
    void set_active(ScreenId screen);

private:
    struct Item {
        lv_obj_t* dot;
        lv_obj_t* label;
    };
    void rebuild_items(const std::vector<std::string>& names);

    App& app_;
    lv_obj_t* health_ = nullptr;
    lv_obj_t* badge_ = nullptr;
    lv_obj_t* tabs_[3] = {};
    lv_obj_t* gear_ = nullptr;
    std::vector<std::string> names_;
    std::vector<Item> items_;
};

class ScaleTile {
public:
    ScaleTile(App& app, lv_obj_t* parent, int x, int y, int w, int h);
    void update(const State& state, bool online);

private:
    App& app_;
    lv_obj_t* chip_ = nullptr;
    lv_obj_t* weight_ = nullptr;
    lv_obj_t* unit_ = nullptr;
    lv_obj_t* detail_ = nullptr;
};

class Numpad {
public:
    Numpad(App& app, lv_obj_t* parent, int x, int y, int w, int h);

private:
    static void on_event(lv_event_t* e);
    App& app_;
    lv_obj_t* matrix_ = nullptr;
};

class SpoolCard {
public:
    SpoolCard(App& app, lv_obj_t* parent, int x, int y, int w);
    void update(const State& state, const std::string& entry);
    static constexpr int kEntryH = 56;
    static constexpr int kCardH = 110;

private:
    App& app_;
    lv_obj_t* digits_ = nullptr;
    lv_obj_t* placeholder_ = nullptr;
    lv_obj_t* backspace_ = nullptr;
    lv_obj_t* card_ = nullptr;
    lv_obj_t* swatch_ = nullptr;
    lv_obj_t* line1_ = nullptr;
    lv_obj_t* tags_ = nullptr;
    lv_obj_t* line2_ = nullptr;
    lv_obj_t* line3_ = nullptr;
    lv_obj_t* line4_ = nullptr;
};

class TargetSelector {
public:
    TargetSelector(App& app, lv_obj_t* parent, int x, int y, int w, int h);
    void update(const State& state, bool online);

private:
    struct Option {
        std::string key;
        lv_obj_t* button;
        lv_obj_t* title;
        lv_obj_t* detail;
    };
    void rebuild(const State& state);

    App& app_;
    lv_obj_t* row_ = nullptr;
    std::vector<Option> options_;
    std::vector<std::string> keys_;
};

class ResultBanner {
public:
    ResultBanner(App& app, lv_obj_t* parent);
    void show(const BannerMessage& message);
    void refresh(const State& state);

private:
    App& app_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* icon_ = nullptr;
    lv_obj_t* text_ = nullptr;
    lv_obj_t* undo_ = nullptr;
    BannerMessage message_;
};

class PrinterCard {
public:
    PrinterCard(App& app, lv_obj_t* parent, int x, int y, int w, int h);
    void update(const Printer& printer, const Settings& settings, bool online);

private:
    struct LaneRow {
        lv_obj_t* root;
        lv_obj_t* swatch;
        lv_obj_t* name;
        lv_obj_t* spool;
        lv_obj_t* weight;
        lv_obj_t* bar;
        lv_obj_t* status;
        lv_obj_t* low;
        std::string lane;
    };
    void build_lanes(std::size_t count);

    App& app_;
    std::string key_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* dot_ = nullptr;
    lv_obj_t* name_ = nullptr;
    lv_obj_t* print_ = nullptr;
    lv_obj_t* status_ = nullptr;
    lv_obj_t* pending_ = nullptr;
    lv_obj_t* clear_ = nullptr;
    lv_obj_t* lanes_box_ = nullptr;
    std::vector<LaneRow> lanes_;
    int width_ = 0;
};

class ConfirmDialog {
public:
    struct Spec {
        std::string key;
        std::string title;
        std::string message;
        std::vector<std::pair<std::string, std::string>> rows;
        std::string confirm_text = "Confirm";
        std::string cancel_text = "Cancel";
        bool danger = false;
        std::function<void()> on_confirm;
        std::function<void()> on_cancel;
    };
    explicit ConfirmDialog(App& app) : app_(app) {}
    void show(Spec spec);
    void close();
    bool open() const { return dimmer_ != nullptr; }
    const std::string& key() const { return spec_.key; }

private:
    App& app_;
    lv_obj_t* dimmer_ = nullptr;
    Spec spec_;
};

class AssignDialog {
public:
    explicit AssignDialog(App& app) : app_(app) {}
    void show(int spool_id, const std::string& printer, const std::string& lane);
    void close();
    bool open() const { return dimmer_ != nullptr; }
    void refresh(const State& state);

private:
    void build();
    void select_printer(const std::string& key);
    static void refresh_async(void* self);

    App& app_;
    lv_obj_t* dimmer_ = nullptr;
    lv_obj_t* printer_row_ = nullptr;
    lv_obj_t* lane_grid_ = nullptr;
    lv_obj_t* hint_ = nullptr;
    lv_obj_t* assign_ = nullptr;
    int spool_id_ = 0;
    std::string printer_;
    std::string lane_;
};

class CountdownOverlay {
public:
    explicit CountdownOverlay(App& app) : app_(app) {}
    void update(const State& state, bool online);
    void close();

private:
    App& app_;
    lv_obj_t* dimmer_ = nullptr;
    lv_obj_t* number_ = nullptr;
    lv_obj_t* detail_ = nullptr;
};

class StatusOverlay {
public:
    explicit StatusOverlay(App& app) : app_(app) {}
    void set_offline(bool offline, const std::string& text);
    void set_blank(bool blank);
    void reset();

private:
    App& app_;
    lv_obj_t* offline_ = nullptr;
    lv_obj_t* offline_text_ = nullptr;
    lv_obj_t* blank_ = nullptr;
};

class MainScreen {
public:
    MainScreen(App& app, lv_obj_t* parent);
    void update(const State& state, std::uint32_t topics, bool online, const std::string& entry);
    lv_obj_t* root() const { return root_; }

private:
    App& app_;
    lv_obj_t* root_ = nullptr;
    std::unique_ptr<ScaleTile> scale_;
    std::unique_ptr<Numpad> numpad_;
    std::unique_ptr<SpoolCard> card_;
    std::unique_ptr<TargetSelector> target_;
    std::vector<lv_obj_t*> actions_;
};

class PrintersScreen {
public:
    PrintersScreen(App& app, lv_obj_t* parent);
    void update(const State& state, bool online);
    lv_obj_t* root() const { return root_; }

private:
    App& app_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* empty_ = nullptr;
    std::vector<std::unique_ptr<PrinterCard>> cards_;
};

class LogScreen {
public:
    LogScreen(App& app, lv_obj_t* parent);
    void update(const State& state, bool online);
    lv_obj_t* root() const { return root_; }

private:
    App& app_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* count_ = nullptr;
    lv_obj_t* list_ = nullptr;
    lv_obj_t* empty_ = nullptr;
};

class SettingsScreen {
public:
    SettingsScreen(App& app, lv_obj_t* parent);
    void update(const State& state, bool online);
    lv_obj_t* root() const { return root_; }

private:
    struct Segment {
        std::string key;
        std::vector<std::pair<std::string, lv_obj_t*>> options;
    };
    struct Stepper {
        std::string key;
        lv_obj_t* value;
        lv_obj_t* minus;
        lv_obj_t* plus;
    };
    lv_obj_t* row(const std::string& title, const std::string& hint);
    void add_segment(const std::string& key, const std::string& title, const std::string& hint,
                     const std::vector<std::pair<std::string, std::string>>& options);
    void add_stepper(const std::string& key, const std::string& title, const std::string& hint, double step,
                     double min, double max);
    void rebuild_targets(const State& state);

    App& app_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* list_ = nullptr;
    lv_obj_t* target_row_ = nullptr;
    lv_obj_t* service_ = nullptr;
    std::vector<Segment> segments_;
    std::vector<Stepper> steppers_;
    std::vector<std::string> target_keys_;
};

}  // namespace station

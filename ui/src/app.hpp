#pragma once
// Application controller: owns the model, IPC client and all widgets; implements UI flows.

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>

#include "idle.hpp"
#include "ipc_client.hpp"
#include "model.hpp"
#include "platform.hpp"
#include "theme.hpp"
#include "ui.hpp"

namespace station {

class App {
public:
    struct Options {
        std::string host = "127.0.0.1";
        std::uint16_t port = 7913;
        bool use_ipc = true;
        bool idle_enabled = true;
    };
    using ResultHandler = std::function<void(const Result&)>;

    App(Platform& platform, Options options);
    ~App();
    App(const App&) = delete;
    App& operator=(const App&) = delete;

    void start();
    // Loads a sample state file (snapshot mode): {"hello", "snapshot", "connected", "entry"}.
    void load_sample(const json& sample);
    void poll();

    const State& state() const { return model_.state(); }
    const Model& model() const { return model_; }
    Theme& theme() { return theme_; }
    Platform& platform() { return platform_; }
    IdleManager& idle() { return *idle_; }
    bool online() const;
    // False once the display (and with it every widget) has been deleted.
    bool alive() const { return !display_gone_; }

    void show(ScreenId screen);
    ScreenId screen() const { return screen_; }

    const std::string& entry() const { return entry_; }
    void entry_digit(char digit);
    void entry_backspace();
    void entry_clear();
    void entry_submit();
    void handle_key(const std::string& key);
    std::optional<int> spool_id() const;

    void weigh(bool confirm = false);
    void weigh_load(bool confirm = false);
    void load();
    void empty_spool();
    void open_assign(std::string printer = std::string(), std::string lane = std::string());
    void assign(int spool_id, const std::string& printer, const std::string& lane);
    // By value: callers often pass strings owned by widgets that this call updates.
    void clear_pending(std::string printer);
    void undo(std::string activity_id);
    void set_setting(const std::string& key, const json& value);
    void cancel_countdown();
    void request(const std::string& action, const json& args, ResultHandler done = {});
    void banner(BannerMessage message);
    void set_blank(bool blank);

private:
    void build_ui();
    void destroy_ui();
    static void rebuild_async(void* self);
    // The Windows driver deletes the display (and every widget) when the window closes;
    // after that nothing may touch LVGL objects until the driver exits the process.
    static void on_display_deleted(lv_event_t* e);
    void on_line(const std::string& line);
    void on_connection(bool connected);
    void refresh(std::uint32_t topics);
    void show_result(const Result& result);
    void confirm_weight(const Result& result, std::function<void()> on_confirm);
    void request_empty(int spool, bool confirm);
    // The spool (and target) are captured so a confirmation never applies to a different spool.
    void send_weigh(int spool, bool confirm);
    void send_weigh_load(int spool, const std::string& target, bool confirm);
    void sync_prompt();
    void attach_keyboard();
    static void on_key(lv_event_t* e);

    Platform& platform_;
    Options options_;
    Model model_;
    Theme theme_;
    std::unique_ptr<IpcClient> ipc_;
    std::unique_ptr<IdleManager> idle_;
    std::map<std::string, ResultHandler> pending_;
    int next_request_ = 1;
    lv_timer_t* timer_ = nullptr;
    std::string theme_name_ = "dark";
    bool rebuild_scheduled_ = false;
    bool sample_mode_ = false;
    bool display_gone_ = false;

    ScreenId screen_ = ScreenId::Main;
    std::string entry_;
    std::string last_scan_at_;
    std::string last_activity_top_;
    BannerMessage banner_message_;

    lv_obj_t* root_ = nullptr;
    lv_obj_t* key_catcher_ = nullptr;
    lv_group_t* key_group_ = nullptr;
    std::unique_ptr<Header> header_;
    std::unique_ptr<MainScreen> main_;
    std::unique_ptr<PrintersScreen> printers_;
    std::unique_ptr<LogScreen> log_;
    std::unique_ptr<SettingsScreen> settings_;
    std::unique_ptr<ResultBanner> banner_;
    std::unique_ptr<ConfirmDialog> confirm_;
    std::unique_ptr<AssignDialog> assign_;
    std::unique_ptr<CountdownOverlay> countdown_;
    std::unique_ptr<StatusOverlay> status_;
};

}  // namespace station

#include "app.hpp"

#include <cstdio>

#include "format.hpp"

namespace station {
namespace {

const char* const kSanityExplanation =
    "The scale is far from what Spoolman expects. Check it is the right spool and that its tare is correct.";

void poll_timer(lv_timer_t* timer)
{
    static_cast<App*>(lv_timer_get_user_data(timer))->poll();
}

std::string fmt_optional(const json& data, const char* key)
{
    const auto it = data.find(key);
    if (it == data.end() || !it->is_number()) return "--";
    return fmt_grams(it->get<double>());
}

}  // namespace

App::App(Platform& platform, Options options) : platform_(platform), options_(std::move(options))
{
    if (options_.use_ipc) {
        ipc_ = std::make_unique<IpcClient>(options_.host, options_.port);
        ipc_->on_line([this](const std::string& line) { on_line(line); });
        ipc_->on_connection([this](bool connected) { on_connection(connected); });
    }
    idle_ = std::make_unique<IdleManager>(*this);
    idle_->set_enabled(options_.idle_enabled);
    confirm_ = std::make_unique<ConfirmDialog>(*this);
    assign_ = std::make_unique<AssignDialog>(*this);
    countdown_ = std::make_unique<CountdownOverlay>(*this);
    status_ = std::make_unique<StatusOverlay>(*this);
}

App::~App()
{
    if (timer_ != nullptr) {
        lv_timer_delete(timer_);
    }
}

void App::start()
{
    // Buttons must not join the default group, or the keypad would navigate them.
    lv_group_set_default(nullptr);
    lv_display_add_event_cb(platform_.display(), on_display_deleted, LV_EVENT_DELETE, this);
    build_ui();
    attach_keyboard();
    idle_->start();
    timer_ = lv_timer_create(poll_timer, 20, this);
    refresh(kTopicAll);
}

void App::on_display_deleted(lv_event_t* e)
{
    auto* app = static_cast<App*>(lv_event_get_user_data(e));
    app->display_gone_ = true;
    if (app->timer_ != nullptr) {
        lv_timer_pause(app->timer_);
    }
}

void App::build_ui()
{
    theme_.apply(platform_.display(), theme_name_ != "light");
    lv_obj_t* screen = lv_screen_active();
    lv_obj_remove_style_all(screen);
    lv_obj_set_style_bg_color(screen, theme_.bg(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(screen, theme_.text(), 0);
    lv_obj_set_style_text_font(screen, theme_.small(), 0);
    lv_obj_set_scrollable(screen, false);

    root_ = ui::container(screen);
    lv_obj_set_size(root_, layout::kWidth, layout::kHeight);
    main_ = std::make_unique<MainScreen>(*this, root_);
    printers_ = std::make_unique<PrintersScreen>(*this, root_);
    log_ = std::make_unique<LogScreen>(*this, root_);
    settings_ = std::make_unique<SettingsScreen>(*this, root_);
    header_ = std::make_unique<Header>(*this, root_);
    banner_ = std::make_unique<ResultBanner>(*this, root_);
    banner_->show(banner_message_.text.empty() ? BannerMessage{BannerMessage::Kind::Idle, "Ready", ""}
                                               : banner_message_);
    show(screen_);
}

void App::destroy_ui()
{
    confirm_->close();
    assign_->close();
    countdown_->close();
    status_->reset();
    header_.reset();
    main_.reset();
    printers_.reset();
    log_.reset();
    settings_.reset();
    banner_.reset();
    if (root_ != nullptr) {
        lv_obj_delete(root_);
        root_ = nullptr;
    }
}

void App::rebuild_async(void* self)
{
    auto* app = static_cast<App*>(self);
    app->rebuild_scheduled_ = false;
    if (app->display_gone_) {
        return;
    }
    app->destroy_ui();
    app->build_ui();
    app->refresh(kTopicAll);
}

void App::attach_keyboard()
{
    lv_indev_t* keypad = platform_.keypad();
    if (keypad == nullptr) {
        return;
    }
    key_group_ = lv_group_create();
    key_catcher_ = lv_obj_create(lv_layer_sys());
    lv_obj_remove_style_all(key_catcher_);
    lv_obj_set_size(key_catcher_, 0, 0);
    lv_group_add_obj(key_group_, key_catcher_);
    lv_obj_add_event_cb(key_catcher_, on_key, LV_EVENT_KEY, this);
    lv_indev_set_group(keypad, key_group_);
}

void App::on_key(lv_event_t* e)
{
    auto* app = static_cast<App*>(lv_event_get_user_data(e));
    if (app->display_gone_) {
        return;
    }
    const std::uint32_t key = lv_event_get_key(e);
    app->idle().wake();
    if (key >= '0' && key <= '9') {
        app->handle_key(std::string(1, static_cast<char>(key)));
    } else if (key == LV_KEY_ENTER || key == '\r' || key == '\n') {
        app->handle_key("enter");
    } else if (key == LV_KEY_BACKSPACE || key == LV_KEY_DEL) {
        app->handle_key("backspace");
    } else if (key == LV_KEY_ESC) {
        app->handle_key("clear");
    }
}

bool App::online() const
{
    return model_.connected() && model_.has_snapshot() && model_.compatible();
}

void App::poll()
{
    if (display_gone_) {
        return;
    }
    if (ipc_) {
        ipc_->poll(steady_ms());
    }
    idle_->tick(state().settings, lv_display_get_inactive_time(platform_.display()));
}

void App::load_sample(const json& sample)
{
    sample_mode_ = true;
    const json& snapshot = sample.contains("snapshot") ? sample["snapshot"] : sample;
    std::uint32_t topics = 0;
    if (sample.contains("hello")) {
        topics |= model_.apply_hello(sample["hello"]);
    }
    const bool connected = !sample.contains("connected") || sample["connected"].get<bool>();
    topics |= model_.set_connected(true);
    topics |= model_.apply_snapshot(snapshot);
    if (!connected) {
        topics |= model_.set_connected(false);
    }
    if (sample.contains("entry") && sample["entry"].is_string()) {
        entry_ = sample["entry"].get<std::string>();
    }
    last_scan_at_ = state().scan.at;
    if (!state().activity.empty()) {
        last_activity_top_ = state().activity.front().id;
        const ActivityEntry& top = state().activity.front();
        banner(BannerMessage{top.ok ? (top.dry_run ? BannerMessage::Kind::Warn : BannerMessage::Kind::Ok)
                                    : BannerMessage::Kind::Error,
                             action_label(top.action) + (top.spool_id ? " #" + std::to_string(*top.spool_id) : "") +
                                 ": " + top.message,
                             top.id});
    }
    if (state().settings.theme != theme_name_) {
        theme_name_ = state().settings.theme;
        destroy_ui();
        build_ui();
    }
    refresh(topics | kTopicAll);
}

void App::on_connection(bool connected)
{
    std::uint32_t topics = model_.set_connected(connected);
    if (!connected) {
        for (auto& [id, handler] : pending_) {
            Result failed;
            failed.id = id;
            failed.code = "disconnected";
            failed.message = "Service connection lost";
            if (handler) handler(failed);
        }
        pending_.clear();
    }
    refresh(topics);
}

void App::on_line(const std::string& line)
{
    const Message message = parse_message(line);
    std::uint32_t topics = 0;
    switch (message.type) {
    case MessageType::Hello:
        topics = model_.apply_hello(message.body);
        if (!model_.compatible()) {
            std::fprintf(stderr, "station-ui: incompatible service protocol %d\n", model_.protocol());
        }
        break;
    case MessageType::Snapshot:
        if (message.body.contains("data")) {
            topics = model_.apply_snapshot(message.body["data"]);
            last_scan_at_ = state().scan.at;
            last_activity_top_ = state().activity.empty() ? std::string() : state().activity.front().id;
        }
        break;
    case MessageType::Event: {
        const auto topic = message.body.find("topic");
        const auto data = message.body.find("data");
        if (topic != message.body.end() && topic->is_string() && data != message.body.end()) {
            topics = model_.apply_event(topic->get<std::string>(), *data);
        }
        break;
    }
    case MessageType::Result: {
        const Result result = parse_result(message.body);
        const auto it = pending_.find(result.id);
        if (it != pending_.end()) {
            ResultHandler handler = std::move(it->second);
            pending_.erase(it);
            if (handler) {
                handler(result);
            } else {
                show_result(result);
            }
        } else if (!result.ok && !result.message.empty()) {
            banner({BannerMessage::Kind::Error, result.message, ""});
        }
        break;
    }
    case MessageType::Unknown:
        break;
    }
    if (topics != 0) {
        refresh(topics);
    }
}

void App::refresh(std::uint32_t topics)
{
    const State& s = state();
    const bool is_online = online();

    if ((topics & kTopicSettings) && s.settings.theme != theme_name_ && model_.has_snapshot()) {
        theme_name_ = s.settings.theme;
        if (!rebuild_scheduled_) {
            rebuild_scheduled_ = true;
            lv_async_call(rebuild_async, this);
        }
    }
    if ((topics & kTopicScan) && !s.scan.at.empty() && s.scan.at != last_scan_at_) {
        last_scan_at_ = s.scan.at;
        idle_->wake();
        if (s.scan.spool_id) {
            entry_ = std::to_string(*s.scan.spool_id);
            show(ScreenId::Main);
        } else {
            banner({BannerMessage::Kind::Warn, "Ignored QR code: " + s.scan.last_code, ""});
        }
    }
    if ((topics & kTopicScale) && s.scale.present && s.scale.status == "stable" && s.scale.grams.value_or(0) > 0 &&
        idle_->level() != IdleManager::Level::Awake) {
        idle_->wake();
    }
    if ((topics & kTopicActivity) && !s.activity.empty() && s.activity.front().id != last_activity_top_) {
        last_activity_top_ = s.activity.front().id;
        const ActivityEntry& top = s.activity.front();
        if (pending_.empty()) {
            BannerMessage::Kind kind = top.ok ? (top.dry_run ? BannerMessage::Kind::Warn : BannerMessage::Kind::Ok)
                                              : BannerMessage::Kind::Error;
            std::string text = action_label(top.action);
            if (top.spool_id) text += " #" + std::to_string(*top.spool_id);
            banner({kind, text + ": " + top.message, top.id});
        }
    }

    if (header_) header_->update(s, is_online);
    if (main_) main_->update(s, topics, is_online, entry_);
    if (printers_ && (topics & (kTopicPrinters | kTopicConnection | kTopicService | kTopicSettings))) {
        printers_->update(s, is_online);
    }
    if (log_ && (topics & (kTopicActivity | kTopicConnection | kTopicService))) {
        log_->update(s, is_online);
    }
    if (settings_ && (topics & (kTopicSettings | kTopicPrinters | kTopicConnection | kTopicService))) {
        settings_->update(s, is_online);
    }
    if (banner_) banner_->refresh(s);
    if (topics & kTopicPrinters) assign_->refresh(s);
    countdown_->update(s, is_online);

    std::string offline_text;
    if (!model_.connected()) {
        offline_text = "Spool station service offline\nReconnecting...";
    } else if (!model_.compatible()) {
        offline_text = "Incompatible service (protocol " + std::to_string(model_.protocol()) + ")";
    } else if (!model_.has_snapshot()) {
        offline_text = "Connecting...";
    }
    status_->set_offline(!offline_text.empty(), offline_text);
    if (!is_online) {
        confirm_->close();
        assign_->close();
    }
    sync_prompt();
}

void App::sync_prompt()
{
    const auto& prompt = state().scan.prompt;
    const std::string key = prompt ? "prompt:" + std::to_string(prompt->spool_id) + ":" + prompt->message : "";
    if (!prompt || !online()) {
        if (confirm_->open() && confirm_->key().rfind("prompt:", 0) == 0) {
            confirm_->close();
        }
        return;
    }
    if (confirm_->open() && confirm_->key() == key) {
        return;
    }
    ConfirmDialog::Spec spec;
    spec.key = key;
    spec.title = "Weight not saved for spool #" + std::to_string(prompt->spool_id);
    spec.message = kSanityExplanation;
    auto row = [](const char* name, const std::optional<double>& value) {
        return std::make_pair(std::string(name), value ? fmt_grams(*value) : std::string("--"));
    };
    spec.rows = {row("Measured (gross)", prompt->gross_g), row("Empty spool (tare)", prompt->tare_g),
                 row("Filament (net)", prompt->net_g), row("Expected gross", prompt->expected_g),
                 {"Difference", prompt->delta_g ? fmt_delta(*prompt->delta_g) : "--"}};
    spec.confirm_text = "Save weight";
    spec.cancel_text = "Dismiss";
    const int spool = prompt->spool_id;
    spec.on_confirm = [this, spool] {
        request("weigh", {{"spool_id", spool}, {"confirm", true}});
    };
    spec.on_cancel = [this] { request("dismiss_prompt", json::object(), [](const Result&) {}); };
    confirm_->show(std::move(spec));
}

void App::show(ScreenId screen)
{
    screen_ = screen;
    if (!main_) return;
    ui::set_hidden(main_->root(), screen != ScreenId::Main);
    ui::set_hidden(printers_->root(), screen != ScreenId::Printers);
    ui::set_hidden(log_->root(), screen != ScreenId::Log);
    ui::set_hidden(settings_->root(), screen != ScreenId::Settings);
    header_->set_active(screen);
}

void App::entry_digit(char digit)
{
    if (entry_.size() >= 7 || (entry_.empty() && digit == '0')) {
        return;
    }
    entry_.push_back(digit);
    refresh(kTopicSpool);
}

void App::entry_backspace()
{
    if (!entry_.empty()) {
        entry_.pop_back();
        refresh(kTopicSpool);
    }
}

void App::entry_clear()
{
    entry_.clear();
    refresh(kTopicSpool);
}

void App::entry_submit()
{
    const auto id = spool_id();
    if (!id) {
        banner({BannerMessage::Kind::Warn, "Type a spool ID first", ""});
        return;
    }
    banner({BannerMessage::Kind::Info, "Looking up spool #" + std::to_string(*id) + "...", ""});
    request("lookup", {{"spool_id", *id}});
}

void App::handle_key(const std::string& key)
{
    if (confirm_->open() || assign_->open()) {
        return;
    }
    if (key.size() == 1 && key[0] >= '0' && key[0] <= '9') {
        if (screen_ != ScreenId::Main) show(ScreenId::Main);
        entry_digit(key[0]);
    } else if (key == "enter") {
        entry_submit();
    } else if (key == "backspace") {
        entry_backspace();
    } else if (key == "clear") {
        entry_clear();
    }
}

std::optional<int> App::spool_id() const
{
    if (!entry_.empty()) {
        try {
            const int id = std::stoi(entry_);
            if (id > 0) return id;
        } catch (...) {
        }
        return std::nullopt;
    }
    if (state().spool && state().spool->found) {
        return state().spool->id;
    }
    return std::nullopt;
}

void App::request(const std::string& action, const json& args, ResultHandler done)
{
    if (!ipc_ || !online()) {
        if (sample_mode_) {
            banner({BannerMessage::Kind::Info, "Snapshot mode: would send " + action, ""});
        } else {
            banner({BannerMessage::Kind::Error, "Service offline: " + action + " not sent", ""});
        }
        return;
    }
    const std::string id = "u-" + std::to_string(next_request_++);
    pending_[id] = std::move(done);
    if (!ipc_->send_line(encode_request(id, action, args))) {
        pending_.erase(id);
        banner({BannerMessage::Kind::Error, "Could not send " + action, ""});
    }
}

void App::show_result(const Result& result)
{
    BannerMessage message;
    message.text = result.message.empty() ? (result.ok ? "Done" : "Failed") : result.message;
    message.activity_id = result.activity_id;
    if (!result.ok) {
        message.kind = BannerMessage::Kind::Error;
    } else if (result.dry_run) {
        message.kind = BannerMessage::Kind::Warn;
    } else {
        message.kind = BannerMessage::Kind::Ok;
    }
    banner(message);
}

void App::banner(BannerMessage message)
{
    banner_message_ = message;
    if (banner_) banner_->show(banner_message_);
}

void App::set_blank(bool blank)
{
    status_->set_blank(blank);
}

void App::confirm_weight(const Result& result, std::function<void()> on_confirm)
{
    ConfirmDialog::Spec spec;
    spec.key = "confirm-weight";
    spec.title = "Weight differs from expected";
    spec.message = kSanityExplanation;
    spec.rows = {{"Measured (gross)", fmt_optional(result.data, "gross_g")},
                 {"Empty spool (tare)", fmt_optional(result.data, "tare_g")},
                 {"Filament (net)", fmt_optional(result.data, "net_g")},
                 {"Expected gross", fmt_optional(result.data, "expected_g")}};
    const auto delta = result.data.find("delta_g");
    spec.rows.emplace_back("Difference", delta != result.data.end() && delta->is_number()
                                             ? fmt_delta(delta->get<double>())
                                             : std::string("--"));
    spec.confirm_text = "Save anyway";
    spec.on_confirm = std::move(on_confirm);
    spec.on_cancel = [this] { banner({BannerMessage::Kind::Info, "Not saved", ""}); };
    confirm_->show(std::move(spec));
    banner({BannerMessage::Kind::Warn, result.message, ""});
}

void App::weigh(bool confirm)
{
    const auto id = spool_id();
    if (!id) return;
    send_weigh(*id, confirm);
}

void App::send_weigh(int spool, bool confirm)
{
    banner({BannerMessage::Kind::Info, "Weighing spool #" + std::to_string(spool) + "...", ""});
    request("weigh", {{"spool_id", spool}, {"confirm", confirm}}, [this, spool](const Result& result) {
        if (result.code == "needs_confirm") {
            confirm_weight(result, [this, spool] { send_weigh(spool, true); });
        } else {
            show_result(result);
        }
    });
}

void App::weigh_load(bool confirm)
{
    const auto id = spool_id();
    if (!id) return;
    send_weigh_load(*id, state().settings.target, confirm);
}

void App::send_weigh_load(int spool, const std::string& target, bool confirm)
{
    banner({BannerMessage::Kind::Info, "Weighing and loading spool #" + std::to_string(spool) + "...", ""});
    request("weigh_load", {{"spool_id", spool}, {"target", target}, {"confirm", confirm}},
            [this, spool, target](const Result& result) {
                if (result.code == "needs_confirm") {
                    confirm_weight(result, [this, spool, target] { send_weigh_load(spool, target, true); });
                } else {
                    show_result(result);
                }
            });
}

void App::load()
{
    const auto id = spool_id();
    if (!id) return;
    banner({BannerMessage::Kind::Info, "Setting next spool #" + std::to_string(*id) + "...", ""});
    request("load", {{"spool_id", *id}});
}

void App::empty_spool()
{
    const auto id = spool_id();
    if (!id) return;
    const State& s = state();
    ConfirmDialog::Spec spec;
    spec.key = "empty";
    spec.title = "Record spool #" + std::to_string(*id) + " as empty?";
    spec.message = "The scale weight becomes the empty spool weight of this spool and the default for its filament, "
                   "remaining is set to 0 g and the spool is archived. This can be undone.";
    spec.rows = {{"Scale now", s.scale.present && s.scale.grams ? fmt_grams(*s.scale.grams, 1) + "  (" +
                                                                    scale_status_label(s.scale.status) + ")"
                                                              : "--"}};
    if (s.spool && s.spool->found && s.spool->id == *id) {
        spec.rows.emplace_back("Known tare", s.spool->spool_weight_g ? fmt_grams(*s.spool->spool_weight_g) : "unknown");
        spec.rows.emplace_back("Remaining now", fmt_grams(s.spool->remaining_g));
    }
    spec.confirm_text = "Record empty";
    spec.danger = true;
    const int spool = *id;
    spec.on_confirm = [this, spool] { request_empty(spool, false); };
    confirm_->show(std::move(spec));
}

void App::request_empty(int spool, bool confirm)
{
    request("empty_spool", {{"spool_id", spool}, {"confirm", confirm}}, [this, spool](const Result& result) {
        if (result.code != "needs_confirm") {
            show_result(result);
            return;
        }
        ConfirmDialog::Spec again;
        again.key = "empty-confirm";
        again.title = "Spool #" + std::to_string(spool) + " may not be empty";
        again.message = result.message;
        again.confirm_text = "Record anyway";
        again.danger = true;
        again.on_confirm = [this, spool] { request_empty(spool, true); };
        confirm_->show(std::move(again));
    });
}

void App::open_assign(std::string printer, std::string lane)
{
    const auto id = spool_id();
    assign_->show(id.value_or(0), printer, lane);
}

void App::assign(int spool_id, const std::string& printer, const std::string& lane)
{
    banner({BannerMessage::Kind::Info, "Assigning spool #" + std::to_string(spool_id) + " to " + lane + "...", ""});
    request("assign_lane", {{"spool_id", spool_id}, {"printer", printer}, {"lane", lane}});
}

void App::clear_pending(std::string printer)
{
    request("clear_pending", {{"printer", printer}});
}

void App::undo(std::string activity_id)
{
    banner({BannerMessage::Kind::Info, "Undoing...", ""});
    request("undo", {{"activity_id", activity_id}});
}

void App::set_setting(const std::string& key, const json& value)
{
    request("set_setting", {{"key", key}, {"value", value}}, [this](const Result& result) {
        if (!result.ok) show_result(result);
    });
}

void App::cancel_countdown()
{
    request("cancel_countdown", json::object());
}

}  // namespace station

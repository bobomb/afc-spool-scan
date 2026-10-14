#include "idle.hpp"

#include "app.hpp"

namespace station {

void IdleManager::tick(const Settings& settings, std::uint32_t inactive_ms)
{
    if (!enabled_) {
        return;
    }
    const Level next = level_for(inactive_ms, settings.idle_dim_s, settings.idle_off_s,
                                 app_.platform().has_backlight());
    if (next != level_) {
        apply(next);
    }
}

void IdleManager::wake()
{
    lv_display_trigger_activity(app_.platform().display());
    if (level_ != Level::Awake) {
        apply(Level::Awake);
    }
}

void IdleManager::force(Level level)
{
    apply(level);
}

void IdleManager::apply(Level level)
{
    level_ = level;
    Platform& platform = app_.platform();
    if (platform.has_backlight()) {
        platform.set_backlight(level == Level::Awake ? 100 : level == Level::Dim ? 25 : 0);
    }
    app_.set_blank(level == Level::Off);
}

}  // namespace station

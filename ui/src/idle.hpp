#pragma once
// Idle management: dim after idle_dim_s, blank after idle_off_s; wake on touch, scan or scale change.

#include <cstdint>

namespace station {

class App;
struct Settings;

class IdleManager {
public:
    enum class Level { Awake, Dim, Off };

    explicit IdleManager(App& app) : app_(app) {}
    // Called periodically with the current inactivity in milliseconds.
    void tick(const Settings& settings, std::uint32_t inactive_ms);
    void wake();
    void force(Level level);
    // Sets the awake brightness once at startup; the kernel's boot level can be very dim.
    void start();
    void set_enabled(bool enabled) { enabled_ = enabled; }
    Level level() const { return level_; }

    static int brightness_for(Level level) { return level == Level::Awake ? 100 : level == Level::Dim ? 25 : 0; }

    // Pure decision used by tick(); dimming is skipped without a software backlight.
    static Level level_for(std::uint32_t inactive_ms, int dim_s, int off_s, bool has_backlight)
    {
        const std::uint64_t inactive = inactive_ms;
        if (off_s > 0 && inactive >= static_cast<std::uint64_t>(off_s) * 1000u) {
            return Level::Off;
        }
        if (has_backlight && dim_s > 0 && inactive >= static_cast<std::uint64_t>(dim_s) * 1000u) {
            return Level::Dim;
        }
        return Level::Awake;
    }

private:
    void apply(Level level);

    App& app_;
    Level level_ = Level::Awake;
    bool enabled_ = true;
};

}  // namespace station

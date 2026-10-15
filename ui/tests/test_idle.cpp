#include <doctest/doctest.h>

#include "idle.hpp"

using station::IdleManager;

TEST_CASE("idle levels follow the settings")
{
    using Level = IdleManager::Level;
    CHECK(IdleManager::level_for(0, 120, 300, true) == Level::Awake);
    CHECK(IdleManager::level_for(119999, 120, 300, true) == Level::Awake);
    CHECK(IdleManager::level_for(120000, 120, 300, true) == Level::Dim);
    CHECK(IdleManager::level_for(300000, 120, 300, true) == Level::Off);
    CHECK(IdleManager::level_for(200000, 120, 300, false) == Level::Awake);
    CHECK(IdleManager::level_for(300000, 120, 300, false) == Level::Off);
    CHECK(IdleManager::level_for(4000000, 0, 0, true) == Level::Awake);
    CHECK(IdleManager::level_for(4000000, 120, 0, true) == Level::Dim);
}

TEST_CASE("idle levels map to backlight percentages")
{
    using Level = IdleManager::Level;
    CHECK(IdleManager::brightness_for(Level::Awake) == 100);
    CHECK(IdleManager::brightness_for(Level::Dim) == 25);
    CHECK(IdleManager::brightness_for(Level::Off) == 0);
}

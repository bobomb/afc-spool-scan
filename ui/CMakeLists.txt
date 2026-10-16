cmake_minimum_required(VERSION 3.24)
project(spool_station_ui VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_C_STANDARD 99)

set(STATION_UI_BACKEND "windows" CACHE STRING "Display backend: windows, sdl, drm or headless")
set_property(CACHE STATION_UI_BACKEND PROPERTY STRINGS windows sdl drm headless)
option(STATION_UI_TESTS "Build the unit tests" ON)

if(NOT STATION_UI_BACKEND MATCHES "^(windows|sdl|drm|headless)$")
  message(FATAL_ERROR "Unknown STATION_UI_BACKEND '${STATION_UI_BACKEND}'")
endif()
if(STATION_UI_BACKEND STREQUAL "windows" AND NOT WIN32)
  message(FATAL_ERROR "The windows backend only builds on Windows")
endif()
string(TOUPPER "${STATION_UI_BACKEND}" STATION_BACKEND_UPPER)

# Keep fetched sources in the build tree (LVGL would otherwise default to ui/.deps).
set(FETCHCONTENT_BASE_DIR "${CMAKE_BINARY_DIR}/_deps" CACHE PATH "Fetched dependencies" FORCE)
include(FetchContent)

# ---- LVGL v9.6.0 -------------------------------------------------------------
set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(LV_BUILD_INSTALL OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_LINUX_DRM OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_EVDEV OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_SDL OFF CACHE BOOL "" FORCE)
if(STATION_UI_BACKEND STREQUAL "drm")
  set(CONFIG_LV_USE_LINUX_DRM ON CACHE BOOL "" FORCE)
  set(CONFIG_LV_USE_EVDEV ON CACHE BOOL "" FORCE)
elseif(STATION_UI_BACKEND STREQUAL "sdl")
  set(CONFIG_LV_USE_SDL ON CACHE BOOL "" FORCE)
endif()

FetchContent_Declare(lvgl
  URL https://github.com/lvgl/lvgl/archive/refs/tags/v9.6.0.tar.gz
  URL_HASH SHA256=b20ee3acc1bba13c62d854f9ebd62e4c51e0b443b1e0225892e86442defa84df
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)

# ---- nlohmann/json v3.12.0 -------------------------------------------------------
set(JSON_BuildTests OFF CACHE INTERNAL "")
set(JSON_Install OFF CACHE INTERNAL "")
FetchContent_Declare(nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
  URL_HASH SHA256=42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)

FetchContent_MakeAvailable(lvgl nlohmann_json)
target_compile_definitions(lvgl PUBLIC STATION_UI_BACKEND_${STATION_BACKEND_UPPER}=1)
if(MSVC)
  target_compile_options(lvgl PRIVATE /w)
endif()

# ---- station core (no LVGL; unit tested) -------------------------------------
add_library(station_core STATIC
  src/format.cpp
  src/ipc_client.cpp
  src/model.cpp
  src/png_writer.cpp
  src/protocol.cpp
  src/script.cpp
  src/view_model.cpp
)
target_include_directories(station_core PUBLIC src)
target_link_libraries(station_core PUBLIC nlohmann_json::nlohmann_json)
if(WIN32)
  target_link_libraries(station_core PUBLIC ws2_32)
  target_compile_definitions(station_core PUBLIC WIN32_LEAN_AND_MEAN NOMINMAX _CRT_SECURE_NO_WARNINGS)
endif()

if(MSVC)
  set(STATION_WARNINGS /W4 /permissive- /utf-8 /wd4100)
else()
  set(STATION_WARNINGS -Wall -Wextra -Wno-unused-parameter -Wno-missing-field-initializers)
endif()
target_compile_options(station_core PRIVATE ${STATION_WARNINGS})

# ---- touch UI executable ------------------------------------------------------------
set(STATION_UI_SOURCES
  src/main.cpp
  src/app.cpp
  src/idle.cpp
  src/platform_headless.cpp
  src/theme.cpp
  src/screens/log_screen.cpp
  src/screens/main_screen.cpp
  src/screens/printers_screen.cpp
  src/screens/settings_screen.cpp
  src/widgets/assign_dialog.cpp
  src/widgets/confirm_dialog.cpp
  src/widgets/countdown_overlay.cpp
  src/widgets/keypad_sheet.cpp
  src/widgets/more_menu.cpp
  src/widgets/printer_card.cpp
  src/widgets/result_banner.cpp
  src/widgets/side_rail.cpp
  src/widgets/spool_hero.cpp
  src/widgets/status_overlay.cpp
  src/widgets/target_card.cpp
  src/widgets/ui_helpers.cpp
  src/fonts/station_icons_22.c
)
if(NOT STATION_UI_BACKEND STREQUAL "headless")
  list(APPEND STATION_UI_SOURCES src/platform_${STATION_UI_BACKEND}.cpp)
endif()

add_executable(station-ui ${STATION_UI_SOURCES})
target_link_libraries(station-ui PRIVATE station_core lvgl::lvgl)
target_compile_definitions(station-ui PRIVATE STATION_UI_VERSION="${PROJECT_VERSION}")
target_compile_options(station-ui PRIVATE ${STATION_WARNINGS})

# ---- tests -------------------------------------------------------------------------------
if(STATION_UI_TESTS)
  set(DOCTEST_WITH_TESTS OFF CACHE BOOL "" FORCE)
  set(DOCTEST_WITH_MAIN_IN_STATIC_LIB OFF CACHE BOOL "" FORCE)
  set(DOCTEST_NO_INSTALL ON CACHE BOOL "" FORCE)
  FetchContent_Declare(doctest
    URL https://github.com/doctest/doctest/archive/refs/tags/v2.5.3.tar.gz
    URL_HASH SHA256=174ebc4e769928959614789c5b4e9c3d0a0f81a62bb608756b127bfebfb21331
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  FetchContent_MakeAvailable(doctest)

  enable_testing()
  add_executable(station-ui-tests
    tests/test_main.cpp
    tests/test_format.cpp
    tests/test_idle.cpp
    tests/test_ipc_client.cpp
    tests/test_model.cpp
    tests/test_png.cpp
    tests/test_protocol.cpp
    tests/test_script.cpp
    tests/test_view_model.cpp
  )
  target_link_libraries(station-ui-tests PRIVATE station_core doctest::doctest)
  target_compile_options(station-ui-tests PRIVATE ${STATION_WARNINGS})
  target_compile_definitions(station-ui-tests PRIVATE STATION_UI_SAMPLES="${CMAKE_CURRENT_SOURCE_DIR}/samples")
  add_test(NAME unit COMMAND station-ui-tests)

  # Render every sample state headlessly; fails on crashes or missing screens.
  file(GLOB STATION_UI_SAMPLE_STATES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/samples/*.json")
  foreach(sample IN LISTS STATION_UI_SAMPLE_STATES)
    get_filename_component(sample_name "${sample}" NAME_WE)
    add_test(NAME snapshot_${sample_name}
      COMMAND station-ui --snapshot "${CMAKE_BINARY_DIR}/snapshots/${sample_name}" --state "${sample}")
  endforeach()
endif()

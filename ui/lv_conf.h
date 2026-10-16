/* LVGL v9.6 configuration for the spool station touch UI.
 * Only non-default options are set; everything else comes from lv_conf_internal.h.
 * The backend macro (STATION_UI_BACKEND_*) is defined by ui/CMakeLists.txt. */
#ifndef LV_CONF_H
#define LV_CONF_H

#define LV_COLOR_FORMAT_DEFAULT LV_COLOR_FORMAT_XRGB8888

#define LV_USE_STDLIB_MALLOC LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB

/* The Windows driver runs its message loop on its own thread and needs lv_lock(). */
#if defined(STATION_UI_BACKEND_WINDOWS)
#define LV_USE_OS LV_OS_WINDOWS
#define LV_USE_WINDOWS 1
#else
#define LV_USE_OS LV_OS_NONE
#endif

#if defined(STATION_UI_BACKEND_SDL)
#define LV_USE_SDL 1
#define LV_SDL_INCLUDE_PATH <SDL2/SDL.h>
#define LV_SDL_RENDER_MODE LV_DISPLAY_RENDER_MODE_DIRECT
#define LV_SDL_AUTO_BACKEND 0
#define LV_SDL_BACKEND LV_SDL_BACKEND_SW
#endif

#if defined(STATION_UI_BACKEND_DRM)
#define LV_USE_LINUX_DRM 1
#define LV_LINUX_DRM_AUTO_BACKEND 0
#define LV_LINUX_DRM_BACKEND LV_LINUX_DRM_BACKEND_FBDEV
#define LV_USE_EVDEV 1
#endif

#define LV_DEF_REFR_PERIOD 16
#define LV_DPI_DEF 133

#define LV_USE_SNAPSHOT 1
#define LV_USE_OBSERVER 1

#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF 1

#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_22 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT LV_FONT_DEFAULT_MONTSERRAT_16

/* Multi-colour spools fill their tile with a diagonal gradient of up to four colours. */
#define LV_GRADIENT_MAX_STOPS 4
#define LV_USE_DRAW_SW_COMPLEX_GRADIENTS 1

#define LV_USE_THEME_DEFAULT 1
#define LV_THEME_DEFAULT_DARK 1
#define LV_THEME_DEFAULT_GROW 0

#define LV_USE_VECTOR_GRAPHIC 0
#define LV_USE_THORVG 0

#define LV_BUILD_EXAMPLES 0
#define LV_BUILD_DEMOS 0

#endif /* LV_CONF_H */

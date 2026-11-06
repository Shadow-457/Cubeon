"""Compact Play controls for video syncing and optional performance mods."""
import flet as ft

from cubeon import i18n, thread_safe_ui
from cubeon.perf_mods import OPTIONAL_PERF_MODS


def build_boost_options(cfg, save_config, set_status, *, accent, text_color):
    """Preferences only: all game-file changes happen during launch preparation."""
    def save(key, value):
        existed, previous = key in cfg, cfg.get(key)
        cfg[key] = value
        try:
            save_config(cfg)
        except Exception:
            if existed:
                cfg[key] = previous
            else:
                cfg.pop(key, None)
            set_status(i18n.t("Couldn't save FPS boost settings. Try again."))
            return False
        return True

    sync = ft.Checkbox(
        label=i18n.t("Sync game settings"),
        value=bool(cfg.get("fps_boost_sync_settings", False)),
        label_style=ft.TextStyle(size=12, color=text_color), active_color=accent,
        visual_density=ft.VisualDensity.COMPACT,
        tooltip=i18n.t("Reapply fast video settings before every launch: 4-chunk render distance, "
                       "5-chunk simulation, VSync off and unlimited FPS. Tunes the renderer and turns off "
                       "Iris/Oculus shaders and Cubeon motion blur. Overrides in-game video edits. "
                       "Turn FPS boost off to restore previous unchanged settings."),
        data="play-fps-sync",
    )
    optional = ft.PopupMenuButton(
        icon=ft.Icons.TUNE_ROUNDED, icon_size=18, icon_color=text_color,
        tooltip=i18n.t("Optional performance mods"), data="play-fps-mods",
        items=[ft.PopupMenuItem(
            content=i18n.t("Add compatible builds at next launch"), disabled=True)],
    )

    def change_sync(event):
        with thread_safe_ui.TREE_LOCK:
            if row.disabled:
                sync.value = bool(cfg.get("fps_boost_sync_settings", False))
            elif save("fps_boost_sync_settings", bool(sync.value)):
                set_status(i18n.t("Video settings will sync at every launch." if sync.value else
                                  "Settings sync off. Your video edits will stay saved."))
            else:
                sync.value = bool(cfg.get("fps_boost_sync_settings", False))
            thread_safe_ui.refresh(row)

    sync.on_change = change_sync
    descriptions = {
        "moreculling": "Extra model culling; may affect how blocks look.",
        "ebe": "Faster supported block entities, such as chests.",
        "exordium": "Renders GUI elements less often; may affect HUD smoothness.",
    }
    chosen = cfg.get("fps_boost_optional_mods", [])
    if not isinstance(chosen, list):
        chosen = []
    for slug, _project, label in OPTIONAL_PERF_MODS:
        item = ft.PopupMenuItem(
            content=label, checked=slug in chosen, tooltip=i18n.t(descriptions[slug]), data=slug)

        def choose(event, slug=slug, item=item):
            with thread_safe_ui.TREE_LOCK:
                if row.disabled:
                    return
                previous = cfg.get("fps_boost_optional_mods", [])
                selected = set(previous) if isinstance(previous, list) else set()
                if slug in selected:
                    selected.remove(slug)
                else:
                    selected.add(slug)
                values = [entry[0] for entry in OPTIONAL_PERF_MODS if entry[0] in selected]
                if save("fps_boost_optional_mods", values):
                    item.checked = slug in values
                    set_status(i18n.t("Mod choices saved for next launch. Disable installed mods in Mods."))
                thread_safe_ui.refresh(row)

        item.on_click = choose
        optional.items.append(item)
    optional.items.append(ft.PopupMenuItem(
        content=i18n.t("Disable installed mods in Mods"), disabled=True))
    row = ft.Row([sync, optional], spacing=0, tight=True,
                 disabled=not bool(cfg.get("fps_boost_enabled", True)))
    return row

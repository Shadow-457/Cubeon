"""
The Stats tab: one clean screen of "what this install actually is".

Design notes
- Follows the launcher's flat, slab-free look: quiet section labels, big
  Minecraftia numbers, no boxed cards stacked inside boxes. The numbers ARE
  the UI - same "state is typography" rule the mods rows follow.
- Everything is computed lazily on refresh (called when the tab opens), so
  the tab costs nothing until visited - same lazy-tab discipline as the
  other tabs.
- All data comes from sources that already exist: milestones.json
  (playtime, hosted sessions, friend high-water, unlock ledger), the
  version/profile/content/plugin folder scans and the skins/capes
  metadata. No new state files, no new counters to maintain.
- Scans are strictly read-only: they glob folders directly instead of
  calling get_profile_dir()/content_dir(), which CREATE directories as a
  side effect - a stats screen must never leave empty folders behind.
"""
import os
import time

import flet as ft

from cubeon.theme import RADIUS, TEXT_FAINT, CARD_BORDER, ACCENT_DIM
from cubeon.paths import (PROFILES_DIR, RESOURCEPACKS_DIR, SHADERPACKS_DIR,
                          SERVERS_DIR)
from cubeon import milestones
from cubeon.versions import get_installed_versions
from cubeon.skins import list_custom_skins
from cubeon.capes import list_custom_capes
from cubeon.cosmetics import HATS


def build_stats_tab(page: ft.Page, cfg: dict, state: dict, *,
                    section_label, go_to_tab,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """Builds the Stats tab. `go_to_tab(key)` is main.py's switch_tab, kept
    for future shortcut chips (jump straight to Mods / Servers / ...)."""

    # --- live controls (filled by refresh_stats) ---------------------------
    def _value():
        return ft.Text("0", size=24, color=TEXT, font_family=FONT_DISPLAY,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

    def _caption(label):
        return ft.Text(label.upper(), size=11, color=TEXT_DIM,
                       font_family=FONT_MONO, weight=ft.FontWeight.W_600)

    playtime_value, sessions_value, friends_value, hats_value = _value(), _value(), _value(), _value()
    versions_value, mods_value, packs_value, content_value, plugins_value = \
        _value(), _value(), _value(), _value(), _value()
    skins_value, capes_value, member_value = _value(), _value(), _value()

    _CAPTIONS = {
        "playtime": "Time in game", "sessions": "Sessions hosted",
        "friends": "Friends", "hats": "Hats unlocked",
        "versions": "Versions installed", "mods": "Mods installed",
        "packs": "Modpacks installed", "content": "Packs & shaders",
        "plugins": "Server plugins", "skins": "Custom skins",
        "capes": "Custom capes", "member": "Playing since",
    }
    playtime_caption = _caption(_CAPTIONS["playtime"])
    sessions_caption = _caption(_CAPTIONS["sessions"])
    friends_caption = _caption(_CAPTIONS["friends"])
    hats_caption = _caption(_CAPTIONS["hats"])
    versions_caption = _caption(_CAPTIONS["versions"])
    mods_caption = _caption(_CAPTIONS["mods"])
    packs_caption = _caption(_CAPTIONS["packs"])
    content_caption = _caption(_CAPTIONS["content"])
    plugins_caption = _caption(_CAPTIONS["plugins"])
    skins_caption = _caption(_CAPTIONS["skins"])
    capes_caption = _caption(_CAPTIONS["capes"])
    member_caption = _caption(_CAPTIONS["member"])

    def _pair(value_ctrl, caption_ctrl):
        return ft.Column([value_ctrl, caption_ctrl], spacing=6,
                         horizontal_alignment=ft.CrossAxisAlignment.START)

    def _stat_row(pairs):
        return ft.Row(pairs, spacing=32,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _rule():
        return ft.Container(height=1, bgcolor=CARD_BORDER,
                            margin=ft.Margin(0, 20, 0, 20))

    # --- read-only counters -------------------------------------------------
    def _count_jars(directory: str) -> int:
        """.jar / .jar.disabled files directly in `directory` (no recursion,
        no side effects). 0 when the folder doesn't exist."""
        try:
            names = os.listdir(directory)
        except OSError:
            return 0
        return sum(1 for n in names
                   if n.endswith(".jar") or n.endswith(".jar.disabled"))

    def _count_mods_all_profiles() -> int:
        """Total mods across every profile folder. Profile dirs are
        '<mc_version>-<loader>' (see cubeon/mods.py profile_key); counting
        by glob rather than list_mods() avoids get_profile_dir()'s
        create-on-read side effect."""
        try:
            entries = os.listdir(PROFILES_DIR)
        except OSError:
            return 0
        total = 0
        for name in entries:
            if "-" not in name:
                continue
            full = os.path.join(PROFILES_DIR, name)
            if os.path.isdir(full):
                total += _count_jars(full)
        return total

    def _count_content() -> int:
        """Resource packs + shaders in the shared .minecraft folders."""
        total = 0
        for d in (RESOURCEPACKS_DIR, SHADERPACKS_DIR):
            try:
                names = os.listdir(d)
            except OSError:
                continue
            total += sum(1 for n in names if n.endswith(".zip"))
        return total

    def _count_plugins_all_servers() -> int:
        """Plugins across every server instance. Globs servers/<id>/plugins
        directly - get_plugins_dir() creates the folder on read, and a stats
        pass must not leave empty server dirs behind."""
        try:
            server_ids = os.listdir(SERVERS_DIR)
        except OSError:
            return 0
        total = 0
        for sid in server_ids:
            total += _count_jars(os.path.join(SERVERS_DIR, sid, "plugins"))
        return total

    def refresh_stats():
        """Recompute every number in place. Cheap (folder globs + one JSON
        read); called when the tab opens."""
        ms = milestones.load_state()
        seconds = float(ms.get("seconds_played") or 0)
        playtime_value.value = f"{seconds / 3600:,.1f} h"
        sessions_value.value = f"{ms.get('sessions_hosted', 0):,}"
        friends_value.value = f"{ms.get('friends_count_high', 0):,}"
        hats_value.value = f"{len(ms.get('unlocked', []))} / {len(HATS)}"

        first = ms.get("first_seen_at")
        member_value.value = time.strftime("%b %Y", time.localtime(first)) if first else "-"

        try:
            versions_value.value = f"{len(get_installed_versions()):,}"
        except Exception:
            versions_value.value = "-"

        mods_value.value = f"{_count_mods_all_profiles():,}"

        try:
            from cubeon.modpacks import list_installed_modpacks
            packs_value.value = f"{len(list_installed_modpacks()):,}"
        except Exception:
            packs_value.value = "-"

        content_value.value = f"{_count_content():,}"
        plugins_value.value = f"{_count_plugins_all_servers():,}"

        try:
            skins_value.value = f"{len(list_custom_skins()):,}"
            capes_value.value = f"{len(list_custom_capes()):,}"
        except Exception:
            skins_value.value = capes_value.value = "-"

        from cubeon import thread_safe_ui
        for ctrl in (playtime_value, sessions_value, friends_value, hats_value,
                     versions_value, mods_value, packs_value, content_value,
                     plugins_value, skins_value, capes_value, member_value):
            thread_safe_ui.refresh(ctrl)

    # --- layout -------------------------------------------------------------
    stats_tab = ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Stats", size=28, color=TEXT,
                                    font_family=FONT_DISPLAY),
                            ft.Text("Everything you've done in Cubeon, at a glance.",
                                    size=13, color=TEXT_DIM),
                        ],
                        spacing=2,
                    ),
                ],
            ),
            ft.Container(height=20),

            section_label("Playtime"),
            _stat_row([_pair(playtime_value, playtime_caption),
                       _pair(sessions_value, sessions_caption),
                       _pair(friends_value, friends_caption),
                       _pair(hats_value, hats_caption)]),
            _rule(),

            section_label("Library"),
            _stat_row([_pair(versions_value, versions_caption),
                       _pair(mods_value, mods_caption),
                       _pair(packs_value, packs_caption)]),
            ft.Container(height=20),
            _stat_row([_pair(content_value, content_caption),
                       _pair(plugins_value, plugins_caption)]),
            _rule(),

            section_label("Cosmetics"),
            _stat_row([_pair(skins_value, skins_caption),
                       _pair(capes_value, capes_caption),
                       _pair(member_value, member_caption)]),
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    return stats_tab, refresh_stats

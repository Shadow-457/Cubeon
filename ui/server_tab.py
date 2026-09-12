"""
Cubeon - Server tab UI.
Lets the user host a local Minecraft server for whatever version is
currently selected on the Play tab: install the server jar, accept the
EULA, tweak the common server.properties settings, and start/stop it
with a live console.

Built the same way as skin_tab.py / mods_tab.py: a build_server_tab()
function main.py calls once at startup, returning the tab's root control
plus a refresh function main.py calls whenever it needs the tab to catch
up with the selected version (switching to the tab, changing versions).
"""

import re
import threading

import flet as ft
from cubeon.theme import (  # design system (radius, toggles, faint text tier, underline tabs, accent fg)
    RADIUS, animated_switch, TEXT_FAINT, text_tab, ON_ACCENT,
    attach_hover, ROW_HOVER, ACCENT_TINT, CARD_BORDER, CARD_FILL,
)

import launcher_core as core
from cubeon import icons as _icons  # disk cache for Modrinth project art
from cubeon import thread_safe_ui  # Makes page.update() safe from background threads


def build_server_tab(page: ft.Page, cfg: dict, state: dict, *,
                      section_label, pixel_divider,
                      BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                      TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """
    Builds the Server tab's root control (a Flet Column) and returns it
    along with a refresh_server_tab() function.

    Args:
        page: The Flet page instance - needed to trigger page.update() from
              background threads (installing, downloading, the live console).
        cfg: The launcher configuration dict. Reads/writes cfg["server_ram_mb"]
             and cfg["java_path"], same java path Settings uses to launch the game.
        state: The shared mutable state dict from main.py - reads
               state["selected_version"], the same version the Play tab has
               selected, so hosting a server never needs its own picker.
        section_label, pixel_divider: Shared helper functions from main.py.
        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM, TEXT, TEXT_DIM,
        DANGER, FONT_DISPLAY, FONT_MONO: Shared design tokens from main.py.

    Returns:
        (ft.Column, ft.Column, ft.Column, callable): the Console view, the
        Settings view, and the Plugins view (each a separate sidebar
        sub-item in main.py), plus refresh_server_tab() to reload all
        three for the currently selected version.
    """

    # Track which version's settings/console are currently loaded, so a
    # stray callback from a previous version's install/console can't stomp
    # on whatever the user has switched to since.
    active_version = {"value": None}

    # --- Header -------------------------------------------------------

    def _make_version_text():
        return ft.Text("No version selected", size=14, color=TEXT_DIM, font_family=FONT_MONO)

    def _make_no_version_notice():
        return ft.Container(
            content=ft.Text(
                "Pick a version on the Play tab first. The server hosts whatever's selected there.",
                size=13, color=TEXT_DIM,
            ),
            bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=16,
            visible=False,
        )

    # Console and Settings are separate sidebar sub-items / separate Flet
    # subtrees, so each needs its own copy of these two shared widgets -
    # a control can't live in two parents at once.
    version_text = _make_version_text()
    no_version_notice = _make_no_version_notice()
    version_text_settings = _make_version_text()
    no_version_notice_settings = _make_no_version_notice()

    # Tracks whether an install/update download is currently running for
    # active_version["value"], so refresh_server_tab() (called every time
    # the user (re)visits a Server sub-tab) doesn't stomp the in-progress
    # button/status/progress-bar back to "Install server" mid-download -
    # that's what made installs look like they silently reset whenever the
    # user switched tabs/windows and came back.
    install_in_progress = {"value": False}

    install_status = ft.Text("", size=12, color=TEXT_DIM)
    install_progress = ft.ProgressBar(
        value=0, color=ACCENT, bgcolor=SURFACE_HI, visible=False, data=1,
    )

    def _set_install_busy(busy: bool):
        install_in_progress["value"] = busy
        install_button.disabled = busy
        install_button.content.value = "Installing..." if busy else install_button_label()
        install_progress.visible = busy
        page.update()

    def install_button_label():
        v = active_version["value"]
        if not v:
            return "Install server"
        return "Update server" if core.is_server_installed(v) else "Install server"

    def on_install_click(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        _set_install_busy(True)
        install_status.value = "Starting..."
        page.update()

        def status_cb(text):
            if active_version["value"] != version_id:
                return
            install_status.value = text
            # Text change only: repaint the status line, not the tree.
            thread_safe_ui.refresh(install_status)

        def progress_cb(val):
            if active_version["value"] != version_id:
                return
            mx = install_progress.data or 1
            install_progress.value = val / mx if mx else 0
            thread_safe_ui.refresh(install_progress)

        def max_cb(val):
            install_progress.data = val

        # Cubeon servers are Paper, always (vanilla hosting was removed) -
        # core.install_server() takes no type choice anymore.

        def worker():
            try:
                # A Paper jar already on disk in Cubeon's folder is used
                # instead of a download automatically (see
                # cubeon.server.find_local_paper_jar), so this works even
                # with papermc.io unreachable.
                core.install_server(
                    version_id,
                    status_cb=status_cb, progress_cb=progress_cb, max_cb=max_cb,
                )
            except Exception as ex:
                if active_version["value"] == version_id:
                    _set_install_busy(False)
                    install_status.value = f"Install failed: {ex}"
                    page.update()
                return
            if active_version["value"] == version_id:
                _set_install_busy(False)
                refresh_plugins_visibility()
                refresh_server_tab()

        threading.Thread(target=worker, daemon=True).start()

    install_button = ft.Container(
        content=ft.Text("Install server", color=BG, weight=ft.FontWeight.W_700, size=14),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(vertical=13, horizontal=18),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_install_click, width=180,
        tooltip="Paper server - works with normal Minecraft and supports plugins.",
    )

    # --- Server type -------------------------------------------------------
    # Vanilla hosting was removed 2026-08-26: Cubeon servers are Paper,
    # always. Paper is vanilla-compatible (same worlds, same clients) and
    # everything else in the server story - plugins, the Smooth-mode stack,
    # Minekube Connect sharing - needs its plugin API anyway. No switcher:
    # one jar type, one code path. The explanation rides on the Install
    # button's tooltip instead of taking two lines of panel text.

    # --- EULA -----------------------------------------------------------

    def on_eula_toggle(e):
        version_id = active_version["value"]
        if not version_id:
            return
        core.set_eula_accepted(version_id, eula_checkbox.value)
        refresh_controls_enabled()
        page.update()

    eula_checkbox = ft.Checkbox(
        value=False,
        label="I accept the Minecraft EULA",
        check_color=BG, active_color=ACCENT, label_style=ft.TextStyle(color=TEXT, size=13),
        tooltip="Read it at aka.ms/MinecraftEULA. The server won't start "
                "until it's accepted - Mojang's rule, not ours.",
        on_change=on_eula_toggle,
    )

    # --- Easy-edit settings ----------------------------------------------

    def text_field(label, width=None, **kw):
        return ft.TextField(
            label=label, width=width, expand=kw.pop("expand", None),
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
            height=52, **kw,
        )

    def _blend_hex(lo_hex: str, hi_hex: str, frac: float) -> str:
        """Blends two "#rrggbb" colors; frac=0 is lo, frac=1 is hi."""
        frac = max(0.0, min(1.0, frac))
        lo = tuple(int(lo_hex[i:i + 2], 16) for i in (1, 3, 5))
        hi = tuple(int(hi_hex[i:i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(lo[c] + (hi[c] - lo[c]) * frac) for c in range(3))
        return "#{:02x}{:02x}{:02x}".format(*mixed)

    def tagged_dropdown(label, options, color_by_option, width=None):
        """A dropdown whose options (and the closed field's text) are each
        colored per `color_by_option`, so the current setting reads at a
        glance by color instead of needing to read the word every time."""
        dd = ft.Dropdown(
            label=label, width=width,
            options=[
                ft.dropdown.Option(
                    key=o,
                    content=ft.Text(o, color=color_by_option.get(o, TEXT), weight=ft.FontWeight.W_600),
                )
                for o in options
            ],
            border_color=BORDER, focused_border_color=ACCENT,
            color=color_by_option.get(options[0], TEXT),
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        )

        def sync_color(e=None):
            dd.color = color_by_option.get(dd.value, TEXT)
            page.update()

        dd.on_change = sync_color
        dd._sync_color = sync_color  # exposed so callers can re-sync after setting .value directly
        return dd

    def gradient_dropdown(label, options, width=None):
        """A tagged_dropdown whose colors are computed as a green -> red blend
        across the option list. Built for Difficulty (peaceful -> hard), but
        works for any ordered "how intense is this" list of options."""
        n = len(options) - 1 or 1
        color_by_option = {o: _blend_hex(ACCENT, DANGER, i / n) for i, o in enumerate(options)}
        return tagged_dropdown(label, options, color_by_option, width=width)

    motd_field = text_field("Server name")
    port_field = text_field("Join port", width=140, keyboard_type=ft.KeyboardType.NUMBER)
    max_players_field = text_field("Player limit", width=140, keyboard_type=ft.KeyboardType.NUMBER)
    seed_field = text_field("World seed")
    # The custom Minekube endpoint - lives here in Settings, next to the
    # online-mode switch it cooperates with, NOT on the console. Blank =
    # Minekube assigns a random free name at startup.
    endpoint_field = text_field(
        "Minekube endpoint (optional)",
        hint_text="my-server  ->  my-server.play.minekube.net")
    endpoint_hint = ft.Text(
        "Blank = random free name.",
        size=11, color=TEXT_DIM,
        tooltip="Your server's free public address. A full domain pointed "
                "at Minekube works too.",
    )

    # --- Whitelist manager ------------------------------------------------
    # The "Only allow invited names" switch is only the gate; this is the
    # actual list of names allowed through it (whitelist.json). Without it
    # the switch just locked everyone out. Add works live: with the server
    # running the entry applies instantly via the console, otherwise it's
    # written to whitelist.json for the next start.
    whitelist_add_field = text_field("Player name", width=200)
    whitelist_status = ft.Text("", size=11, color=TEXT_DIM)
    whitelist_list = ft.Column(spacing=6, wrap=True)

    def refresh_whitelist_list():
        version_id = active_version["value"]
        whitelist_list.controls.clear()
        if not version_id:
            page.update()
            return
        names = core.get_whitelist(version_id)
        if not names:
            whitelist_list.controls.append(ft.Text(
                "Nobody whitelisted yet.", size=11, color=TEXT_DIM,
                tooltip="With the gate on, only names listed here can join.",
            ))
        for name in names:
            def _remove(e, n=name):
                try:
                    core.remove_from_whitelist(active_version["value"], n)
                except Exception as ex:
                    whitelist_status.value = str(ex)
                refresh_whitelist_list()
            whitelist_list.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PERSON_OUTLINE_ROUNDED, size=14, color=TEXT_DIM),
                    ft.Text(name, size=12, color=TEXT, font_family=FONT_MONO),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE_ROUNDED, icon_size=13,
                        icon_color=TEXT_DIM, tooltip=f"Remove {name}",
                        on_click=_remove,
                    ),
                ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=SURFACE_HI, border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
            ))
        page.update()

    def on_whitelist_add(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        name = whitelist_add_field.value or ""
        try:
            core.add_to_whitelist(version_id, name)
            whitelist_status.value = f"Whitelisted {name.strip()}."
            whitelist_status.color = ACCENT
            whitelist_add_field.value = ""
        except ValueError as ex:
            whitelist_status.value = str(ex)
            whitelist_status.color = DANGER
        refresh_whitelist_list()

    whitelist_add_field.on_submit = on_whitelist_add
    whitelist_add_button = ft.Container(
        content=ft.Text("Add", size=12, color=BG, weight=ft.FontWeight.W_700),
        bgcolor=ACCENT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_whitelist_add,
    )

    # --- Security password (CubeonGate) -----------------------------------
    # The owner-set join password. The CubeonGate plugin enforces it per
    # UUID before spawn: no movement/commands/chat until it's answered, a
    # correct answer verifies the UUID permanently (until changed), and
    # failures escalate 10 -> 20 -> 40... minute lockouts that persist
    # across restarts. Only a salted PBKDF2 hash is ever stored.
    gate_password_field = text_field(
        "Server password", width=240, password=True, can_reveal_password=True,
        tooltip="Players verify once per account. 3 wrong tries locks them "
                "out, starting at 10 minutes.")
    gate_status = ft.Text("", size=11, color=TEXT_DIM)

    def update_gate_status():
        version_id = active_version["value"]
        if not version_id:
            gate_status.value = ""
            return
        gate_status.value = ("Password is set - players verify once to join."
                             if core.gate.has_password(version_id)
                             else "No password - anyone who reaches this server can join.")
        gate_status.color = ACCENT if core.gate.has_password(version_id) else DANGER

    def on_gate_set(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        try:
            core.gate.set_password(version_id, gate_password_field.value or "")
        except core.gate.GateError as ex:
            gate_status.value = str(ex)
            gate_status.color = DANGER
            page.update()
            return
        gate_password_field.value = ""
        update_gate_status()
        page.update()

    def on_gate_clear(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        core.gate.clear_password(version_id)
        update_gate_status()
        page.update()

    gate_set_button = ft.Container(
        content=ft.Text("Set password", size=12, color=BG, weight=ft.FontWeight.W_700),
        bgcolor=ACCENT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_gate_set,
    )
    gate_clear_button = ft.Container(
        content=ft.Text("Remove", size=12, color=TEXT_DIM, weight=ft.FontWeight.W_600),
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_gate_clear,
    )
    # Distance caps: Minecraft ENFORCES view-distance / simulation-distance
    # per player SERVER-side - a client can open its own settings to 32
    # chunks, but the server never sends chunks beyond view-distance and
    # never ticks anything beyond simulation-distance. So these two dropdowns
    # are literally "the maximum every player on the server gets", which is
    # the lever that keeps ping and tick rate sane on weak connections.
    # Green -> red gradient reads as cheap -> expensive per connection.
    _render_distance_options = ["4", "6", "8", "10", "12", "16", "20", "32"]
    _simulation_distance_options = ["4", "6", "8", "10", "12", "16", "32"]
    view_distance_dropdown = gradient_dropdown(
        "Render distance", _render_distance_options, width=200)
    view_distance_dropdown.tooltip = (
        "The server never sends chunks beyond this cap, no matter what "
        "clients set. Lower = better ping.")
    sim_distance_dropdown = gradient_dropdown(
        "Simulation distance", _simulation_distance_options, width=200)
    sim_distance_dropdown.tooltip = (
        "How far from each player the server keeps things ticking. "
        "Lower = better tick rate on weak machines.")

    gamemode_dropdown = tagged_dropdown(
        "Gamemode", ["survival", "creative", "adventure", "spectator"],
        {
            "survival": ACCENT,        # the default, grass-green "normal play" color
            "creative": "#5FA8D9",     # cool blue, "build mode"
            "adventure": "#D9A441",    # amber, "exploration/quest" mode
            "spectator": "#8C8FA3",    # muted ghost-gray, you're not really "there"
        },
        width=180,
    )
    difficulty_dropdown = gradient_dropdown("Difficulty", ["peaceful", "easy", "normal", "hard"], width=180)

    # Fixed so every switch card is the same height whether or not it has a
    # hint line underneath - two cards side by side (one with a hint, one
    # without) used to end up visibly mismatched heights in the grid.
    SWITCH_CARD_HEIGHT = 60

    def switch_row(label, hint=None):
        # animated_switch: springs when flipped, even though nothing reads the
        # handler (these values are only read back when the server saves).
        sw = animated_switch(
            active_color=ACCENT,
            # Explicit colors for BOTH states (not just "on") so the two
            # states render as the same size/shape pill and only differ by
            # color - the default theme drew "on" as a filled pill and "off"
            # as a thin outline, which is what made switches look mismatched
            # next to each other.
            track_color={
                ft.ControlState.SELECTED: ACCENT,
                ft.ControlState.DEFAULT: BORDER,
            },
            thumb_color={
                ft.ControlState.SELECTED: BG,
                ft.ControlState.DEFAULT: TEXT_DIM,
            },
            track_outline_color=ft.Colors.TRANSPARENT,
        )
        row_children = [ft.Text(label, size=13, color=TEXT, expand=True), sw]
        # Hints live in the card's tooltip, not on the card: the settings
        # panel is meant to read at a glance, and hover-for detail keeps the
        # card short without losing the explanation for whoever wants it.
        card = ft.Container(
            content=ft.Row(row_children),
            bgcolor=SURFACE_HI, border_radius=RADIUS, padding=12, expand=True,
            height=SWITCH_CARD_HEIGHT,
        )
        if hint:
            card.tooltip = hint
        return sw, card

    pvp_switch, pvp_row = switch_row("PvP")
    whitelist_switch, whitelist_row = switch_row("Whitelist only")
    online_mode_switch, online_mode_row = switch_row(
        "Premium accounts only",
        "Keep this off for Cubeon/offline names, or players may get locked out.",
    )
    allow_flight_switch, allow_flight_row = switch_row("Allow flying")

    # Same green -> red gradient treatment as the Settings-tab RAM slider,
    # and - critically - the same machine-bounded ceiling. The old slider was
    # hardcoded min=1024/max=16384, so on an 8 GB machine the user could still
    # drag the server allocation up to 16 GB and hand Java an -Xmx bigger than
    # physically exists (the exact bug already fixed for the client RAM slider
    # in main.py). Now max = detected system RAM, the recommended half-point is
    # a labelled threshold, and going above it warns instead of silently
    # over-allocating.
    server_system_ram_mb = core.get_system_ram_mb()
    server_recommended_ram_mb = core.recommended_max_ram_mb(server_system_ram_mb)
    server_ram_min_mb = 1024
    server_ram_max_mb = max(server_system_ram_mb, server_ram_min_mb + 512)
    # Clamp a previously-saved value that's now impossible (config copied from
    # a beefier PC, RAM removed, or the old 16 GB ceiling left a stale 16384).
    _saved_server_ram = cfg.get("server_ram_mb", 2048)
    if _saved_server_ram > server_ram_max_mb:
        _saved_server_ram = min(server_recommended_ram_mb, server_ram_max_mb)
    if _saved_server_ram < server_ram_min_mb:
        _saved_server_ram = server_ram_min_mb
    cfg["server_ram_mb"] = _saved_server_ram
    _server_ram_divisions = max(1, min(32, (server_ram_max_mb - server_ram_min_mb) // 256 or 1))

    def _server_ram_color(value: float) -> str:
        """Green up to the recommended half-point, then blends toward red as
        you push further above it, reaching full red at the machine's max."""
        if value <= server_recommended_ram_mb:
            return ACCENT
        span = max(server_ram_max_mb - server_recommended_ram_mb, 1)
        return _blend_hex(ACCENT, DANGER, (value - server_recommended_ram_mb) / span)

    server_ram_slider = ft.Slider(
        min=server_ram_min_mb, max=server_ram_max_mb, divisions=_server_ram_divisions,
        value=cfg["server_ram_mb"],
        active_color=_server_ram_color(cfg["server_ram_mb"]), inactive_color=SURFACE_HI,
        thumb_color=_server_ram_color(cfg["server_ram_mb"]),
        label="{value} MB",
    )
    server_ram_label = ft.Text(
        f"{cfg['server_ram_mb']} MB allocated", size=13, color=TEXT_DIM, font_family=FONT_MONO,
    )
    server_ram_range_row = ft.Row(
        [
            ft.Text(f"{server_ram_min_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"Recommended: {server_recommended_ram_mb} MB (half of {server_system_ram_mb} MB detected)",
                    size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"{server_ram_max_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    server_ram_warning = ft.Text("", size=12, color=DANGER, font_family=FONT_MONO, visible=False)

    def _update_server_ram_warning(value: int):
        if value > server_recommended_ram_mb:
            server_ram_warning.value = (
                f"⚠ Above the recommended half-point ({server_recommended_ram_mb} MB). "
                f"The server and your computer share this RAM - allocating too much can "
                f"starve everything else or cause instability."
            )
            server_ram_warning.visible = True
        else:
            server_ram_warning.visible = False

    _update_server_ram_warning(cfg["server_ram_mb"])

    def on_server_ram_change(e):
        value = int(server_ram_slider.value)
        color = _server_ram_color(value)
        server_ram_slider.active_color = color
        server_ram_slider.thumb_color = color
        server_ram_label.value = f"{value} MB allocated"
        _update_server_ram_warning(value)
        cfg["server_ram_mb"] = value
        core.save_config(cfg)
        page.update()

    server_ram_slider.on_change = on_server_ram_change

    # --- High-ping / low-latency optimization -----------------------------

    # Live progress for the auto-install that Smooth mode kicks off (Cubeon's
    # own low-ping stack: LagFixer + Chunky + FarmControl on Paper servers).
    smooth_progress_text = ft.Text("", size=12, color=TEXT_DIM)
    smooth_progress_ring = ft.ProgressRing(width=14, height=14, stroke_width=2, color=ACCENT)
    smooth_progress_bar = ft.ProgressBar(width=280, height=6, color=ACCENT,
                                         bgcolor=SURFACE_HI, value=None)
    smooth_progress_row = ft.Row(
        [smooth_progress_ring,
         ft.Column([smooth_progress_text, smooth_progress_bar], spacing=4, expand=True)],
        spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, visible=False)
    # Generation counter: each install bumps it; completion timers from an
    # older run check it before hiding the row, so a fresh install's progress
    # can never be dismissed by a stale timer.
    _smooth_gen = {"v": 0}

    def _smooth_progress(ev):
        """Runs on the install worker thread; refresh() is thread-safe."""
        stage = ev.get("stage")
        title = ev.get("title", "")
        if stage == "start":
            smooth_progress_text.value = f"Installing {title}..."
            smooth_progress_bar.value = None   # indeterminate until bytes flow
        elif stage == "progress":
            total = ev.get("total") or 0
            done = ev.get("done") or 0
            if total:
                smooth_progress_bar.value = done / total
                smooth_progress_text.value = f"Downloading {title}... {int(done * 100 / max(total, 1))}%"
            else:
                smooth_progress_text.value = f"Downloading {title}... {done // 1024} KB"
        elif stage == "done":
            if not ev.get("ok"):
                smooth_progress_text.value = f"Couldn't install {title}."
        # Per-file progress events: repaint just the progress row.
        thread_safe_ui.refresh(smooth_progress_row)

    def _smooth_install_worker(version_id, gen):
        try:
            res = core.ensure_smooth_mode_plugins(version_id, progress_cb=_smooth_progress)
        except Exception as ex:
            _smooth_finish(gen, f"Auto-install failed: {ex}")
            return
        bits = []
        if res["installed"]:
            bits.append("Installed " + ", ".join(res["installed"]))
        if res["present"]:
            bits.append("already had " + ", ".join(res["present"]))
        for title, why in res["failed"]:
            bits.append(f"{title} failed ({why})")
        if res["skipped_reason"]:
            settings_status.value = res["skipped_reason"]
            _smooth_finish(gen, None)
        elif bits:
            _smooth_finish(gen, ". ".join(bits) + ". Takes effect next server start.")
        refresh_plugins_list()
        page.update()

    def _smooth_finish(gen, message):
        """Work is over: drop the spinner and the (full) bar immediately so
        the row stops looking 'busy', show the summary, and dismiss the whole
        row a few seconds later - unless a newer install has started, which
        the generation check catches."""
        if gen != _smooth_gen["v"]:
            return
        smooth_progress_ring.visible = False
        smooth_progress_bar.visible = False
        if message:
            smooth_progress_text.value = message
        page.update()

        def _dismiss(g):
            if g != _smooth_gen["v"]:
                return   # a new install took over the row
            smooth_progress_row.visible = False
            smooth_progress_ring.visible = True
            smooth_progress_bar.visible = True
            page.update()
        threading.Timer(7.0, _dismiss, args=(gen,)).start()

    def on_high_ping_toggle(e):
        version_id = active_version["value"]
        if not version_id:
            return
        core.set_high_ping_optimization(version_id, high_ping_switch.value)
        settings_status.value = (
            "High-ping optimization applied. Takes effect next server start."
            if high_ping_switch.value else
            "High-ping optimization reverted to defaults."
        )
        if high_ping_switch.value and version_id:
            # Cubeon doesn't just RECOMMEND performance plugins - switching
            # Smooth mode on INSTALLS the curated low-ping stack (Paper
            # servers), with live download progress below.
            _smooth_gen["v"] += 1   # invalidates any stale dismiss timer
            smooth_progress_row.visible = True
            smooth_progress_ring.visible = True
            smooth_progress_bar.visible = True
            smooth_progress_bar.value = None
            smooth_progress_text.value = "Setting up smooth mode..."
            threading.Thread(target=_smooth_install_worker, args=(version_id, _smooth_gen["v"]),
                             name="smooth-mode-plugin-install", daemon=True).start()
        else:
            # Turning it off leaves installed plugins in place - they're
            # harmless when disabled via their config, and uninstalling
            # something a user may want anyway would be surprising.
            smooth_progress_row.visible = False
        page.update()

    high_ping_switch, high_ping_row = switch_row(
        "Smooth mode for laggy friends",
        "Lighter settings for players on slow connections.",
    )
    high_ping_switch.on_change = on_high_ping_toggle

    # --- Open server folder -------------------------------------------------

    def on_open_folder_click(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        try:
            core.open_server_folder(version_id)
        except Exception as ex:
            settings_status.value = f"Couldn't open folder: {ex}"
            page.update()

    open_folder_button = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=16, color=TEXT),
             ft.Text("Open server folder", size=13, color=TEXT, weight=ft.FontWeight.W_600)],
            spacing=8, tight=True,
        ),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=14, vertical=11),
        ink=False, on_click=on_open_folder_click,
    )

    settings_status = ft.Text("", size=12, color=TEXT_DIM)

    # --- Delete this version's server ---------------------------------------

    def _open_dialog(dlg):
        # Shared cross-Flet dialog plumbing (Flet 0.86: show_dialog/pop_dialog).
        from cubeon import dialogs as cubeon_dialogs
        cubeon_dialogs.open_dialog(page, dlg)

    def _close_dialog(dlg):
        from cubeon import dialogs as cubeon_dialogs
        cubeon_dialogs.close_dialog(page, dlg)

    def on_delete_server_click(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        if not core.is_server_installed(version_id):
            settings_status.value = "Nothing to delete. No server installed for this version."
            page.update()
            return
        # A running (or orphaned/leftover) server can't be deleted from under
        # itself - surface the same remedy the Console tab uses.
        if core.is_server_running(version_id):
            settings_status.value = "Stop the server first. It's still running."
            page.update()
            return

        def confirm(e=None):
            _close_dialog(dlg)
            try:
                core.delete_server(version_id)
            except (RuntimeError, ValueError) as ex:
                settings_status.value = str(ex)
                page.update()
                return
            settings_status.value = f"Deleted the server for {version_id}."
            # Server's gone - the tab must fall back to "Install server",
            # hide Paper-only Plugins, disable Start, etc.
            plugins_tab_visible["value"] = False
            refresh_plugins_visibility()
            refresh_server_tab()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Delete server?", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"This permanently deletes the server for '{version_id}'. "
                                "Its world, settings and any plugins are removed.", size=13, color=TEXT),
                        ft.Text("Your game installs, mods and skins are not affected.",
                                size=12, color=TEXT_DIM),
                    ],
                    spacing=8, tight=True,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: _close_dialog(dlg)),
                ft.TextButton("Delete", on_click=confirm, style=ft.ButtonStyle(color=DANGER)),
            ],
        )
        _open_dialog(dlg)

    delete_server_button = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, size=16, color=DANGER),
             ft.Text("Delete server", size=13, color=DANGER, weight=ft.FontWeight.W_600)],
            spacing=8, tight=True,
        ),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, DANGER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=14, vertical=11),
        ink=False, on_click=on_delete_server_click,
    )

    def on_save_settings(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        props = core.get_server_properties(version_id)
        props["motd"] = motd_field.value or DEFAULT_MOTD
        props["server-port"] = (port_field.value or "25565").strip()
        props["max-players"] = (max_players_field.value or "20").strip()
        props["level-seed"] = seed_field.value or ""
        props["view-distance"] = str(core.clamp_distance(
            view_distance_dropdown.value, core.VIEW_DISTANCE_RANGE, 10))
        props["simulation-distance"] = str(core.clamp_distance(
            sim_distance_dropdown.value, core.SIMULATION_DISTANCE_RANGE, 10))
        props["gamemode"] = gamemode_dropdown.value or "survival"
        props["difficulty"] = difficulty_dropdown.value or "normal"
        props["pvp"] = "true" if pvp_switch.value else "false"
        props["white-list"] = "true" if whitelist_switch.value else "false"
        props["online-mode"] = "true" if online_mode_switch.value else "false"
        props["allow-flight"] = "true" if allow_flight_switch.value else "false"
        core.save_server_properties(version_id, props)
        # The endpoint is saved with everything else - Settings is the one
        # place server identity is configured. Invalid input keeps the
        # properties save (already written) but reports the problem.
        try:
            clean_endpoint = core.minekube.validate_endpoint(endpoint_field.value)
        except ValueError as ex:
            settings_status.value = str(ex)
            page.update()
            return
        try:
            core.minekube.ensure_config(
                version_id,
                endpoint=clean_endpoint,
                allow_offline=props["online-mode"] != "true")
        except Exception:
            pass
        settings_status.value = "Saved. Applies next time the server starts."
        page.update()

    DEFAULT_MOTD = core.DEFAULT_SERVER_PROPERTIES["motd"]

    save_settings_button = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.SAVE_ROUNDED, color=BG, size=16),
             ft.Text("Save", color=BG, weight=ft.FontWeight.W_800, size=13)],
            spacing=7, tight=True,
        ),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(horizontal=18, vertical=12),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_save_settings,
    )

    # The settings card used to be one long wall of sections. Basics - the
    # things you touch while playing - stay visible; everything you set once
    # and forget (public address, join password, Smooth mode, RAM) collapses
    # behind an "Advanced options" toggle that starts closed.
    advanced_open = {"v": False}

    def _toggle_advanced(e=None):
        advanced_open["v"] = not advanced_open["v"]
        advanced_body.visible = advanced_open["v"]
        advanced_chevron.name = (ft.Icons.EXPAND_LESS if advanced_open["v"]
                                 else ft.Icons.EXPAND_MORE)
        page.update()

    advanced_chevron = ft.Icon(ft.Icons.EXPAND_MORE, size=18, color=TEXT_DIM)
    advanced_header = ft.Container(
        content=ft.Row(
            [advanced_chevron,
             ft.Text("Advanced options", size=13, color=TEXT,
                     weight=ft.FontWeight.W_700),
             ft.Container(expand=True),
             ft.Text("Address, password, RAM",
                     size=11, color=TEXT_DIM)],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE_HI, border_radius=RADIUS, ink=False,
        on_click=_toggle_advanced,
        padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
    )
    advanced_body = ft.Column(
        [
            ft.Container(height=4),
            pixel_divider(),
            ft.Container(height=4),
            section_label("Public address (Minekube)"),
            endpoint_field,
            endpoint_hint,
            ft.Container(height=4),
            pixel_divider(),
            ft.Container(height=4),
            section_label("Security password"),
            ft.Row([gate_password_field, gate_set_button,
                    gate_clear_button, gate_status], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=4),
            pixel_divider(),
            ft.Container(height=4),
            section_label("Make it smoother"),
            ft.Row([high_ping_row], spacing=12),
            smooth_progress_row,
            ft.Container(height=4),
            pixel_divider(),
            ft.Container(height=4),
            ft.Row(
                [
                    section_label("Server power"),
                    ft.Container(expand=True),
                    server_ram_label,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            server_ram_slider,
            server_ram_range_row,
            server_ram_warning,
            ft.Container(height=8),
            ft.Row([open_folder_button, delete_server_button], spacing=12),
        ],
        spacing=12, visible=False,
    )

    settings_panel = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        section_label("Server settings"),
                        ft.Container(expand=True),
                        settings_status,
                        save_settings_button,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([ft.Container(content=motd_field, expand=2), ft.Container(content=seed_field, expand=2)], spacing=12),
                ft.Row([port_field, max_players_field, view_distance_dropdown, sim_distance_dropdown], spacing=12),
                ft.Row([gamemode_dropdown, difficulty_dropdown], spacing=12),
                ft.Row([pvp_row, whitelist_row], spacing=12),
                ft.Row([online_mode_row, allow_flight_row], spacing=12),
                ft.Container(height=4),
                section_label("Whitelist"),
                ft.Row([whitelist_add_field, whitelist_add_button,
                        whitelist_status], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                whitelist_list,
                ft.Container(height=4),
                advanced_header,
                advanced_body,
            ],
            spacing=12,
        ),
        bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
    )

    # --- Start/stop + live console ---------------------------------------

    status_dot = ft.Container(width=10, height=10, border_radius=RADIUS, bgcolor=TEXT_DIM)
    status_text = ft.Text("Stopped", size=15, color=TEXT_DIM, font_family=FONT_MONO, weight=ft.FontWeight.W_600)
    address_text = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)

    # Console lines are colorized by rough severity so a wall of log text is
    # actually scannable - errors/warnings pop, chat/join lines stay dim.
    def _console_line_color(line: str) -> str:
        lowered = line.lower()
        if "/error" in lowered or "exception" in lowered:
            return DANGER
        if "/warn" in lowered:
            return "#D6A94A"
        if "done (" in lowered or "for help, type" in lowered:
            return ACCENT
        return TEXT_DIM

    console_log = ft.ListView(expand=True, spacing=1, auto_scroll=True)
    console_line_count = ft.Text("0 lines", size=11, color=TEXT_FAINT, font_family=FONT_MONO)

    # Pending page.update callbacks + one-shot flush flag for the coalesced
    # console repaint (see append_console below).
    pending_flush = []
    flush_scheduled = {"v": False}

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    # Plugin library downloads (AuthMe's SpigotLibraryLoader pulls a dozen
    # maven jars on first boot) fire one identical-looking line per file.
    # Printed raw, they flood the console and push the log off-screen, so
    # consecutive download lines collapse into ONE updating progress line.
    _LIB_DOWNLOAD_RE = re.compile(r"\[SpigotLibraryLoader\]\s*Downloading\s+(\S+)")
    lib_dl = {"count": 0}

    def append_console(line: str):
        # Plugins like LagFixer print ANSI colour escapes even when piped;
        # raw, they render as "[38;5;11m⚡[0m" garbage in every other line.
        # Stripped here (display only) - logs/latest.log keeps its codes.
        line = _ANSI_RE.sub("", line)

        # Collapse library-download spam into a single live line.
        lib_match = _LIB_DOWNLOAD_RE.search(line)
        if lib_match:
            lib_dl["count"] += 1
            jar = lib_match.group(1).rsplit("/", 1)[-1]
            text = (f"[plugins] Downloading plugin libraries... "
                    f"{lib_dl['count']} so far (latest: {jar}). One time "
                    f"only, happens after installing a new plugin.")
            with thread_safe_ui.TREE_LOCK:
                last = console_log.controls[-1] if console_log.controls else None
                if last is not None and getattr(last, "data", None) == "lib-dl":
                    last.value = text
                else:
                    console_log.controls.append(
                        ft.Text(text, size=12.5, color=TEXT_DIM,
                                font_family=FONT_MONO, selectable=True,
                                data="lib-dl"))
                if len(console_log.controls) > 800:
                    del console_log.controls[: len(console_log.controls) - 800]
                pending_flush.append(console_flush_target)
                if flush_scheduled["v"]:
                    return
                flush_scheduled["v"] = True
            threading.Timer(0.08, _flush_console).start()
            return
        lib_dl["count"] = 0

        # Console floods at server-start time (dozens of lines/second). Two
        # guards here, both needed - see cubeon/thread_safe_ui.py's TREE_LOCK:
        #   1. mutation + update run under the shared tree lock, so Flet's
        #      diff can never walk this list mid-append (the IndexError inside
        #      _compare_lists users hit when starting a server).
        #   2. bursts are coalesced onto one flush ~80ms out, so 50 rapid
        #      lines cost ONE repaint instead of 50.
        with thread_safe_ui.TREE_LOCK:
            # Commands you sent echo as shell-style prompt lines - bright with
            # an accent caret, distinct from the server's own chatter.
            is_prompt = line.startswith("> ")
            console_log.controls.append(
                ft.Text(line, size=12, color=ACCENT if is_prompt else _console_line_color(line),
                         weight=ft.FontWeight.W_600 if is_prompt else ft.FontWeight.W_400,
                         font_family=FONT_MONO, selectable=True)
            )
            if len(console_log.controls) > 800:
                del console_log.controls[: len(console_log.controls) - 800]
            console_line_count.value = f"{len(console_log.controls)} lines"
            pending_flush.append(console_flush_target)
            if flush_scheduled["v"]:
                return
            flush_scheduled["v"] = True
        threading.Timer(0.08, _flush_console).start()

    def _flush_console():
        with thread_safe_ui.TREE_LOCK:
            flush_scheduled["v"] = False
            callbacks = pending_flush[:]
            pending_flush.clear()
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass

    def console_flush_target():
        """Control-level repaint of just the console region (list + counter).

        Server start floods dozens of lines/second; each used to cost a
        full-tree diff. The whole console lives in two controls, so this
        repaints only those."""
        thread_safe_ui.refresh(console_log)
        thread_safe_ui.refresh(console_line_count)

    def clear_console(e=None):
        with thread_safe_ui.TREE_LOCK:
            console_log.controls.clear()
            console_line_count.value = "0 lines"
        console_flush_target()

    # --- Quick actions - one-tap common commands, no typing required -----

    def quick_command(cmd_template, needs_name=False):
        def handler(e=None):
            version_id = active_version["value"]
            if not version_id or not core.is_server_running(version_id):
                return
            if needs_name:
                name = (command_field.value or "").strip()
                if not name:
                    command_field.error_text = "Enter a username above first"
                    page.update()
                    return
                command_field.error_text = None
                cmd = cmd_template.format(name=name)
            else:
                cmd = cmd_template
            try:
                _send_console_command(version_id, cmd)
            except Exception as ex:
                append_console(f"[couldn't send command: {ex}]")
            page.update()
        return handler

    def quick_button(label, icon, on_click):
        return ft.Container(
            content=ft.Row(
                [ft.Icon(icon, size=15, color=TEXT), ft.Text(label, size=12.5, color=TEXT, weight=ft.FontWeight.W_600)],
                spacing=6, tight=True,
            ),
            bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=9),
            ink=False, on_click=on_click,
        )

    quick_actions_row = ft.Row(
        [
            quick_button("Op", ft.Icons.SHIELD_ROUNDED, quick_command("op {name}", needs_name=True)),
            quick_button("Whitelist add", ft.Icons.PERSON_ADD_ROUNDED, quick_command("whitelist add {name}", needs_name=True)),
            quick_button("Kick", ft.Icons.LOGOUT_ROUNDED, quick_command("kick {name}", needs_name=True)),
            quick_button("Save world", ft.Icons.SAVE_ROUNDED, quick_command("save-all")),
            quick_button("List players", ft.Icons.GROUPS_ROUNDED, quick_command("list")),
        ],
        spacing=8, wrap=True,
    )

    def set_running_ui(running: bool, busy=False, busy_label="Starting..."):
        if busy:
            status_dot.bgcolor = ACCENT_DIM
            status_text.value, status_text.color = busy_label, TEXT_DIM
        elif running:
            status_dot.bgcolor = ACCENT
            status_text.value, status_text.color = "Running", ACCENT
        else:
            status_dot.bgcolor = TEXT_DIM
            status_text.value, status_text.color = "Stopped", TEXT_DIM
        start_stop_button.content.value = "Stop server" if running else "Start server"
        start_stop_button.bgcolor = DANGER if running else ACCENT
        start_stop_button.disabled = busy
        restart_button.disabled = busy or not running
        command_field.disabled = not running
        send_command_button.disabled = not running
        version_id = active_version["value"]
        if running and version_id:
            props = core.get_server_properties(version_id)
            port = props.get("server-port", "25565")
            address_text.value = f"LAN address: {core.get_local_lan_address()}:{port}"
            _refresh_public_address_line()
        else:
            address_text.value = ""
            _refresh_public_address_line()
        refresh_controls_enabled()
        page.update()

    def _show_snack(text: str):
        """Shows a snackbar via the shared cross-Flet plumbing; falls back to
        a console line if even that can't run."""
        from cubeon import dialogs as cubeon_dialogs
        try:
            cubeon_dialogs.show_snack(page, text)
        except Exception:
            append_console(f"[hint] {text}")

    def _start_blocked_reason(version_id: str | None) -> str | None:
        """Why Start can't run right now, in plain language - or None if it can."""
        if not version_id:
            return "Select a version on the Play tab first."
        if install_in_progress["value"]:
            return "Wait for the install to finish."
        if not core.is_server_installed(version_id):
            return ("The server isn't installed yet. Go to Servers > Settings "
                    "and tap Install first.")
        if not core.eula_accepted(version_id):
            return "Accept the Minecraft EULA in Servers > Settings first."
        return None

    def refresh_controls_enabled():
        """Settings/install/eula/start controls are only meaningful once a
        version is selected, and starting needs the jar + EULA in place."""
        version_id = active_version["value"]
        has_version = bool(version_id)
        installed = has_version and core.is_server_installed(version_id)
        accepted = has_version and core.eula_accepted(version_id)
        running = has_version and core.is_server_running(version_id)

        install_button.disabled = (not has_version) or install_in_progress["value"]
        eula_checkbox.disabled = not has_version
        for ctrl in (motd_field, port_field, max_players_field, seed_field,
                     endpoint_field, endpoint_hint,
                     whitelist_add_field, whitelist_add_button,
                     gate_password_field, gate_set_button, gate_clear_button,
                     view_distance_dropdown, sim_distance_dropdown,
                     gamemode_dropdown, difficulty_dropdown, save_settings_button,
                     pvp_switch, whitelist_switch, online_mode_switch, allow_flight_switch,
                     high_ping_switch):
            ctrl.disabled = not has_version
        open_folder_button.disabled = not has_version
        # Start stays CLICKABLE unless there's genuinely nothing to act on -
        # a disabled Flet Container keeps its bright styling, so users tap it
        # and nothing happens with no explanation. A blocked-but-clickable
        # button answers with a snackbar instead (see on_start_stop_click).
        start_stop_button.disabled = (not has_version) or install_in_progress["value"]
        restart_button.disabled = (not has_version) or (not installed) or (not running)
        # Dim whichever buttons are actually dead, so "disabled" is visible
        # and not just silently eating clicks.
        start_stop_button.opacity = 0.45 if start_stop_button.disabled else 1.0
        restart_button.opacity = 0.45 if restart_button.disabled else 1.0

    def _start_worker(version_id, on_started=None):
        """Actually launches the process and wires up its console/exit
        callbacks. Shared by Start and Restart so they behave identically.
        Starting IS sharing now: the Minekube Connect plugin and config are
        ensured right here, so there's no separate enable button to forget."""
        with thread_safe_ui.TREE_LOCK:
            console_log.controls.clear()
            console_line_count.value = "0 lines"
            pending_flush.clear()

        def on_output(line):
            if active_version["value"] == version_id:
                append_console(line)

        def on_exit(code):
            if active_version["value"] == version_id:
                append_console(f"[server exited, code {code}]")
                set_running_ui(False)
            # Milestones: hosting a server for friends counts once per
            # start->exit cycle. Clean exit or crash both count - the
            # world WAS hosted either way.
            try:
                core.milestones_add_hosted()
                for m in core.milestones_evaluate():
                    append_console(f"[unlocked: {core.milestone_name(m)} hat]")
            except Exception:
                pass  # cosmetic; the console must never die on this

        try:
            _ensure_minekube_ready(version_id, append_console)
            java_path = cfg.get("java_path") or None
            ram = cfg.get("server_ram_mb", 2048)
            core.start_server(version_id, ram, java_path, on_output=on_output, on_exit=on_exit)
            if active_version["value"] == version_id:
                set_running_ui(True)
        except Exception as ex:
            append_console(f"[failed to start: {ex}]")
            if active_version["value"] == version_id:
                set_running_ui(False)
                # A leftover server is the most likely cause of a start failure,
                # and the Stop button for it has to appear now - not on the next
                # tab switch, which is when the user has already given up.
                refresh_orphan_notice()
        finally:
            if on_started:
                on_started()

    def on_start_stop_click(e=None):
        version_id = active_version["value"]
        # A blocked-but-clickable Start explains itself instead of doing nothing.
        reason = _start_blocked_reason(version_id)
        if reason is not None:
            _show_snack(reason)
            return

        if core.is_server_running(version_id):
            set_running_ui(True, busy=True, busy_label="Stopping...")

            def status_cb(text):
                if active_version["value"] == version_id:
                    status_text.value = text
                    page.update()

            def stop_worker():
                core.stop_server(version_id, status_cb=status_cb)
                if active_version["value"] == version_id:
                    set_running_ui(False)

            threading.Thread(target=stop_worker, daemon=True).start()
            return

        set_running_ui(False, busy=True, busy_label="Starting...")
        threading.Thread(target=_start_worker, args=(version_id,), daemon=True).start()

    def on_restart_click(e=None):
        version_id = active_version["value"]
        if not version_id or not core.is_server_installed(version_id):
            return

        def status_cb(text):
            if active_version["value"] == version_id:
                status_text.value = text
                page.update()

        def restart_worker():
            if core.is_server_running(version_id):
                set_running_ui(True, busy=True, busy_label="Restarting (stopping)...")
                core.stop_server(version_id, status_cb=status_cb)
            if active_version["value"] != version_id:
                return
            set_running_ui(False, busy=True, busy_label="Restarting (starting)...")
            _start_worker(version_id)

        threading.Thread(target=restart_worker, daemon=True).start()

    start_stop_button = ft.Container(
        content=ft.Text("Start server", color=BG, weight=ft.FontWeight.W_700, size=14),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(vertical=13, horizontal=20),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_start_stop_click, width=180,
    )

    restart_button = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.RESTART_ALT_ROUNDED, size=16, color=TEXT), ft.Text("Restart", size=13, color=TEXT, weight=ft.FontWeight.W_600)],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=13, horizontal=16),
        alignment=ft.Alignment.CENTER, ink=False, on_click=on_restart_click, disabled=True,
    )

    def on_stop_orphan_click(e=None):
        """Shuts down a server left behind by a previous Cubeon run.

        Only reachable when one exists. Cubeon can't talk to that process - no
        stdin, no console - so the normal Stop button can't help; this signals
        the PID the world lock itself reported.
        """
        version_id = active_version["value"]
        if not version_id:
            return
        pid = core.is_server_orphaned(version_id)
        if not pid:
            refresh_orphan_notice()
            return

        stop_orphan_button.disabled = True
        append_console(f"[stopping leftover server, process {pid}...]")
        page.update()

        def worker():
            ok = core.stop_orphaned_server(version_id)
            if active_version["value"] != version_id:
                return
            append_console("[leftover server stopped, you can start now]" if ok
                           else "[couldn't stop it; try closing it yourself]")
            stop_orphan_button.disabled = False
            refresh_orphan_notice()
            set_running_ui(core.is_server_running(version_id))

        threading.Thread(target=worker, daemon=True).start()

    stop_orphan_button = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.WARNING_ROUNDED, size=16, color=BG),
             ft.Text("Stop leftover server", size=13, color=BG,
                     weight=ft.FontWeight.W_700)],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor=DANGER, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=13, horizontal=16),
        alignment=ft.Alignment.CENTER, ink=False,
        on_click=on_stop_orphan_click, visible=False,
    )
    orphan_notice = ft.Text("", size=12, color=DANGER, font_family=FONT_MONO,
                            visible=False)

    def refresh_orphan_notice():
        """Surfaces a server Cubeon lost track of, instead of letting the next
        Start die on `session.lock: already locked` with no explanation."""
        version_id = active_version["value"]
        pid = core.is_server_orphaned(version_id) if version_id else None
        stop_orphan_button.visible = bool(pid)
        orphan_notice.visible = bool(pid)
        if pid:
            orphan_notice.value = (
                f"A server from an earlier Cubeon session is still running "
                f"and is holding this world. Stop it before starting a new one.")
        page.update()

    def _send_console_command(version_id: str, text: str):
        """Sends a console command on a background thread - the stdin pipe
        can block for a moment if the server is mid-startup, and doing that
        on the UI thread froze the whole console."""
        def worker():
            try:
                core.send_server_command(version_id, text)
                append_console(f"> {text}")
            except Exception as ex:
                append_console(f"[couldn't send command: {ex}]")
            page.update()
        threading.Thread(target=worker, daemon=True).start()

    def on_send_command(e=None):
        version_id = active_version["value"]
        text = (command_field.value or "").strip()
        if not version_id or not text:
            return
        _send_console_command(version_id, text)
        command_field.value = ""
        command_field.error_text = None
        page.update()

    command_field = ft.TextField(
        hint_text="type a command, press Enter",
        border=ft.InputBorder.NONE, content_padding=ft.padding.Padding.symmetric(horizontal=4, vertical=10),
        color=TEXT, hint_style=ft.TextStyle(color=TEXT_FAINT, size=13, font_family=FONT_MONO),
        cursor_color=ACCENT, bgcolor=None,
        height=40, expand=True, text_style=ft.TextStyle(font_family=FONT_MONO, size=13),
        disabled=True, filled=False,
        on_submit=on_send_command,
    )
    send_command_button = ft.Container(
        content=ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, size=16, color=BG),
        bgcolor=ACCENT, border_radius=RADIUS, padding=9, ink=False,
        on_click=on_send_command, disabled=True,
    )

    # The terminal: one dark window with a titlebar (traffic lights + live
    # line count + clear) and the command input docked in a footer with a
    # shell prompt glyph - reads as "a console", not a form.
    terminal_container = ft.Container(
        bgcolor="#0A0C08",
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS,
        content=ft.Column(
            [
                # titlebar
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(width=9, height=9, border_radius=100, bgcolor="#5A6152"),
                            ft.Container(width=9, height=9, border_radius=100, bgcolor="#4A4F45"),
                            ft.Container(width=9, height=9, border_radius=100, bgcolor="#3A3F37"),
                            ft.Container(width=6),
                            ft.Text("server-console", size=12, color=TEXT_DIM, font_family=FONT_MONO),
                            ft.Container(expand=True),
                            console_line_count,
                            ft.Container(width=10),
                            ft.Container(
                                content=ft.Row(
                                    [ft.Icon(ft.Icons.CLEAR_ALL_ROUNDED, size=13, color=TEXT_DIM),
                                     ft.Text("Clear", size=12, color=TEXT_DIM, font_family=FONT_MONO)],
                                    spacing=4, tight=True,
                                ),
                                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
                                border_radius=RADIUS, ink=False, on_click=clear_console,
                                tooltip="Clear the log",
                            ),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=7),
                ),
                ft.Container(height=1, bgcolor=BORDER, margin=ft.margin.Margin.symmetric(horizontal=1)),
                # log body - FIXED height, not expand: the Console view is a
                # scrolling column, and inside a scrollable parent expand
                # collapses to zero (the old log did the same trick with a
                # 440px box). The ListView inside scrolls on its own.
                ft.Container(content=console_log, height=430, padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8)),
                # footer prompt
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("❯", size=13, color=ACCENT, font_family=FONT_MONO, weight=ft.FontWeight.W_700),
                            command_field,
                            send_command_button,
                        ],
                        spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#11140E",
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=5),
                ),
            ],
            spacing=0, tight=True,
        ),
    )

    # --- Plugins view (the "Servers > Plugins" sidebar sub-item, Paper only) -

    plugins_tab_visible = {"value": False}  # only meaningful once we know main.py's nav; see refresh_plugins_visibility

    plugins_not_paper_notice_text = ft.Text(
        "", size=13, color=TEXT_DIM,
    )
    plugins_not_paper_notice = ft.Container(
        content=plugins_not_paper_notice_text,
        bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=16,
        visible=True,
    )

    installed_plugins_list = ft.Column(spacing=8)
    installed_plugins_count = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    plugins_show_all = {"value": False}

    # --- Browse / Installed view state (panes built after their children) ---
    plugins_active_view = {"value": "browse"}
    plugins_browse_pane = None   # constructed below, once the market controls exist
    plugins_installed_pane = None

    def refresh_plugins_list():
        version_id = active_version["value"]
        installed_plugins_list.controls.clear()
        if not version_id or core.get_server_type(version_id) != core.SERVER_TYPE_PAPER:
            installed_plugins_count.value = ""
            thread_safe_ui.refresh(installed_plugins_list)
            thread_safe_ui.refresh(installed_plugins_count)
            _build_plugins_view_segment()
            return
        plugins = core.list_plugins(version_id)
        installed_plugins_count.value = f"{len(plugins)} plugin(s)"
        if not plugins:
            installed_plugins_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, size=20, color=TEXT_DIM),
                                width=40, height=40, bgcolor=SURFACE, border_radius=RADIUS,
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.Text("No plugins installed yet", size=14, color=TEXT, weight=ft.FontWeight.W_700),
                                    ft.Text("Pick one above and it lands here.", size=12, color=TEXT_DIM),
                                ],
                                spacing=2, expand=True,
                            ),
                        ],
                        spacing=12,
                    ),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, BORDER),
                    border_radius=RADIUS,
                    padding=14,
                )
            )
        visible_plugins = plugins if plugins_show_all["value"] else plugins[:5]
        for p in visible_plugins:
            installed_plugins_list.controls.append(_plugin_row(p))
        if len(plugins) > 5:
            installed_plugins_list.controls.append(
                ft.Container(
                    content=ft.Text(
                        "Show fewer" if plugins_show_all["value"] else f"Show all installed ({len(plugins) - 5} more)",
                        size=12, color=ACCENT, weight=ft.FontWeight.W_700,
                    ),
                    padding=ft.padding.Padding.symmetric(vertical=8, horizontal=10),
                    border_radius=RADIUS,
                    ink=False,
                    on_click=lambda e: (plugins_show_all.update({"value": not plugins_show_all["value"]}), refresh_plugins_list()),
                )
                    )
        # Scoped diff (page.update() re-synced every mounted tab).
        thread_safe_ui.refresh(installed_plugins_list)
        thread_safe_ui.refresh(installed_plugins_count)
        _build_plugins_view_segment()  # keep "Installed (N)" tab count fresh

    def _plugin_row(p: dict):
        def on_toggle(e):
            version_id = active_version["value"]
            if not version_id:
                return
            core.toggle_plugin(version_id, p["filename"], e.control.value)
            refresh_plugins_list()

        def on_delete(e):
            version_id = active_version["value"]
            if not version_id:
                return
            core.delete_plugin(version_id, p["filename"])
            refresh_plugins_list()

        # Installed rows match the mods tab's: transparent at rest, lift on
        # hover, quiet typography - state is in the text, not a slab.
        return attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(ft.Icons.EXTENSION_ROUNDED, size=18,
                                            color=ACCENT if p["enabled"] else TEXT_FAINT),
                            width=38, height=38, bgcolor=ROW_HOVER, border_radius=RADIUS,
                            alignment=ft.Alignment.CENTER,
                        ),
                        ft.Column(
                            [
                                ft.Text(p["display_name"], size=13.5,
                                        color=TEXT if p["enabled"] else TEXT_DIM,
                                        weight=ft.FontWeight.W_600),
                                ft.Text("Managed by Cubeon (required for public sharing)" if p.get("protected")
                                        else ("Enabled" if p["enabled"] else "Disabled"),
                                        size=11, color=TEXT_FAINT, font_family=FONT_MONO),
                            ],
                            spacing=2, expand=True,
                        ),
                        # Protected plugins (Minekube Connect) get a lock instead
                        # of the toggle/delete controls - they're Cubeon's own
                        # infrastructure and are re-installed at server start
                        # anyway, so removing them only ever broke sharing.
                        *(
                            [ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.LOCK_ROUNDED, size=14, color=TEXT_DIM),
                                    ft.Text("System", size=11, color=TEXT_DIM, font_family=FONT_MONO),
                                ], spacing=4, tight=True),
                                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
                            )]
                            if p.get("protected") else [
                                animated_switch(value=p["enabled"], active_color=ACCENT, on_change=on_toggle),
                                ft.Container(
                                    content=ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, size=18, color=DANGER),
                                    padding=8, ink=False, border_radius=RADIUS, on_click=on_delete,
                                ),
                            ]
                        ),
                    ],
                    spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
            ),
            "transparent", ROW_HOVER,
        )

    # Browse/search Modrinth for plugins.
    plugin_search_field = ft.TextField(
        hint_text="Search plugins on Modrinth...",
        border_color=CARD_BORDER, focused_border_color=ACCENT_DIM, color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT), bgcolor=CARD_FILL, border_radius=RADIUS,
        height=46, expand=True, prefix_icon=ft.Icons.SEARCH_ROUNDED,
        content_padding=ft.padding.Padding.symmetric(horizontal=14, vertical=12),
        on_submit=lambda e: run_plugin_search(),
    )
    plugin_search_status = ft.Text("", size=12, color=TEXT_DIM)
    # Quiet mono caption, same role as the mods tab's "Recommended" line.
    plugin_market_title = ft.Text("Plugin picks", size=12, color=TEXT_DIM, font_family=FONT_MONO)

    # Download-progress banner: every plugin install (market, search results,
    # low-ping picks - anything using _install_plugin_handler) reports its
    # byte progress here instead of a bare "Installing..." text.
    plugin_install_title = ft.Text("", size=12, color=TEXT, weight=ft.FontWeight.W_600)
    plugin_install_bar = ft.ProgressBar(width=260, height=6, color=ACCENT,
                                        bgcolor=SURFACE_HI, value=0)
    plugin_install_pct = ft.Text("0%", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    plugin_install_banner = ft.Container(
        content=ft.Row(
            [ft.ProgressRing(width=14, height=14, stroke_width=2, color=ACCENT),
             plugin_install_title, plugin_install_bar, plugin_install_pct],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS, padding=ft.padding.Padding.symmetric(horizontal=14, vertical=9),
        visible=False,
    )
    _plugin_install_busy = {"v": False}   # one install at a time (double-click safe)
    plugin_results_list = ft.Column(spacing=10)
    PLUGIN_PAGE_SIZE = 5
    plugin_browse_state = {"results": [], "page": 0}
    plugin_pager_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    plugin_pager_prev = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=TEXT),
        padding=6, border_radius=RADIUS, ink=False,
    )
    plugin_pager_next = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT),
        padding=6, border_radius=RADIUS, ink=False,
    )
    plugin_pager_row = ft.Row(
        [plugin_pager_prev, plugin_pager_label, plugin_pager_next],
        alignment=ft.MainAxisAlignment.CENTER, spacing=4, visible=False,
    )

    def _plugin_icon(hit: dict, *, size=48):
        if hit.get("icon_url"):
            _icons.prefetch(hit["icon_url"])  # disk-cache art for next renders
            return ft.Image(
                src=_icons.src(hit["icon_url"]), width=size, height=size,
                border_radius=RADIUS, fit=ft.BoxFit.COVER,
                error_content=ft.Icon(ft.Icons.EXTENSION_ROUNDED, color=ACCENT, size=20),
            )
        return ft.Container(
            content=ft.Icon(ft.Icons.EXTENSION_ROUNDED, size=22, color=TEXT_FAINT),
            width=size, height=size, bgcolor=ROW_HOVER, border_radius=RADIUS,
            alignment=ft.Alignment.CENTER,
        )

    def _install_plugin_handler(hit: dict):
        def handler(e=None):
            version_id = active_version["value"]
            if not version_id:
                return
            if _plugin_install_busy["v"]:
                plugin_search_status.value = "Already installing a plugin. One at a time."
                page.update()
                return
            _plugin_install_busy["v"] = True
            title = hit.get("title") or hit.get("slug") or "plugin"
            plugin_install_title.value = f"Downloading {title}..."
            plugin_install_bar.value = 0
            plugin_install_pct.value = "0%"
            plugin_install_banner.visible = True
            plugin_search_status.value = ""
            page.update()

            def worker():
                try:
                    file_info = core.get_plugin_download(hit["slug"] or hit["project_id"], mc_version=version_id)
                    if not file_info:
                        plugin_search_status.value = f"No build of {title} found for {version_id}."
                    else:
                        def on_progress(done, total):
                            # Byte-accurate progress from download_plugin's
                            # stream callback; indeterminate bar if the
                            # server didn't send Content-Length.
                            plugin_install_bar.value = (done / total) if total else None
                            plugin_install_pct.value = (
                                f"{int(done * 100 / max(total, 1))}% · {done // 1024} KB"
                                if total else f"{done // 1024} KB")
                            page.update()

                        core.download_plugin(
                            version_id, file_info["url"], file_info["filename"],
                            slug=hit["slug"], progress_cb=on_progress,
                        )
                        plugin_install_pct.value = "100%"
                        plugin_search_status.value = f"Installed {title}."
                        refresh_plugins_list()
                        _render_plugin_page()  # flip its Browse button to "Installed"
                except Exception as ex:
                    plugin_search_status.value = f"Couldn't install {title}: {ex}"
                finally:
                    plugin_install_banner.visible = False
                    _plugin_install_busy["v"] = False
                    page.update()

            threading.Thread(target=worker, daemon=True).start()
        return handler

    def _plugin_result_row(hit: dict, is_installed=False):
        """
        One plugin in the browse results, styled exactly like the mods tab's
        rows: title leads (15px, bold), description and download/author
        metadata quiet beneath it, the row transparent until hovered, and the
        install action a restrained green wash instead of a solid block.
        """
        desc = hit.get("description") or ""
        if len(desc) > 105:
            desc = desc[:102] + "..."
        downloads = hit.get("downloads", 0) or 0
        author = hit.get("author") or "Modrinth"

        install_btn_text = ft.Text(
            "Installed" if is_installed else "Install",
            size=12.5, weight=ft.FontWeight.W_700,
            color=TEXT_FAINT if is_installed else ACCENT,
        )
        install_btn = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.CHECK_ROUNDED if is_installed else ft.Icons.DOWNLOAD_ROUNDED,
                         color=TEXT_FAINT if is_installed else ACCENT, size=15),
                 install_btn_text],
                spacing=6, tight=True,
            ),
            bgcolor=None if is_installed else ACCENT_TINT,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=7),
            ink=False,
            on_click=None if is_installed else _install_plugin_handler(hit),
        )

        return attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        _plugin_icon(hit),
                        ft.Column(
                            [
                                ft.Text(hit["title"] or hit.get("slug", ""), size=15,
                                        color=TEXT, weight=ft.FontWeight.W_700, max_lines=1),
                                ft.Text(desc, size=12, color=TEXT_DIM, max_lines=1),
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=13, color=TEXT_FAINT),
                                        ft.Text(f"{downloads:,}", size=11, color=TEXT_FAINT,
                                                font_family=FONT_MONO),
                                        ft.Container(width=8),
                                        ft.Icon(ft.Icons.PERSON_ROUNDED, size=13, color=TEXT_FAINT),
                                        ft.Text(author, size=11, color=TEXT_FAINT),
                                    ],
                                    spacing=4,
                                ),
                            ],
                            spacing=3, expand=True,
                        ),
                        install_btn,
                    ],
                    spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=10),
            ),
            "transparent", ROW_HOVER,
        )

    def run_plugin_search(e=None):
        version_id = active_version["value"]
        if not version_id:
            return
        query = plugin_search_field.value or ""
        plugin_search_status.value = "Searching..."
        plugin_results_list.controls.clear()
        plugin_pager_row.visible = False
        page.update()

        def worker():
            try:
                if query.strip():
                    hits = core.search_plugins(query, mc_version=version_id)
                else:
                    hits = core.get_recommended_plugins()
                plugin_browse_state["results"] = hits
                plugin_browse_state["page"] = 0
                plugin_search_status.value = f"{len(hits)} result(s)" if query.strip() else "Featured picks"
                _render_plugin_page()
            except Exception as ex:
                plugin_search_status.value = f"Search failed: {ex}"
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    def _plugin_installed_tokens() -> set:
        """Identifiers for plugins already in this server's plugins/ folder,
        for marking browse results as installed. Uses each plugin's recorded
        Modrinth slug plus a punctuation-free token of its filename, so a hit
        reads as "already installed" whether it was pulled from Modrinth
        (exact slug match) or dropped in as a local .jar (name-token match)."""
        version_id = active_version.get("value") or ""
        if not version_id:
            return set()
        tokens = set()
        for p in core.list_plugins(version_id):
            slug = (p.get("slug") or "").lower()
            if slug:
                tokens.add(slug)
            name = re.sub(r"[^a-z0-9]+", "", (p.get("display_name") or "").lower())
            if name:
                tokens.add(name)
        return tokens

    def _render_plugin_page():
        """Renders one page (PLUGIN_PAGE_SIZE items) of the stored plugin
        results and updates the pager to match - pages through everything
        that came back, not just the first handful."""
        hits = plugin_browse_state["results"]
        page_num = plugin_browse_state["page"]
        total_pages = max(1, -(-len(hits) // PLUGIN_PAGE_SIZE))  # ceil div
        page_num = max(0, min(page_num, total_pages - 1))
        plugin_browse_state["page"] = page_num

        plugin_results_list.controls.clear()
        installed = _plugin_installed_tokens()
        start = page_num * PLUGIN_PAGE_SIZE
        for hit in hits[start:start + PLUGIN_PAGE_SIZE]:
            hit_slug = (hit.get("slug") or "").lower()
            hit_title = re.sub(r"[^a-z0-9]+", "", (hit.get("title") or "").lower())
            is_installed = hit_slug in installed or \
                (bool(hit_title) and hit_title in installed)
            plugin_results_list.controls.append(_plugin_result_row(hit, is_installed))

        plugin_pager_label.value = f"Page {page_num + 1} of {total_pages}"
        plugin_pager_row.visible = len(hits) > PLUGIN_PAGE_SIZE
        plugin_pager_prev.disabled = page_num <= 0
        plugin_pager_next.disabled = page_num >= total_pages - 1
        page.update()

    def _plugin_page_prev(e=None):
        if plugin_browse_state["page"] > 0:
            plugin_browse_state["page"] -= 1
            _render_plugin_page()

    def _plugin_page_next(e=None):
        total_pages = max(1, -(-len(plugin_browse_state["results"]) // PLUGIN_PAGE_SIZE))
        if plugin_browse_state["page"] < total_pages - 1:
            plugin_browse_state["page"] += 1
            _render_plugin_page()

    plugin_pager_prev.on_click = _plugin_page_prev
    plugin_pager_next.on_click = _plugin_page_next

    # (Search runs on Enter; the old solid-green Search button is gone - the
    # mods tab has no explicit search button either.)

    # --- Browse / Installed view tabs (built here: every child control now exists) ---
    # Same pattern as the Mods tab: the plugin market and the installed list
    # each get the whole screen, toggled by underline tabs. Both panes stay
    # mounted; only visibility flips. No enclosing slab - the rows carry
    # themselves, exactly like the mods browse pane.
    plugins_browse_pane = ft.Column(
        [
            ft.Row([plugin_search_field], spacing=6),
            ft.Container(height=12),
            ft.Row([plugin_market_title, ft.Container(expand=True), plugin_search_status],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=4),
            plugin_install_banner,
            plugin_results_list,
            plugin_pager_row,
        ],
        spacing=8,
        visible=True,
    )

    plugins_installed_pane = ft.Column(
        [
            ft.Row([section_label("Installed plugins"), ft.Container(expand=True), installed_plugins_count],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            installed_plugins_list,
        ],
        spacing=8,
        visible=False,
    )

    plugins_view_segment_row = ft.Row(spacing=18)

    def _build_plugins_view_segment():
        plugins_view_segment_row.controls.clear()
        try:
            v = active_version["value"]
            n_plugs = len(core.list_plugins(v)) if (v and core.get_server_type(v) == core.SERVER_TYPE_PAPER) else 0
        except Exception:
            n_plugs = 0
        for vid, vlabel in (("browse", "Browse"), ("installed", "Installed")):
            count_note = f" ({n_plugs})" if (vid == "installed" and n_plugs) else ""
            plugins_view_segment_row.controls.append(
                text_tab(vlabel + count_note,
                         selected=plugins_active_view["value"] == vid,
                         on_click=lambda e, vv=vid: _on_plugins_view_change(vv))
            )
        thread_safe_ui.refresh(plugins_view_segment_row)

    def _on_plugins_view_change(new_view):
        if plugins_active_view["value"] == new_view:
            return
        plugins_active_view["value"] = new_view
        plugins_browse_pane.visible = (new_view == "browse")
        plugins_installed_pane.visible = (new_view == "installed")
        _build_plugins_view_segment()
        if new_view == "installed":
            refresh_plugins_list()
        thread_safe_ui.refresh(plugins_browse_pane)
        thread_safe_ui.refresh(plugins_installed_pane)

    plugins_content = ft.Column(
        [
            # View tabs: Browse (the market) and Installed (your plugins)
            # share the screen one at a time - the installed list no longer
            # lives a full market-scroll below the search results.
            plugins_view_segment_row,
            ft.Container(height=6),
            plugins_browse_pane,
            plugins_installed_pane,
        ],
        spacing=0,
        visible=False,
    )
    _build_plugins_view_segment()

    def refresh_plugins_visibility():
        is_paper = plugins_tab_visible["value"]
        # The notice covers "server not installed yet". Cubeon always hosts
        # Paper, so the old "Switch to Paper in Settings" wording was wrong
        # twice over: there is no type to switch, and the fix is installing.
        if not is_paper:
            v = active_version["value"]
            if not v:
                plugins_not_paper_notice_text.value = (
                    "Pick a version on the Play tab first - the server hosts whatever's selected there."
                )
            else:
                plugins_not_paper_notice_text.value = (
                    "Install the server first (Servers tab, big Install button) - "
                    "plugins live inside it once it exists."
                )
        plugins_not_paper_notice.visible = not is_paper
        plugins_content.visible = is_paper
        page.update()

    plugins_view = ft.Column(
        [
            ft.Text("Plugins", size=28, color=TEXT, font_family=FONT_DISPLAY),
            ft.Text("Find plugins, then manage the ones you've added.", size=13, color=TEXT_DIM),
            ft.Container(height=8),
            plugins_not_paper_notice,
            plugins_content,
        ],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )

    # --- Console view (the "Servers > Console" sidebar sub-item) ----------

    # Public (Minekube) address, shown neatly under the LAN line. There is
    # no separate "share" panel anymore: starting the server IS sharing -
    # the Connect plugin is auto-installed and configured at start, and
    # this line picks the public address out of the log the moment the
    # plugin announces it.
    public_text = ft.Text("", size=12, color=ACCENT, font_family=FONT_MONO,
                          weight=ft.FontWeight.W_600, selectable=True)
    public_hint_text = ft.Text("", size=11, color=TEXT_DIM, font_family=FONT_MONO)

    def _refresh_public_address_line():
        """Disk reads only (log tail + config) - safe on the UI thread."""
        version_id = active_version["value"]
        if not version_id or not core.is_server_installed(version_id):
            public_text.value = ""
            public_hint_text.value = ""
            return
        endpoint = core.minekube.get_endpoint(version_id)
        named = core.minekube.public_address(endpoint)
        addr = core.minekube.read_public_address(version_id)
        if core.is_server_running(version_id) and addr:
            public_text.value = f"Public address: {addr}"
            public_hint_text.value = "Share this with friends. No port forwarding needed."
        elif named:
            public_text.value = f"Public address: {named}"
            public_hint_text.value = "Goes live when the server starts."
        elif core.is_server_running(version_id):
            public_text.value = "Public address: starting..."
            public_hint_text.value = "Minekube announces it right after startup."
        else:
            public_text.value = ""
            public_hint_text.value = ""

    def _public_watcher():
        """Keeps the public-address line live without any user action -
        same contract the old tunnel panel's watcher had, just attached to
        one neat line instead of a whole collapsible section."""
        import time as _time
        _last_notified = None   # address already pushed into Minecraft chat
        while True:
            _time.sleep(2.0)
            try:
                version_id = active_version["value"]
                if not version_id or not core.is_server_running(version_id):
                    continue
                addr = core.minekube.read_public_address(version_id)
                if addr and f"Public address: {addr}" != public_text.value:
                    public_text.value = f"Public address: {addr}"
                    public_hint_text.value = ("Share this with friends. "
                                              "No port forwarding needed.")
                    # The address belongs in the player's Minecraft chat too:
                    # a host in-game learns it where they can copy it, instead
                    # of hunting for the Server tab. One line per resolved
                    # address, not per poll.
                    if addr != _last_notified:
                        _last_notified = addr
                        try:
                            from cubeon.friends_service import FriendsService
                            FriendsService.notify_active(
                                f"Your Cubeon server is public at {addr} - "
                                f"share it with friends.")
                        except Exception:
                            pass
                    # Feed the Tab-list branding in CubeonGate so the
                    # player list shows the live endpoint.
                    try:
                        core.gate.set_display_address(version_id, addr)
                    except Exception:
                        pass
                    page.update()
            except Exception:
                continue

    threading.Thread(target=_public_watcher, daemon=True).start()

    def _ensure_minekube_ready(version_id, console_line):
        """Start-server step zero: the managed plugins (Minekube Connect
        for sharing, AuthMe for login security on offline servers) and
        Connect's config must exist before the jar boots. Best effort - a
        failed download must not block the server itself from starting;
        the console line says what happened either way."""
        try:
            if not core.minekube.is_plugin_installed(version_id):
                console_line("[minekube] Installing the Connect plugin (one time)...")
                core.minekube.install_plugin(version_id)
            endpoint = ""
            try:
                endpoint = core.minekube.get_endpoint(version_id)
            except Exception:
                pass
            core.minekube.ensure_config(
                version_id, endpoint=endpoint,
                allow_offline=core.get_server_properties(
                    version_id).get("online-mode", "false") != "true")
            console_line("[minekube] Connect ready. The public address "
                         "appears here after startup.")
        except Exception as ex:
            console_line(f"[minekube] Sharing unavailable this start: {ex}")
        try:
            # Always call: install() is a no-op when the jar already
            # matches, and updates it when a Cubeon release ships a fix.
            core.gate.install(version_id)
        except Exception as ex:
            console_line(f"[gate] Couldn't install the security plugin: {ex}")
        if not core.gate.has_password(version_id):
            console_line("[gate] No server password set! Set one in "
                         "Settings > Security password. Until then anyone "
                         "who reaches this server can walk in.")
        try:
            result = core.ensure_default_plugins(version_id)
            for name in result.get("installed", []):
                console_line(f"[server] Installed default plugin: {name}")
            for change in result.get("tuned", []):
                console_line(f"[server] AuthMe tuning: {change}")
            for slug, why in result.get("failed", []):
                console_line(f"[server] Couldn't install default plugin "
                             f"{slug}: {why}")
        except Exception as ex:
            console_line(f"[server] Default plugin check failed: {ex}")

    console_view = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Console", size=28, color=TEXT, font_family=FONT_DISPLAY),
                    ft.Container(expand=True),
                    restart_button,
                    start_stop_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            version_text,
            no_version_notice,
            ft.Container(height=4),
            # one slim status bar: dot + state + address, nothing stacked
            ft.Row(
                [status_dot, status_text, address_text],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            public_text,
            public_hint_text,
            orphan_notice,
            ft.Row([stop_orphan_button], spacing=10),
            ft.Container(height=6),
            quick_actions_row,
            ft.Container(height=8),
            terminal_container,
        ],
        spacing=6,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # --- Settings view (the "Servers > Settings" sidebar sub-item) --------

    settings_view = ft.Column(
        [
            ft.Text("Server settings", size=28, color=TEXT, font_family=FONT_DISPLAY),
            ft.Container(height=8),
            version_text_settings,
            no_version_notice_settings,
            ft.Container(height=12),
            ft.Container(
                content=ft.Column(
                    [
                        section_label("Install"),
                        ft.Row([install_button, install_status], spacing=12),
                        install_progress,
                        ft.Container(height=4),
                        eula_checkbox,
                    ],
                    spacing=10,
                ),
                bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
            ),
            ft.Container(height=16),
            settings_panel,
        ],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )

    def refresh_server_tab():
        """Called by main.py when the Server tab becomes visible, and
        whenever the selected version changes elsewhere in the app -
        reloads everything for whichever version is now selected."""
        version_id = state.get("selected_version")
        active_version["value"] = version_id

        if not version_id:
            version_text.value = ""
            version_text_settings.value = ""
            no_version_notice.visible = True
            no_version_notice_settings.visible = True
            stop_orphan_button.visible = False
            orphan_notice.visible = False
            plugins_tab_visible["value"] = False
            public_text.value = ""
            public_hint_text.value = ""
            refresh_plugins_visibility()
            refresh_controls_enabled()
            page.update()
            return

        no_version_notice.visible = False
        no_version_notice_settings.visible = False
        version_text.value = f"Hosting version: {version_id}"
        version_text_settings.value = f"Hosting version: {version_id}"

        props = core.get_server_properties(version_id)
        motd_field.value = props.get("motd", "")
        port_field.value = props.get("server-port", "25565")
        max_players_field.value = props.get("max-players", "20")
        seed_field.value = props.get("level-seed", "")
        view_distance_dropdown.value = str(core.clamp_distance(
            props.get("view-distance", "10"), core.VIEW_DISTANCE_RANGE, 10))
        view_distance_dropdown._sync_color()
        sim_distance_dropdown.value = str(core.clamp_distance(
            props.get("simulation-distance", "10"), core.SIMULATION_DISTANCE_RANGE, 10))
        sim_distance_dropdown._sync_color()
        gamemode_dropdown.value = props.get("gamemode", "survival")
        gamemode_dropdown._sync_color()
        difficulty_dropdown.value = props.get("difficulty", "normal")
        difficulty_dropdown._sync_color()
        pvp_switch.value = props.get("pvp", "true") == "true"
        whitelist_switch.value = props.get("white-list", "false") == "true"
        online_mode_switch.value = props.get("online-mode", "false") == "true"
        allow_flight_switch.value = props.get("allow-flight", "false") == "true"
        high_ping_switch.value = core.high_ping_optimization_enabled(version_id)
        endpoint_field.value = core.minekube.get_endpoint(version_id)
        update_gate_status()
        refresh_whitelist_list()

        plugins_tab_visible["value"] = core.is_server_installed(version_id)
        refresh_plugins_visibility()

        eula_checkbox.value = core.eula_accepted(version_id)
        if not install_in_progress["value"]:
            install_button.content.value = install_button_label()
            install_status.value = "Installed" if core.is_server_installed(version_id) else "Not installed yet"
            install_progress.visible = False

        set_running_ui(core.is_server_running(version_id))
        refresh_orphan_notice()
        refresh_plugins_list()
        if plugins_tab_visible["value"] and not plugin_results_list.controls:
            run_plugin_search()

    return console_view, settings_view, plugins_view, refresh_server_tab

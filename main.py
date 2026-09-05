"""
Cubeon - a Minecraft launcher UI built with Flet.
Dark control-room aesthetic, offline/cracked auth, version install+launch,
skin preview, RAM/Java settings, and mods folder management.

This is the main entry point for the launcher. It sets up the window,
loads configuration, builds the entire UI (Play, Skin, Mods, Settings tabs),
handles user interactions, and orchestrates game launching and mod management.

The code uses Flet for UI and relies on launcher_core.py for backend logic
(version installation, mod downloads, Java launching, etc.).
"""

# Standard library imports
import os          # For file path/mtime handling (used for avatar cache-busting)
import re          # For regular expressions (used to clean mod slugs and parse version strings)
import sys         # For runtime platform detection and PyInstaller bundle paths
import threading   # For running long tasks (e.g., network calls, game launch) without freezing the UI
import time        # For the scheduled-backup timer loop
import traceback   # For printing full tracebacks of swallowed launch errors to the console
import flet as ft  # Flet UI framework - provides widgets and app scaffolding

# Local module imports - our own helper functions for Minecraft-related logic
import launcher_core as core
from launcher_core import run_file_picker  # Version-safe FilePicker.pick_files() wrapper
from cubeon import thread_safe_ui  # Makes page.update() safe from background threads
from ui.skin_tab import build_skin_section  # Imports the skin section builder, now embedded in the Profile dialog
from ui.mods_tab import build_mods_tab  # Imports the mods_tab builder function
from ui.modpacks_tab import build_modpacks_tab  # Imports the modpacks_tab builder function
from ui.server_tab import build_server_tab  # Imports the server_tab builder function
from cubeon import friends  # Realtime social client (identity, presence, chat, calls)
from cubeon.friends_service import FriendsService  # Headless owner of friends/P2P (UI lives in the in-game mod)
from cubeon.discord_rpc import DiscordPresence  # Optional Discord Rich Presence (no-op unless configured)
from cubeon.controller import ControllerWatcher  # Gamepad detection + menu driving (no-op without a pad)


# ---------------------------------------------------------------------------
# Design tokens - colors and fonts used throughout the UI.
#
# These now live in cubeon/theme.py rather than being defined here, because
# every tab module needs them and main.py can't be imported by them (it imports
# them, so that would be circular). They're re-exported into this module's
# namespace so the ~700 references below, and the `THEME`-passing call sites,
# keep working untouched.
# ---------------------------------------------------------------------------
from cubeon.theme import (  # noqa: E402  (kept with the other token setup)
    BG, SURFACE, SURFACE_HI, SURFACE_MAX, BORDER, BORDER_HI,
    ACCENT, ACCENT_HI, ACCENT_DIM, ON_ACCENT,
    TEXT, TEXT_DIM, TEXT_FAINT, DANGER, INFO, WARNING,
    FONT_DISPLAY, FONT_BODY, FONT_MONO,
    FONT_URLS, THEME, RADIUS, RADIUS_LG,
    CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT,
    card as glass_card,
)
from cubeon import theme  # for theme.pixel_divider / theme.section_label


def resolve_assets_dir() -> str:
    """Reliably find the 'assets' directory across all execution modes:
    - Running from source script (`python main.py`)
    - Running frozen by PyInstaller (`_internal/assets`, `sys._MEIPASS`, etc.)
    - Running inside Linux AppImage ($APPDIR)
    - Running inside Windows standalone exe/folder
    """
    candidates = []

    # 1. PyInstaller MEIPASS temporary extract dir (onefile mode)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "assets"))

    # 2. PyInstaller executable directory (onedir mode)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "assets"))
        candidates.append(os.path.join(exe_dir, "_internal", "assets"))

    # 3. Linux AppImage environment
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(os.path.join(appdir, "usr", "bin", "assets"))
        candidates.append(os.path.join(appdir, "usr", "bin", "_internal", "assets"))
        candidates.append(os.path.join(appdir, "assets"))

    # 4. Source script location (__file__)
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(this_dir, "assets"))
        candidates.append(os.path.join(this_dir, "_internal", "assets"))
        candidates.append(os.path.join(this_dir, "..", "assets"))
    except Exception:
        pass

    # 5. Current working directory
    candidates.append(os.path.join(os.getcwd(), "assets"))

    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)

    # Fallback
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _explain_exit(code: int, lines=None) -> str:
    """Turns a game exit code + its last output into something actionable.

    The audience here is a kid whose game just closed, so this looks for the
    handful of causes that actually account for most failed cracked launches and
    names the fix. Anything unrecognised falls back to the real error line,
    which is still far better than the previous behaviour of showing nothing.
    """
    text = "\n".join(lines or [])
    low = text.lower()

    if "java.lang.outofmemoryerror" in low or "could not reserve enough space" in low:
        return "Crashed: out of memory. Lower RAM in Settings, or close other apps."
    if "unsupported class file major version" in low or "unsupportedclassversionerror" in low:
        return "Crashed: wrong Java version for this Minecraft version. Set Java in Settings."
    if "incompatible mod set" in low or "mod resolution encountered an incompatible" in low:
        return "Crashed: mods don't match this version. Disable mods on the Mods tab."
    if "org.lwjgl" in low and ("glfw" in low or "no opengl" in low or "failed to create window" in low):
        return "Crashed: graphics driver couldn't start the game window. Update your GPU drivers."
    if "cannot run program" in low or "no such file or directory" in low and "java" in low:
        return "Crashed: Java not found. Install Java, or set its path in Settings."
    # A missing loader entrypoint means the classpath was wrong, not that the
    # user did anything. It reads like a broken Fabric install, so say what it
    # really is - this was Cubeon's own client.json bug (see cubeon/launch.py).
    if "knotclient" in low or "knotserver" in low:
        return ("Crashed: this version's config was incomplete, so Fabric couldn't start. "
                "Cubeon repaired it. Press Play again.")
    if "classnotfoundexception" in low and "net.minecraft" in low:
        return ("Crashed: the game files for this version look incomplete. "
                "Reinstall it, or pick another version.")

    # Nothing recognised - surface the last line that looks like an actual
    # error, rather than the harmless final log line.
    for line in reversed(lines or []):
        if any(marker in line.lower() for marker in
               ("exception", "error", "caused by", "fatal")):
            return f"Crashed (exit {code}): {line.strip()[:140]}"
    return f"Crashed (exit {code}). Check that Java and your mods match this version."


def main(page: ft.Page):
    """
    This is the main function that Flet calls when the app starts.
    It receives a `page` object representing the application window.
    We set up the page properties, load configuration, build all UI components,
    and define the app's behavior (callbacks, background threads, etc.).
    """

    # Make page.update() safe to call from the background threads this file
    # starts. Without this, Flet 0.80+ silently loses those updates until some
    # unrelated input wakes its event loop - which is what made the Play button
    # sit on "Preparing" until you switched tabs. See cubeon/thread_safe_ui.py.
    thread_safe_ui.install(page)

    # Dev-only live UI inspector (CUBEON_INSPECT=1): a DevTools-style dialog
    # for browsing the mounted control tree and editing text/tooltips live.
    # Off by default; public builds never show it. See cubeon/inspector.py.
    from cubeon.inspector import inspector_enabled, open_inspect
    _inspector_enabled = inspector_enabled()

    def _open_inspector():
        try:
            open_inspect(page)
        except Exception:
            traceback.print_exc()
            try:
                page.open(ft.SnackBar(ft.Text("Inspector failed to open - "
                                              "see cubeon.log", size=12)))
            except Exception:
                pass

    # Central logging BEFORE anything else can fail: from here on, every
    # cubeon/ module's log calls land in ~/.cubeon_launcher/cubeon.log and
    # any uncaught exception (any thread) is written there with a traceback.
    from cubeon.logging_setup import setup_logging
    setup_logging()
    # --- Basic window configuration ---
    page.title = "Cubeon Launcher"
    page.bgcolor = BG
    page.padding = 0
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 980
    page.window.min_height = 640

    # App/taskbar/titlebar icon - falls back gracefully if not supported.
    # On Windows: window_manager requires .ico (e.g. icon.ico).
    # On Linux/macOS: window_manager requires .png (e.g. icon_256.png).
    try:
        _assets_folder = resolve_assets_dir()
        if sys.platform == "win32":
            _ico = os.path.join(_assets_folder, "icon.ico")
            if os.path.isfile(_ico):
                page.window.icon = _ico
            else:
                page.window.icon = "icon.ico"
        else:
            for _png_name in ("icon_256.png", "icon_512.png", "icon_128.png", "icon_64.png", "icon_32.png", "icon_16.png"):
                _png_path = os.path.join(_assets_folder, _png_name)
                if os.path.isfile(_png_path):
                    page.window.icon = _png_path
                    break
    except Exception:
        pass

    # --- Load bundled fonts from the local asset dir ---
    # Minecraftia + Inter ship inside assets/fonts (paths resolved against
    # assets_dir), so nothing is fetched from the web at startup - the window
    # can appear instantly and even fully offline. URLs live beside the family
    # names in cubeon/theme.py, so a font can't be referenced by name without
    # also being registered here.
    page.fonts = dict(FONT_URLS)
    # Install the full design system (blocky shapes + on-palette ColorScheme for
    # every default Flet control - dialogs, buttons, menus, scrollbars). See
    # cubeon/theme.apply_page_theme for the colour-theory rationale.
    theme.apply_page_theme(page)

    # --- Load configuration (saved settings) from disk ---
    cfg = core.load_config()  # returns a dict with keys like "username", "ram_mb", "last_version", etc.

    # Now that cfg exists, arm the opt-in crash reporting hooks (the logging
    # itself was armed above; this only decides whether uncaught exceptions
    # are ALSO reported, and only if the user opted in + an endpoint exists).
    from cubeon import crashreport as _crashreport
    from cubeon.logging_setup import _install_excepthooks as _arm_crash_hooks
    _arm_crash_hooks(cfg)

    # --- Optional Discord Rich Presence ("Cubeon" on your Discord profile) ---
    # Only does anything if Discord is running AND the user has pasted a Discord
    # application id into config (discord_client_id). Every call is a silent
    # no-op otherwise, so a missing/misconfigured Discord never breaks the app.
    # See cubeon/discord_rpc.py for the two required Discord-side steps.
    _rpc = DiscordPresence(cfg.get("discord_client_id"),
                           enabled=cfg.get("discord_rpc_enabled", True))
    # The app's Discord art-asset image key (config), used as the big presence
    # icon. Empty string -> no icon.
    _discord_img = cfg.get("discord_large_image") or None
    _discord_img_text = cfg.get("discord_large_text") or "Cubeon"
    # Announce "in the launcher" off the UI thread: connecting to Discord's IPC
    # socket is a network-ish call, and we never want a missing/slow Discord to
    # delay the window appearing. All later updates are tiny and fast.
    threading.Thread(
        target=_rpc.set_activity,
        kwargs={
            "details": "Cubeon",
            "state": "In the launcher",
            "large_image": _discord_img,
            "large_text": _discord_img_text,
        },
        daemon=True,
    ).start()

    # --- Ensure the stable machine identity exists (auth_key.json) ---
    # A permanent random v4 UUID + owning secret, created once and self-healing.
    # This is what the game launches with and what the Friends/chat account is
    # anchored to, so changing the in-game username never resets player data,
    # cosmetics, or your friends list. Idempotent - a no-op once the key exists.
    core.ensure_auth_key()

    # --- Get the list of already installed Minecraft versions ---
    _initial_versions = core.get_installed_versions()  # List of version info dicts

    # --- State dictionary to hold dynamic data that changes during the app's lifetime ---
    # We use this to track the selected version, installed versions, running processes, etc.
    state = {
        "selected_version": cfg.get("last_version"),        # The version currently selected in the dropdown (raw launch id)
        "selected_mc_version": core.extract_mc_version(cfg.get("last_version")) if cfg.get("last_version") else None,
        # ^ clean numeric version (e.g. "1.20.1") derived from the launch id - this is the
        # key used for mods profiles (get_profile_dir/list_mods/sync_mods_to_game). Kept
        # separate from "selected_version" because the raw id can be loader-tagged for
        # TLauncher or manually-installed versions (e.g. "1.20.1-forge-47.2.0"), and using
        # that raw id as a profile key pointed the Mods tab and the mods-sync-at-launch
        # step at a different, always-empty folder - see on_version_selected().
        "installed": {v["id"] for v in _initial_versions},  # Set of installed version IDs for quick lookup
        "installed_meta": {v["id"]: v for v in _initial_versions},  # Full info per installed version
        "process": None,                                     # Will hold the subprocess when game is running
        "mod_loader": "fabric",  # fabric | quilt | forge | neoforge - which mod loader is selected
        "running_version": None,  # launch id currently running, or None - guards instance delete
    }

    # -----------------------------------------------------------------
    # Shared small components - pixel_divider() and section_label() now live
    # in cubeon/theme.py next to the tokens they're built from, since the tab
    # modules take them as arguments and they were pure functions of the
    # palette anyway. Bound to locals here so the call sites below and the
    # `section_label=`/`pixel_divider=` arguments passed to the tab builders
    # keep working unchanged.
    # -----------------------------------------------------------------
    pixel_divider = theme.pixel_divider
    section_label = theme.section_label

    # -----------------------------------------------------------------
    # STATUS INDICATOR (headless)
    # There is deliberately no top bar and no visible "READY" chip under the
    # brand - both communicated almost nothing per pixel. The status widgets
    # still exist so set_status() keeps working everywhere (and any future
    # surface can mount them); they're just not displayed in the sidebar.
    # -----------------------------------------------------------------

    # A small colored dot that changes color to show status (ready, busy, error)
    status_dot = ft.Container(width=7, height=7, bgcolor=ACCENT, border_radius=RADIUS)
    status_text = ft.Text("READY", size=11, color=TEXT_DIM, font_family=FONT_MONO)

    # -----------------------------------------------------------------
    # SIDEBAR NAVIGATION - the vertical menu on the left
    # -----------------------------------------------------------------

    # Flat nav items: (key, icon, label). Profile is its own tab, opened
    # either from the sidebar nav list or by clicking "Signed in as" at
    # the bottom of the sidebar.
    nav_items = [
        ("play", ft.Icons.PLAY_ARROW_ROUNDED, "Play"),
        ("mods", ft.Icons.EXTENSION_ROUNDED, "Mods"),
        ("modpacks", ft.Icons.INVENTORY_2_ROUNDED, "Modpacks"),
        ("profile", ft.Icons.PERSON_ROUNDED, "Profile"),
        ("settings", ft.Icons.TUNE_ROUNDED, "Settings"),
    ]
    # "Servers" is a separate expandable group rather than a flat item -
    # (key, icon, label) sub-items collapsed under one clickable header.
    server_group_items = [
        ("server_console", ft.Icons.TERMINAL_ROUNDED, "Console"),
        ("server_plugins", ft.Icons.EXTENSION_ROUNDED, "Plugins"),
        ("server_settings", ft.Icons.TUNE_ROUNDED, "Settings"),
    ]
    server_group_expanded = {"value": False}

    active_tab = {"value": "play"}  # We use a dict so we can mutate it inside nested functions
    nav_buttons = {}  # Will hold references to each navigation button container

    # The main content area on the right - it will be replaced when switching tabs
    content_area = ft.Container(expand=True)

    def _style_nav_button(btn, is_active):
        # The active state is a *quiet* one: a faint green wash and a small
        # accent bar on the left edge - not a solid green slab. Green stays
        # scarce, so the rail doesn't out-shout the content it navigates to.
        btn.bgcolor = ACCENT_TINT if is_active else "transparent"
        btn.data = is_active  # remembered so the hover handler knows the resting state
        row = btn.content
        row.controls[0].color = ACCENT if is_active else TEXT_DIM      # icon
        row.controls[1].color = TEXT if is_active else TEXT_DIM        # label
        row.controls[2].bgcolor = ACCENT if is_active else "transparent"  # indicator bar

    def _on_nav_hover(e):
        """Affordance: an inactive nav item lifts to a faint wash and its
        label brightens to full TEXT on hover, so the sidebar feels responsive
        instead of dead. The active item is left alone - it already reads as
        selected and shouldn't flicker under the cursor."""
        btn = e.control
        if btn.data:  # active tab - leave it as-is
            return
        hovering = e.data == "true"
        btn.bgcolor = ROW_HOVER if hovering else "transparent"
        btn.content.controls[0].color = TEXT if hovering else TEXT_DIM
        btn.content.controls[1].color = TEXT if hovering else TEXT_DIM
        btn.update()

    def build_nav_button(key, icon, label, *, icon_size=18, indent=0):
        is_active = key == active_tab["value"]
        btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=icon_size, color=ACCENT if is_active else TEXT_DIM),
                    ft.Text(label, size=13.5, weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500,
                            color=TEXT if is_active else TEXT_DIM, expand=True),
                    # Small accent indicator on the leading edge - the whole
                    # active affordance is this bar plus the tint behind it.
                    ft.Container(width=3, height=16, bgcolor=ACCENT if is_active else "transparent",
                                 border_radius=RADIUS),
                ],
                spacing=12,
            ),
            bgcolor=ACCENT_TINT if is_active else "transparent",
            border_radius=RADIUS,
            padding=ft.padding.Padding.only(left=12 + indent, right=10, top=10, bottom=10),
            data=is_active,
            on_click=lambda e, k=key: switch_tab(k),
            on_hover=_on_nav_hover,
            animate=150,
        )
        nav_buttons[key] = btn
        return btn

    def toggle_server_group(e=None):
        server_group_expanded["value"] = not server_group_expanded["value"]
        server_group_children.visible = server_group_expanded["value"]
        server_group_chevron.name = (
            ft.Icons.EXPAND_LESS_ROUNDED if server_group_expanded["value"] else ft.Icons.EXPAND_MORE_ROUNDED
        )
        page.update()

    server_group_chevron = ft.Icon(ft.Icons.EXPAND_MORE_ROUNDED, size=18, color=TEXT_DIM)

    def build_server_group_header():
        """The 'Servers' row itself - minimal: an icon, a label, and a
        chevron. Clicking it only expands/collapses; it never navigates,
        since there's nothing to show without picking Console or Settings."""
        is_active = active_tab["value"] in {k for k, _, _ in server_group_items}
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.DNS_ROUNDED, size=18, color=ACCENT if is_active else TEXT_DIM),
                    ft.Text("Servers", size=13.5,
                            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500,
                            color=TEXT if is_active else TEXT_DIM, expand=True),
                    server_group_chevron,
                ],
                spacing=12,
            ),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
            on_click=toggle_server_group,
        )

    def build_nav():
        """
        Creates the list of navigation controls: the flat tab buttons plus
        the collapsible "Servers" group. The currently active tab gets a
        highlighted background (ACCENT). Clicking a flat button or a group
        sub-item calls switch_tab(); clicking the group header just
        expands/collapses it.
        """
        rows = []
        for key, icon, label in nav_items[:3]:  # Play, Mods, Modpacks
            rows.append(build_nav_button(key, icon, label))

        nonlocal server_group_header
        server_group_header = build_server_group_header()
        rows.append(server_group_header)
        server_sub_rows = [
            build_nav_button(key, icon, label, icon_size=16, indent=14)
            for key, icon, label in server_group_items
        ]
        nonlocal server_group_children
        server_group_children = ft.Column(server_sub_rows, spacing=2, visible=server_group_expanded["value"])
        rows.append(server_group_children)

        for key, icon, label in nav_items[3:]:  # Profile, Settings
            rows.append(build_nav_button(key, icon, label))
        return rows

    server_group_children = ft.Column([])  # placeholder, replaced inside build_nav()
    server_group_header = ft.Container()   # placeholder, replaced inside build_nav()

    # Sidebar "Signed in as" widgets - pulled out as named variables so the
    # username field's on_change handler can update them live, since offline
    # accounts are keyed entirely off the username (new name = new account).
    #
    # Avatar source resolution: an uploaded profile picture wins if present,
    # otherwise falls back to the skin-face render - so the sidebar/profile
    # dialog always shows *something* meaningful even before anyone uploads
    # their own picture.
    def _current_avatar_src(username: str) -> str:
        pfp_path = core.get_profile_picture_path(cfg)
        if pfp_path:
            try:
                with open(pfp_path, "rb") as f:
                    return f.read()
            except OSError:
                pass
        return core.get_skin_face_url(username)

    sidebar_avatar = ft.CircleAvatar(
        foreground_image_src=_current_avatar_src(cfg["username"]),
        radius=14,
        bgcolor=SURFACE_HI,
    )
    sidebar_username_text = ft.Text(
        cfg["username"], size=14, weight=ft.FontWeight.W_600,
        color=TEXT, font_family=FONT_MONO,
    )

    # --- Profile tab: bigger avatar, upload/remove picture, username ---

    profile_dialog_avatar = ft.CircleAvatar(
        foreground_image_src=_current_avatar_src(cfg["username"]),
        radius=48,
        bgcolor=SURFACE_HI,
    )
    # Little animated companion perched on the avatar's shoulder - pure
    # decoration, no state of its own, so it's just an Image placed via
    # Stack rather than threaded through refresh_avatars()/cfg like the
    # actual profile picture is.
    profile_parrot = ft.Image(
        src="parrot.gif", width=40, height=46, fit=ft.BoxFit.CONTAIN,
    )
    profile_avatar_with_parrot = ft.Stack(
        [
            ft.Container(content=profile_dialog_avatar, width=96, height=96),
            ft.Container(
                content=profile_parrot,
                left=62, top=-6,  # perched over the avatar's top-right edge
            ),
        ],
        width=104, height=100,
    )
    profile_dialog_username = ft.Text(
        cfg["username"], size=20, color=TEXT, font_family=FONT_DISPLAY,
    )
    profile_pfp_status = ft.Text("", size=12, color=TEXT_DIM)

    def refresh_avatars():
        """Called after upload/remove/username-change so the sidebar and
        the dialog's own avatar never fall out of sync with each other."""
        src = _current_avatar_src(cfg["username"])
        sidebar_avatar.foreground_image_src = src
        profile_dialog_avatar.foreground_image_src = src
        sidebar_username_text.value = cfg["username"]
        profile_dialog_username.value = cfg["username"]

    def handle_pfp_files(files):
        if not files:
            return
        picked = files[0]
        profile_pfp_status.value = "Uploading..."
        page.update()
        try:
            core.set_profile_picture(picked.path)
            cfg["profile_picture"] = "avatar.png"
            core.save_config(cfg)
            refresh_avatars()
            profile_pfp_status.value = "Profile picture updated."
        except ValueError as ve:
            profile_pfp_status.value = str(ve)
        except Exception as ex:
            profile_pfp_status.value = f"Upload failed: {ex}"
        page.update()

    def on_pfp_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Not type-hinted as
        # ft.FilePickerResultEvent - that class doesn't exist on every
        # Flet build (e.g. it's gone in 0.86.x, which is otherwise the
        # pinned/tested version), and a hard annotation on it would crash
        # this function's definition at import time on those builds. See
        # run_file_picker()'s docstring in cubeon/config.py for the same
        # version-spanning reasoning.
        handle_pfp_files(e.files)

    pfp_file_picker = ft.FilePicker()
    pfp_file_picker.on_result = on_pfp_picked

    # Same version-spanning registration dance used for the skin uploader's
    # FilePicker in skin_tab.py - newer Flet self-registers Services,
    # older Flet needs the explicit page.overlay append.
    _pfp_registered = False
    _services_list = getattr(page, "_services", None)
    _already_registered = (
        _services_list is not None
        and hasattr(_services_list, "_services")
        and pfp_file_picker in _services_list._services
    )
    _register_fn = getattr(page, "register_service", None)
    if _already_registered:
        _pfp_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(pfp_file_picker)
            _pfp_registered = True
        except Exception:
            _pfp_registered = False
    if not _pfp_registered:
        try:
            if pfp_file_picker not in page.overlay:
                page.overlay.append(pfp_file_picker)
        except Exception:
            pass

    def open_pfp_picker(e=None):
        run_file_picker(
            page, pfp_file_picker,
            on_files=handle_pfp_files,
            dialog_title="Choose a profile picture",
            allow_multiple=False,
            allowed_extensions=["png", "jpg", "jpeg", "webp", "gif", "bmp"],
        )

    # Skin FilePicker - created and registered once here (same pattern as
    # pfp_file_picker above), then passed into build_skin_section() on every
    # rebuild instead of letting that function create its own each time.
    skin_file_picker = ft.FilePicker()

    _skin_registered = False
    _skin_services_list = getattr(page, "_services", None)
    _skin_already_registered = (
        _skin_services_list is not None
        and hasattr(_skin_services_list, "_services")
        and skin_file_picker in _skin_services_list._services
    )
    if _skin_already_registered:
        _skin_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(skin_file_picker)
            _skin_registered = True
        except Exception:
            _skin_registered = False
    if not _skin_registered:
        try:
            if skin_file_picker not in page.overlay:
                page.overlay.append(skin_file_picker)
        except Exception:
            pass

    # Cape FilePicker - same create-and-register-once pattern as the skin
    # picker above. The skin section rebuilds on every Profile open, so the
    # cape uploader (like the skin one) must reuse a single shared, already-
    # registered picker rather than making a fresh one each rebuild (only the
    # first registration ever receives results - see build_skin_section()).
    cape_file_picker = ft.FilePicker()

    _cape_registered = False
    _cape_services_list = getattr(page, "_services", None)
    _cape_already_registered = (
        _cape_services_list is not None
        and hasattr(_cape_services_list, "_services")
        and cape_file_picker in _cape_services_list._services
    )
    if _cape_already_registered:
        _cape_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(cape_file_picker)
            _cape_registered = True
        except Exception:
            _cape_registered = False
    if not _cape_registered:
        try:
            if cape_file_picker not in page.overlay:
                page.overlay.append(cape_file_picker)
        except Exception:
            pass

    def on_remove_pfp(e=None):
        core.clear_profile_picture(cfg)
        refresh_avatars()
        profile_pfp_status.value = "Profile picture removed."
        page.update()

    # --- Username field (Profile tab's own copy) ---
    # Mirrors the Play tab's username field - offline accounts are keyed
    # entirely off the username, so editing it here changes the signed-in
    # account exactly the same way editing it on Play does. Both fields
    # stay in sync via refresh_avatars()/sync_username_fields() below.

    profile_username_field = ft.TextField(
        value=cfg["username"],
        label="Username",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        text_style=ft.TextStyle(font_family=FONT_MONO),
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=52,
        # Pencil affordance inside the field (right edge) - the field is
        # directly editable, the icon just signals "this is editable" the
        # way the target layout shows it.
        suffix_icon=ft.Icons.EDIT_ROUNDED,
    )

    def on_profile_username_change(e=None):
        name = profile_username_field.value.strip()
        ok, err = core.validate_username(name)
        if not ok:
            profile_username_field.error_text = err
            page.update()
            return
        profile_username_field.error_text = None
        cfg["username"] = name
        # CustomSkinLoader looks the skin up by <USERNAME>.png, so a rename
        # has to move the synced file or the skin stops resolving.
        core.sync_local_skin_to_csl(cfg)
        # A rename moves the cape file too, same reason (CSL reads it as
        # LocalSkin/capes/<USERNAME>.png).
        core.sync_local_cape_to_csl(cfg)
        core.save_config(cfg)
        refresh_avatars()
        # Keep the Play tab's username field showing the same name, without
        # re-triggering its own on_change (which would just redo this work).
        if username_field.value != name:
            username_field.value = name
        page.update()

    profile_username_field.on_change = on_profile_username_change
    profile_username_field.on_blur = on_profile_username_change

    # --- Skin section container - rebuilt each time the dialog opens, so
    # the CustomSkinLoader-installed notice reflects whatever version/mod
    # loader is currently selected on the Play tab. ---

    skin_section_container = ft.Container()

    def rebuild_skin_section():
        skin_section_container.content = build_skin_section(
            page, cfg,
            section_label=section_label, pixel_divider=pixel_divider,
            **THEME,
            mc_version=version_dropdown.value, mc_loader=state.get("mod_loader"),
            file_picker=skin_file_picker,
            cape_file_picker=cape_file_picker,
        )

    # Profile tab content - a plain scrollable column like every other tab,
    # using the full content width instead of a fixed centered column.
    #
    # Layout: a header CARD laid out as one horizontal row -
    #   [ avatar ]  [ name + "Cubeon Profile" + username field ]  [ picture actions ]
    # then the in-game skin card below it. Left-aligned and side-by-side
    # rather than the old centered stack.
    profile_pfp_upload_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.UPLOAD_ROUNDED, color=ON_ACCENT, size=16),
                ft.Text("Upload", color=ON_ACCENT, weight=ft.FontWeight.W_700, size=13),
            ],
            alignment=ft.MainAxisAlignment.CENTER, spacing=6, tight=True,
        ),
        bgcolor=ACCENT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=11, horizontal=18),
        ink=True, on_click=open_pfp_picker,
    )
    profile_pfp_remove_btn = ft.Container(
        content=ft.Text("Remove", color=DANGER, weight=ft.FontWeight.W_700, size=13),
        border=ft.border.Border.all(1, DANGER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=11, horizontal=18),
        ink=True, on_click=on_remove_pfp, alignment=ft.Alignment.CENTER,
    )

    profile_tab = ft.Column(
        [
            ft.Column(
                    [
                        # --- Header card: avatar | identity + username | picture actions ---
                        ft.Container(
                            content=ft.Row(
                                [
                                    # Left: avatar
                                    profile_avatar_with_parrot,
                                    ft.Container(width=20),
                                    # Center: name + editable username field
                                    ft.Column(
                                        [
                                            profile_dialog_username,
                                            ft.Container(height=14),
                                            ft.Container(width=340, content=profile_username_field),
                                        ],
                                        spacing=2,
                                        expand=True,
                                    ),
                                    ft.Container(width=20),
                                    # Right: profile picture upload/remove
                                    ft.Column(
                                        [
                                            section_label("Profile picture"),
                                            ft.Container(height=8),
                                            ft.Row(
                                                [profile_pfp_upload_btn, profile_pfp_remove_btn],
                                                spacing=10,
                                            ),
                                            profile_pfp_status,
                                        ],
                                        spacing=2,
                                        horizontal_alignment=ft.CrossAxisAlignment.START,
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.START,
                            ),
                            bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
                        ),

                        ft.Container(height=24),

                        # --- Section: in-game skin (see skin_tab.py) ---
                        ft.Container(
                            content=skin_section_container,
                            bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
                        ),
                    ],
                    spacing=2,
            ),
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    def refresh_profile_tab():
        """Called whenever the Profile tab becomes active, so its fields
        and the embedded skin section reflect current state (username,
        selected version/loader) rather than whatever was last built."""
        profile_pfp_status.value = ""
        profile_username_field.value = cfg["username"]
        profile_username_field.error_text = None
        rebuild_skin_section()

    # Column that holds all nav buttons
    sidebar_column = ft.Column(build_nav(), spacing=2)

    # Brand mark - the app icon plus wordmark, shown once at the top of the
    # sidebar so the launcher has a consistent visual identity every time
    # it's open, not just as a taskbar/window icon.
    sidebar_brand = ft.Row(
        [
            # The cube mark as a static vector (assets/cube.svg), extracted
            # from the icon's own polygons - crisp at any size, no hand-drawn
            # animation frames to go muddy.
            ft.Image(src="cube.svg", width=32, height=32, fit=ft.BoxFit.CONTAIN),
            ft.Text("Cubeon", size=19, color=TEXT, font_family=FONT_DISPLAY),
        ],
        spacing=10,
    )

    # The sidebar container. It sits directly on the canvas gradient with no
    # fill and no dividing border - separation comes from the content surface
    # beside it being one step lighter, not from a drawn line. Narrower than
    # before: a rail should navigate, not dominate.
    sidebar = ft.Container(
        content=ft.Column(
            [
                sidebar_brand,
                ft.Container(height=22),  # spacer between brand and nav
                sidebar_column,  # The navigation buttons
                ft.Container(expand=True),  # Spacer to push the user info to the bottom
                # Dev-only UI inspector toggle (CUBEON_INSPECT=1): opens the
                # live text/property editor. Lives just above the user block
                # so it's reachable but never part of the shipped nav.
                *([] if not _inspector_enabled else [
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.BUG_REPORT, size=14, color=TEXT_FAINT),
                            ft.Text("Inspect UI", size=12, color=TEXT_FAINT),
                        ], spacing=8),
                        padding=ft.padding.Padding.only(left=12, bottom=6),
                        on_click=lambda e: _open_inspector(),
                    ),
                ]),
                # Bottom section: shows the current signed-in username with
                # avatar - clickable, switches to the Profile tab (view
                # profile, upload/remove profile picture).
                ft.Container(
                    content=ft.Column(
                        [
                            section_label("Signed in as"),
                            ft.Row(
                                [
                                    sidebar_avatar,
                                    sidebar_username_text,
                                ],
                                spacing=10,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=ft.padding.Padding.only(top=14),
                    border=ft.border.Border.only(top=ft.border.BorderSide(1, CARD_BORDER)),
                    border_radius=RADIUS,
                    on_click=lambda e: switch_tab("profile"),
                ),
            ],
            expand=True,
        ),
        width=200,
        padding=ft.padding.Padding.only(left=16, right=12, top=18, bottom=16),
    )

    # -----------------------------------------------------------------
    # PLAY TAB - the main "Play" tab content
    # -----------------------------------------------------------------

    # --- UI elements for the Play tab ---

    # Username input field - pre-filled with the stored username from config
    username_field = ft.TextField(
        value=cfg["username"],
        label="Username",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        text_style=ft.TextStyle(font_family=FONT_MONO),  # Use monospaced for usernames
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=52,
    )

    def on_username_change(e=None):
        """
        Live-updates the in-game display name as soon as the username changes,
        instead of waiting for Play to be clicked. The username is now purely a
        display/impersonable name: the account's real UUID comes from the stable
        auth_key.json identity (core.stable_uuid()), so a rename keeps the same
        player UUID, cosmetics, and friends account - only the visible name and
        the CustomSkinLoader <USERNAME>.png mirror move. Refreshed here so the
        sidebar and skin preview reflect the new name immediately.
        """
        name = username_field.value.strip()
        ok, err = core.validate_username(name)
        if not ok:
            username_field.error_text = err
            page.update()
            return
        username_field.error_text = None

        # Persist immediately so the new identity survives even if the
        # user navigates away without clicking Play.
        cfg["username"] = name
        # CustomSkinLoader looks the skin up by <USERNAME>.png, so a rename
        # has to move the synced file or the skin stops resolving.
        core.sync_local_skin_to_csl(cfg)
        # A rename moves the cape file too, same reason (CSL reads it as
        # LocalSkin/capes/<USERNAME>.png).
        core.sync_local_cape_to_csl(cfg)
        core.save_config(cfg)

        # Refresh the sidebar + profile dialog avatar/label.
        refresh_avatars()
        # Keep the profile dialog's own username field showing the same
        # name, without re-triggering its on_change (which would just redo
        # this same work).
        if profile_username_field.value != name:
            profile_username_field.value = name
        page.update()

    username_field.on_change = on_username_change
    username_field.on_blur = on_username_change

    # Dropdown to select a Minecraft version (installed or available online)
    version_dropdown = ft.Dropdown(
        label="Version",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM),
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=52,
        options=[],  # Will be populated later
        on_select=lambda e: on_version_selected(),  # Called when user picks a version
    )

    # Ordered list of loader ids backing the segmented switcher below - Vanilla
    # plus every mod loader launcher_core knows how to install (Fabric, Quilt,
    # Forge, NeoForge). Index in this list == selected_index on the control.
    LOADER_IDS = list(core.SUPPORTED_LOADERS.keys())

    # Per-segment label controls, kept around so we can restyle them once we
    # actually know (installed / available / unsupported) for the currently
    # selected version, instead of a static row of plain text.
    loader_segment_labels = [
        ft.Text(core.SUPPORTED_LOADERS[lid], color=ACCENT_HI if i == 0 else TEXT_DIM,
                 size=13, weight=ft.FontWeight.W_600)
        for i, lid in enumerate(LOADER_IDS)
    ]
    # Small dot under each label - green once we've confirmed that loader is
    # already installed for the selected version, hollow/dim otherwise.
    loader_segment_dots = [
        ft.Container(width=5, height=5, border_radius=RADIUS, bgcolor=ft.Colors.with_opacity(0, ACCENT))
        for _ in LOADER_IDS
    ]
    loader_segment_columns = [
        ft.Column([loader_segment_labels[i], loader_segment_dots[i]],
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, tight=True)
        for i in range(len(LOADER_IDS))
    ]

    loader_status_text = ft.Text("", size=11, color=TEXT_DIM, visible=False)

    # Switcher between Vanilla and each supported mod loader. The thumb is a
    # *subtle* deep-green pill rather than a bright slab, so the selected
    # option reads via its green label + the quiet thumb behind it while the
    # inactive ones stay clearly visible (TEXT_DIM) - previously the active
    # segment was near-white-on-green and everything else was nearly invisible.
    loader_toggle = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,  # index into LOADER_IDS
        thumb_color="#32431D",  # ACCENT_DIM blended over SURFACE_HI - restrained
        bgcolor=SURFACE_HI,
        padding=4,
        controls=loader_segment_columns,
        on_change=lambda e: on_loader_toggle_change(e.control.selected_index),
    )

    # Cache of the last support/installed check, keyed by version id, so
    # re-visiting a version you've already checked this session doesn't
    # re-hit the network every time.
    loader_check_cache: dict[str, dict[str, tuple[bool, bool]]] = {}

    def style_loader_segments(support: "dict[str, tuple[bool, bool]] | None"):
        """Repaints each segment's label/dot based on a support map of
        {loader_id: (supported, installed)}. A None map means "not checked
        yet" - every segment is shown at full opacity with no dot, since we
        don't yet know better and shouldn't guess.

        Once the selected version is already installed, the loader choice is
        locked in (see refresh_loader_support / on_loader_toggle_change) - all
        non-selected segments are dimmed to make clear they can't be picked."""
        version_id = version_dropdown.value
        locked = bool(version_id and version_id in state["installed"])
        for i, lid in enumerate(LOADER_IDS):
            label = loader_segment_labels[i]
            dot = loader_segment_dots[i]
            is_selected = (i == loader_toggle.selected_index)
            # Selected = bright green on the deep-green thumb; the rest stay
            # at readable dim text instead of vanishing.
            base_color = ACCENT_HI if is_selected else TEXT_DIM
            if support is None or lid == "vanilla":
                label.color = base_color
                label.opacity = 1 if (not locked or is_selected) else 0.45
                dot.bgcolor = ft.Colors.with_opacity(0, ACCENT)
                continue
            supported, installed = support.get(lid, (True, False))
            label.color = base_color
            if locked:
                label.opacity = 1 if is_selected else 0.45
            else:
                label.opacity = 1 if supported else 0.45
            # Green dot = already installed for this version, so switching
            # to it will jump straight to Play instead of downloading.
            dot_color = ACCENT if is_selected else ACCENT_DIM
            dot.bgcolor = ft.Colors.with_opacity(1 if installed else 0, dot_color)
        page.update()

    def refresh_loader_support(version_id):
        """Runs in the background: checks every loader's support + installed
        status for version_id, then repaints the switcher. This is what makes
        the switcher "real" - it reflects the actual state of the selected
        version instead of always looking the same regardless of context.

        The loader is only a choice at install time: once version_id is
        already installed, we detect which loader (if any) it was installed
        with, lock the switcher to that, and disable it outright - switching
        loaders on an existing install would silently reinstall/relaunch
        under a different loader, which is surprising and not what "install"
        means here. For a not-yet-installed version, the switcher stays free
        to pick from."""
        if not version_id:
            style_loader_segments(None)
            loader_status_text.visible = False
            page.update()
            return

        already_installed = version_id in state["installed"]

        cached = loader_check_cache.get(version_id)
        if cached:
            if already_installed:
                lock_loader_to_installed(version_id, cached)
            else:
                loader_toggle.disabled = False
            style_loader_segments(cached)
            loader_status_text.visible = False
            page.update()
            return

        loader_toggle.disabled = True
        loader_status_text.value = "Checking loader availability..."
        loader_status_text.visible = True
        page.update()

        def worker():
            support = {}
            for lid in LOADER_IDS:
                if lid == "vanilla":
                    continue
                try:
                    supported = core.is_loader_supported(lid, version_id)
                except Exception:
                    supported = False
                installed = bool(core.find_installed_loader_version(state["installed"], lid, version_id))
                support[lid] = (supported, installed)
            loader_check_cache[version_id] = support

            # If the user already moved on to a different version while this
            # was running, don't paint stale results over the new selection.
            if version_dropdown.value != version_id:
                return

            loader_status_text.visible = False
            if already_installed:
                # Already installed - the loader was decided at install time.
                # Detect which one and lock the switcher to it.
                lock_loader_to_installed(version_id, support)
                style_loader_segments(support)
                page.update()
                return

            loader_toggle.disabled = False
            style_loader_segments(support)
            # If the currently-selected loader turned out to be unsupported
            # for this version, fall back to the first supported one rather
            # than silently letting the user hit "unsupported" at launch.
            selected_id = LOADER_IDS[loader_toggle.selected_index]
            if not support.get(selected_id, (True, False))[0]:
                fallback = next((lid for lid in LOADER_IDS
                                 if support.get(lid, (False, False))[0]), None)
                if fallback and fallback != selected_id:
                    loader_status_text.value = (
                        f"{core.SUPPORTED_LOADERS[selected_id]} isn't available "
                        f"for this version, switched to {core.SUPPORTED_LOADERS[fallback]}.")
                    loader_status_text.visible = True
                    loader_toggle.selected_index = LOADER_IDS.index(fallback)
                    state["mod_loader"] = fallback
                    style_loader_segments(support)
                    refresh_mods_list()
                    refresh_browse_for_new_profile()
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    def lock_loader_to_installed(version_id, support):
        """For a version that's already installed, figure out which loader
        (if any) it was installed with, snap the switcher to it, and disable
        the switcher so it can't be changed after the fact. Mod loader choice
        only happens at install time - see refresh_loader_support."""
        # Prefer the loader that's already selected when it's genuinely
        # installed for this version. A version can have more than one loader
        # installed at once (e.g. a modpack's Fabric install plus a manual
        # Forge one), and blindly taking the first installed loader in list
        # order would then lock to the wrong one - clobbering the loader a
        # modpack handoff just set. Falling back to first-installed only when
        # the current pick isn't installed keeps old single-loader behaviour.
        current = state.get("mod_loader")
        detected = None
        if current and support.get(current, (False, False))[1]:
            detected = current
        # Also check vanilla: a bare mc_version in installed_ids means
        # a vanilla (loader-less) install. Vanilla is always supported
        # and appears in LOADER_IDS, so check it explicitly if no mod
        # loader was detected above.
        if detected is None and "vanilla" in LOADER_IDS:
            if core.find_installed_loader_version(state["installed"], "vanilla", version_id):
                detected = "vanilla"
        if detected is None:
            for lid in LOADER_IDS:
                if lid == "vanilla":
                    continue
                if support.get(lid, (False, False))[1]:
                    detected = lid
                    break
        if detected in LOADER_IDS:
            loader_toggle.selected_index = LOADER_IDS.index(detected)
        else:
            # Fallback: keep the switcher on the first option and disabled.
            loader_toggle.selected_index = 0
        state["mod_loader"] = detected
        # Keep the switcher clickable: the handler allows a one-way switch
        # back to Vanilla for an installed version, and snaps anything else.
        loader_toggle.disabled = False
        update_hero()
        update_pack_badge()

    def on_loader_toggle_change(idx):
        """Updates the state when the loader switcher changes, and refreshes
        everything that depends on it (mod list is per version+loader profile,
        and the play button availability can change since the loader may not
        be installed for the currently selected version)."""
        version_id = version_dropdown.value
        new_loader = LOADER_IDS[idx] if 0 <= idx < len(LOADER_IDS) else LOADER_IDS[0]
        if version_id and version_id in state["installed"]:
            # Loader is locked in once a version is installed - a mod loader
            # can't be swapped after the fact (packs key off it). Switching
            # BACK to vanilla is always allowed though: the plain version id
            # is already on disk, no install is needed, and the launch just
            # skips the mods folder.
            if new_loader == "vanilla" and state["mod_loader"] != "vanilla":
                state["mod_loader"] = "vanilla"
                loader_status_text.value = "Switched to Vanilla - mods won't load for this version."
                loader_status_text.visible = True
                style_loader_segments(loader_check_cache.get(version_id))
                refresh_mods_list()
                on_version_selected()
                page.update()
                return
            loader_toggle.selected_index = max(0, LOADER_IDS.index(state["mod_loader"])) \
                if state["mod_loader"] in LOADER_IDS else 0
            page.update()
            return
        cached = loader_check_cache.get(version_id) if version_id else None
        if cached and not cached.get(new_loader, (True, False))[0]:
            # Block the switch outright - snap back and explain, rather than
            # letting the user pick something that will only fail later.
            loader_toggle.selected_index = max(0, LOADER_IDS.index(state["mod_loader"])) \
                if state["mod_loader"] in LOADER_IDS else 0
            loader_status_text.value = f"{core.SUPPORTED_LOADERS[new_loader]} isn't available for this version."
            loader_status_text.visible = True
            page.update()
            return
        loader_status_text.visible = False
        state["mod_loader"] = new_loader
        style_loader_segments(cached)
        refresh_mods_list()
        on_version_selected()

    # A row for "Show snapshots" checkbox (visible only when browsing online)
    browse_online_row = ft.Row(
        [
            ft.Checkbox(
                label="Show snapshots", value=False, check_color=BG, active_color=ACCENT,
                label_style=ft.TextStyle(color=TEXT_DIM, size=12),
                on_change=lambda e: refresh_version_list(online=True),  # Reload versions when toggled
            ),
        ],
        visible=False,  # Hidden by default
    )
    show_snapshots = browse_online_row.controls[0]  # Reference to the checkbox

    # Online mode pulls in every release Mojang has ever shipped (600+
    # entries) with no way to jump to one - the raw dropdown became a wall of
    # text nobody could scan. This filters that list live as the user types
    # (e.g. "1.20" narrows straight to the 1.20.x releases) instead of making
    # them scroll past hundreds of versions from 2011 onward to find one from
    # this year. Only shown once there's actually a long online list to
    # filter; the short offline (installed-only) list doesn't need it.
    all_online_options = {"value": []}  # full unfiltered list, cached across filter keystrokes

    def _filter_versions(e=None):
        query = (version_filter_field.value or "").strip().lower()
        if not query:
            version_dropdown.options = all_online_options["value"]
        else:
            version_dropdown.options = [
                o for o in all_online_options["value"] if query in o.key.lower()
            ]
        if not version_dropdown.options:
            version_dropdown.value = None
        elif version_dropdown.value not in {o.key for o in version_dropdown.options}:
            version_dropdown.value = version_dropdown.options[0].key
            on_version_selected()
        page.update()

    version_filter_field = ft.TextField(
        hint_text="Filter versions... e.g. 1.20",
        border_color=BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=44,
        text_size=13,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_change=_filter_versions,
        visible=False,  # shown only once online browsing is active
    )

    # Notice shown when offline (no internet)
    offline_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, color=TEXT_DIM, size=14),
                ft.Text("No internet. Showing installed versions only.", size=12, color=TEXT_DIM),
            ],
            spacing=8,
        ),
        visible=False,
    )

    # Link to browse online versions (when clicked, fetches versions from Mojang)
    browse_online_link = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CLOUD_DOWNLOAD_ROUNDED, color=ACCENT, size=14),
                ft.Text("Browse online versions", size=12, color=ACCENT, weight=ft.FontWeight.W_600),
            ],
            spacing=8,
        ),
        on_click=lambda e: refresh_version_list(online=True),
        ink=True,
    )

    # Progress bar and label shown during installation/launch
    progress_bar = ft.ProgressBar(
        value=0, bgcolor=SURFACE_HI, color=ACCENT, bar_height=6, border_radius=RADIUS,
        visible=False,
    )
    progress_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO, visible=False)

    # Small native spinner next to the progress label during installs/launches
    # - a crisp, animated ProgressRing (no image asset), so "something's
    # working" has one consistent visual instead of a bare progress bar with
    # no motion of its own while a step (e.g. extracting) sits at a static
    # percentage.
    progress_spinner = ft.ProgressRing(
        width=16, height=16, stroke_width=2, color=ACCENT, visible=False,
    )
    progress_row = ft.Row(
        [progress_spinner, progress_label], spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # The main play button - its appearance changes based on state (play/download/busy)
    play_button_icon = ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, color=ON_ACCENT, size=22)
    play_button_text = ft.Text("PLAY", size=16, color=ON_ACCENT,
                                font_family=FONT_DISPLAY)

    def _on_play_hover(e):
        """Brighten the hero button on hover so it reads as the obvious next
        step. Only the two live fills (play=green, download=cyan) react; the
        disabled busy/running/incomplete states must not appear clickable."""
        if play_button.disabled:
            return
        hovering = e.data == "true"
        if play_button_text.value == "PLAY":
            play_button.bgcolor = ACCENT_HI if hovering else ACCENT
        else:  # download
            play_button.bgcolor = "#63C7D8" if hovering else INFO
        play_button.update()

    play_button = ft.Container(
        content=ft.Row(
            [play_button_icon, play_button_text],
            alignment=ft.MainAxisAlignment.CENTER, spacing=6,
        ),
        bgcolor=ACCENT,
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=16),
        alignment=ft.Alignment.CENTER,
        ink=True,
        on_click=lambda e: on_play_click(),  # The main action
        on_hover=_on_play_hover,
    )

    # Text to show any issues with the selected version (e.g., incomplete install)
    version_issue_text = ft.Text("", size=12, color=DANGER, visible=False)

    # When the selected version+loader is one an installed modpack owns, show
    # the pack's real name here. Without it a pack reads only as its bare MC
    # version + loader (e.g. "1.20.1 (Fabric)"), so the user can't tell which
    # pack they're about to launch - see go_to_pack / update_pack_badge.
    pack_name_text = ft.Text("", size=12, color=ACCENT, weight=ft.FontWeight.W_600,
                             font_family=FONT_MONO)
    pack_name_badge = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=ACCENT, size=15), pack_name_text],
            spacing=6,
        ),
        visible=False,
    )

    # --- Helper functions for the Play tab ---

    def set_button_mode(mode):
        """
        Changes the play button's appearance based on the current state.
        Modes:
          - 'play': ready to launch (green)
          - 'download': version not installed, offer download (cyan)
          - 'busy': working on something before launch, e.g. installing (disabled, spinning icon)
          - 'running': the game process is currently open (disabled, distinct look)
          - 'incomplete': installed but broken (disabled, error icon)

        Foreground colour is set per-mode alongside the fill, not just once at
        creation: the play/download fills are light (green/cyan) so they take
        dark ON_ACCENT text, but the disabled busy/running/incomplete fills are
        dark (SURFACE_HI) - leaving the text dark there rendered it nearly
        invisible (dark-on-dark). Each disabled state now also carries a
        *semantic* colour so the button's meaning reads at a glance: dim = a
        transient wait, green = the game is live, red = a broken install.
        """
        def paint(bg, fg):
            play_button.bgcolor = bg
            play_button_icon.color = fg
            play_button_text.color = fg

        if mode == "play":
            paint(ACCENT, ON_ACCENT)
            play_button_icon.name = ft.Icons.PLAY_ARROW_ROUNDED
            play_button_text.value = "PLAY"
            play_button.disabled = False
        elif mode == "download":
            paint(INFO, ON_ACCENT)  # diamond cyan = download, not play (on-palette)
            play_button_icon.name = ft.Icons.DOWNLOAD_ROUNDED
            play_button_text.value = "DOWNLOAD & PLAY"
            play_button.disabled = False
        elif mode == "busy":
            paint(SURFACE_HI, TEXT_DIM)
            play_button_icon.name = ft.Icons.HOURGLASS_TOP_ROUNDED
            play_button_text.value = "WORKING..."
            play_button.disabled = True
        elif mode == "running":
            paint(SURFACE_HI, ACCENT)
            play_button_icon.name = ft.Icons.SPORTS_ESPORTS_ROUNDED
            play_button_text.value = "GAME RUNNING..."
            play_button.disabled = True
        elif mode == "incomplete":
            paint(SURFACE_HI, DANGER)
            play_button_icon.name = ft.Icons.ERROR_OUTLINE_ROUNDED
            play_button_text.value = "INCOMPLETE INSTALL"
            play_button.disabled = True
        page.update()  # Refresh UI to show changes

    def _refresh_pack_index():
        """Rebuild the (mc_version, loader) -> modpack-name lookup from disk.
        Cheap (reads a handful of small _modpack.json files); called whenever
        the version list is rebuilt so the Play tab can name an installed pack.
        """
        try:
            packs = core.list_installed_modpacks()
        except Exception:
            packs = []
        state["pack_index"] = {
            (p.get("mc_version"), p.get("loader")): p.get("name")
            for p in packs if p.get("mc_version")
        }

    def update_pack_badge():
        """Show the pack name badge iff the current version+loader is a modpack
        install. Keyed on (version, loader) because that pair is the profile a
        pack's mods live in - the same identity launch uses."""
        name = state.get("pack_index", {}).get(
            (state.get("selected_mc_version"), state.get("mod_loader")))
        if name:
            pack_name_text.value = name
            pack_name_badge.visible = True
        else:
            pack_name_badge.visible = False
        page.update()

    _install_locks: dict[str, threading.Lock] = {}

    def _install_lock(version_id: str) -> threading.Lock:
        """One lock per version id so a background prefetch and an actual
        Play click can never run Mojang's installer for the same version
        concurrently (duplicated downloads, interleaved writes)."""
        lock = _install_locks.get(version_id)
        if lock is None:
            lock = threading.Lock()
            _install_locks[version_id] = lock
        return lock

    _prefetched: set[str] = set()

    def prefetch_version(version_id: str | None) -> None:
        """Starts downloading the selected version in the background the
        moment it's chosen, so by the time the user clicks Play the assets,
        libraries and jar are already on disk and the launch begins
        immediately instead of behind a progress bar. Safe to call often:
        each version is prefetched at most once per session, and the per-
        version install lock keeps it from racing the real installer."""
        if not version_id or version_id in _prefetched:
            return
        _prefetched.add(version_id)

        def _work():
            try:
                with _install_lock(version_id):
                    if version_id in state["installed"]:
                        return  # someone beat us to it
                    core.install_version(
                        version_id,
                        progress_cb=lambda v: None,
                        status_cb=lambda t: None,
                        max_cb=lambda m: None,
                    )
                    state["installed"].add(version_id)
                    try:
                        # The version is on disk now, so the hero button must
                        # stop saying DOWNLOAD. page.update() alone repaints
                        # the old label - the mode has to be recomputed.
                        if version_dropdown.value == version_id:
                            set_button_mode("play")
                        page.update()
                    except Exception:
                        pass
            except Exception:
                _prefetched.discard(version_id)  # allow a retry

        threading.Thread(target=_work, name="version-prefetch", daemon=True).start()

    def on_version_selected():
        """
        Called when the user selects a version from the dropdown.
        It checks if the version is installed, and if it's complete or incomplete.
        Then it updates the play button mode accordingly.
        """
        version_id = version_dropdown.value
        state["selected_version"] = version_id  # keep Mods/Servers tabs in sync with the dropdown
        # Separate "clean" numeric version for anything that keys off a mods
        # profile folder. version_id is the raw launch id and for
        # TLauncher/manually-installed instances that's frequently something
        # like "1.20.1-forge-47.2.0" rather than a bare "1.20.1" - using it
        # directly as a profile key silently pointed the Mods tab and
        # sync_mods_to_game() at an empty folder that nothing else ever
        # wrote to, which is why installed mods didn't show up or apply.
        state["selected_mc_version"] = core.extract_mc_version(version_id) if version_id else None
        # Rename/Delete only apply to a version that's actually installed
        # (an online-only entry has nothing on disk to manage yet).
        _installed_sel = bool(version_id and version_id in state["installed"])
        rename_instance_btn.disabled = not _installed_sel
        delete_instance_btn.disabled = not _installed_sel
        rename_instance_btn.opacity = 1 if _installed_sel else 0.4
        delete_instance_btn.opacity = 1 if _installed_sel else 0.4
        refresh_mods_list()
        refresh_browse_for_new_profile()
        refresh_loader_support(version_id)
        refresh_server_status_panel()
        update_pack_badge()
        update_hero()               # hero title/meta follow the selection
        if active_tab["value"] in {"server_console", "server_plugins", "server_settings"}:
            refresh_server_tab()
        meta = state["installed_meta"].get(version_id)
        if meta and meta.get("incomplete"):
            # The version exists but is missing files - show error and disable play
            version_issue_text.value = meta.get("issue", "This install is missing files.")
            version_issue_text.visible = True
            set_button_mode("incomplete")
        elif version_id and version_id in state["installed"]:
            # Installed and complete - ready to play
            version_issue_text.visible = False
            set_button_mode("play")
        else:
            # Not installed - offer to download, and quietly start the
            # download in the background so Play is instant when clicked.
            version_issue_text.visible = False
            set_button_mode("download")
            prefetch_version(version_id)

    def refresh_version_list(online=False):
        """
        Populates the version dropdown with available versions.

        If online=False (default): shows only locally installed versions.
        If online=True: fetches the full list from Mojang (may take a moment).

        This function is called at startup, when the user clicks "Browse online versions",
        or when the "Show snapshots" checkbox changes.
        """
        # First, get the currently installed versions (might have changed since last time)
        installed = core.get_installed_versions()
        state["installed"] = {v["id"] for v in installed}
        state["installed_meta"] = {v["id"]: v for v in installed}
        _refresh_pack_index()  # keep the version+loader -> pack-name map current

        if not online:
            # Offline mode: only installed versions
            _labels = cfg.get("version_labels") or {}
            options = [
                ft.dropdown.Option(
                    key=v["id"],
                    text=f"{_labels.get(v['id']) or v.get('display_name', v['id'])}  {'⚠' if v.get('incomplete') else '●'}",
                )
                for v in installed
            ]
            version_dropdown.options = options
            browse_online_row.visible = False
            offline_notice.visible = False
            version_filter_field.visible = False
            version_filter_field.value = ""

            # Select the first option or the previously selected version
            if options:
                if state["selected_version"] and any(o.key == state["selected_version"] for o in options):
                    version_dropdown.value = state["selected_version"]
                else:
                    version_dropdown.value = options[0].key
                on_version_selected()
            else:
                version_dropdown.value = None
                version_dropdown.hint_text = "No versions installed yet"
                # Nothing is selectable, so there is no instance - clear the
                # stale selection in state too. It was primed from
                # config["last_version"] at startup, and leaving it set points
                # the Mods tab / sync at the OLD version's profile folder
                # (whose mods are still on disk), so it would show "X installed"
                # and mark browse rows as already downloaded with no instance
                # actually selected.
                state["selected_version"] = None
                state["selected_mc_version"] = None
                refresh_mods_list()
                refresh_browse_for_new_profile()
                update_hero()
            page.update()
            return

        # Online mode: fetch versions from Mojang
        set_status("Checking for versions", busy=True)
        try:
            versions = core.get_available_versions(include_snapshots=show_snapshots.value)
        except Exception:
            # If network fails, show the offline notice
            offline_notice.visible = True
            browse_online_row.visible = False
            version_filter_field.visible = False
            set_status("Offline")
            page.update()
            return

        # Build options: show installed versions with a "●" marker
        _labels = cfg.get("version_labels") or {}
        options = []
        for v in versions:
            is_installed = v["id"] in state["installed"]
            tag = "  ●" if is_installed else ""
            # A renamed instance keeps its nickname in the online list too, so
            # it reads the same in both places.
            label = _labels.get(v["id"]) if is_installed else None
            options.append(ft.dropdown.Option(key=v["id"], text=f"{label or v['id']}{tag}"))
        all_online_options["value"] = options
        version_filter_field.value = ""
        version_filter_field.visible = True
        version_dropdown.options = options
        browse_online_row.visible = True
        offline_notice.visible = False

        # Set the dropdown value to either the previously selected, the latest release, or the first
        if state["selected_version"] and any(o.key == state["selected_version"] for o in options):
            version_dropdown.value = state["selected_version"]
        elif options:
            try:
                latest = core.get_latest_release()
                version_dropdown.value = latest if any(o.key == latest for o in options) else options[0].key
            except Exception:
                version_dropdown.value = options[0].key
        on_version_selected()
        set_status("Ready")
        page.update()

    def set_status(text, busy=False):
        """Updates the status text and dot in the sidebar's brand block.

        The dot colour is derived from the text rather than passed in, because
        every failure path already calls set_status("Crashed") / ("Error") and
        none of them knew to ask for a different colour - so a crashed launcher
        showed the word CRASHED next to the same healthy green dot as READY.
        Deriving it means the indicator can't disagree with the label.
        """
        label = text.upper()
        status_text.value = label
        if label in ("CRASHED", "ERROR"):
            status_dot.bgcolor = DANGER
        elif busy:
            status_dot.bgcolor = ACCENT_DIM
        else:
            status_dot.bgcolor = ACCENT
        page.update()

    def on_play_click():
        """
        This is called when the user clicks the main play/download button.
        It validates the username, saves config, and then starts the installation/launch process
        in a background thread so the UI stays responsive.
        """
        # Validate username
        username = username_field.value.strip()
        ok, err = core.validate_username(username)
        if not ok:
            username_field.error_text = err
            page.update()
            return
        username_field.error_text = None

        version_id = version_dropdown.value
        if not version_id:
            return

        # Save config with current username and last selected version
        cfg["username"] = username
        cfg["last_version"] = version_id
        core.save_config(cfg)

        # Update UI to "busy" state. progress_label is reset explicitly: it may
        # still be holding the previous launch's crash message, and leaving a
        # stale "Crashed: ..." line under a running progress bar reads as though
        # the new attempt failed instantly.
        set_button_mode("busy")
        progress_bar.visible = True
        # Reset the bar itself, not just its label. It carries state from the
        # previous run (the last launch ended on value=None, the indeterminate
        # "running" pulse) and `data` still holds that run's phase maximum.
        # Start indeterminate on purpose: "Preparing" may involve no measurable
        # work at all - an already-installed version reports no progress, and a
        # click during a background prefetch just blocks on the install lock. A
        # determinate bar pinned at 0% through either reads as frozen; the pulse
        # says "working", and the first real progress_cb makes it determinate.
        progress_bar.value = None
        progress_bar.data = 1
        progress_label.value = "Preparing"
        progress_label.visible = True
        progress_spinner.visible = True
        set_status("Preparing", busy=True)
        page.update()

        # Start the installation/launch in a background thread
        threading.Thread(target=lambda: do_install_and_launch(version_id, username), daemon=True).start()

    def do_install_and_launch(version_id, username):
        """
        This runs in a background thread. It handles:
          - Installing the version if not already present
          - Installing Fabric if selected and supported
          - Launching the game with the chosen version
        It uses callbacks to update the UI (progress, status).
        """
        try:
            target_version = version_id

            # Define callback functions that update UI elements from the background thread.
            # All three use throttled_update(): install progress arrives once
            # per FILE (a version is ~4000 files) and a full page.update()
            # per file saturates Flet's event loop - the window stops taking
            # input for the whole install and unfreezes when it ends.
            def status_cb(text):
                progress_label.value = text
                thread_safe_ui.throttled_update(page)

            def progress_cb(val):
                mx = progress_bar.data or 1
                # Clamped: each install phase reports its own max, and a phase
                # that emits progress before its setMax lands would otherwise
                # divide by the previous phase's (smaller) max and overshoot.
                progress_bar.value = min(1.0, max(0.0, val / mx)) if mx else 0
                thread_safe_ui.throttled_update(page)

            def max_cb(val):
                progress_bar.data = val
                thread_safe_ui.throttled_update(page)

            # If the version is not installed, install it. The per-version
            # lock also covers the background prefetch (on_version_selected),
            # so a click during a prefetch waits for it instead of racing it,
            # and an install completed by the prefetch is not repeated.
            if version_id not in state["installed"]:
                with _install_lock(version_id):
                    if version_id not in state["installed"]:
                        core.install_version(version_id, progress_cb, status_cb, max_cb)
                        state["installed"].add(version_id)

            # If a mod loader is selected, install it if supported - but only
            # if it isn't already installed for this version, otherwise every
            # single launch re-downloads/reinstalls it for no reason.
            loader_id = state["mod_loader"]
            # Loader support is a property of the *Minecraft version*, not of
            # the raw launch id. version_id can be a loader install row like
            # "fabric-loader-0.19.5-26.1.2" (or a TLauncher-style renamed id);
            # asking is_loader_supported/find_installed_loader_version with
            # that raw id would report "unsupported" and point the existing-
            # install lookup at an empty profile even though the loader is
            # right there. The numeric base is what those checks mean.
            base_version = core.extract_mc_version(version_id)
            if loader_id != "vanilla":
                loader_label = core.SUPPORTED_LOADERS.get(loader_id, loader_id)
                if core.is_loader_supported(loader_id, base_version):
                    existing_id = core.find_installed_loader_version(state["installed"], loader_id, base_version)
                    if existing_id:
                        target_version = existing_id
                    else:
                        status_cb(f"Installing {loader_label} loader")
                        target_version = core.install_mod_loader(loader_id, base_version, progress_cb, status_cb, max_cb)
                        state["installed"].add(target_version)
                else:
                    status_cb(f"{loader_label} unsupported for this version, using vanilla")

            # Now that the version (and loader, if any) is installed, the
            # loader choice is locked in - refresh the cached support map and
            # re-lock the switcher so it can't be changed after the fact.
            thread_safe_ui.final_update(page)   # paint any coalesced progress
            support = dict(loader_check_cache.get(version_id, {}))
            for lid in LOADER_IDS:
                if lid == "vanilla":
                    continue
                installed_now = bool(core.find_installed_loader_version(state["installed"], lid, base_version))
                supported_prev = support.get(lid, (True, False))[0]
                support[lid] = (supported_prev, installed_now)
            loader_check_cache[version_id] = support
            if version_dropdown.value == version_id:
                lock_loader_to_installed(version_id, support)
                style_loader_segments(support)

            # Launch the game
            progress_label.value = "Launching"
            page.update()
            set_status("Running", busy=True)

            # Has the game already exited? launch_game() is non-blocking, so a
            # process that dies immediately reaches on_exit() while this thread
            # is still mid-launch. Both writers check this under the lock so the
            # last word about the run belongs to whichever event really happened
            # last - see the guarded block after launch_game() returns.
            exited = {"done": False}
            _exit_lock = threading.Lock()

            # Define callback when game process exits - this is the only place
            # that should put the button back to "play", since launch_game()
            # itself is non-blocking (it spawns the process and returns right
            # away on a background watcher thread).
            def on_exit(code, lines=None):
                # Mark the game as finished BEFORE touching any UI, so the
                # post-launch "Minecraft is running" block below can see that
                # this launch is already over and leave the result alone.
                with _exit_lock:
                    exited["done"] = True
                # Tell friends this user stopped playing (presence -> online).
                if friends_service is not None:
                    friends_service.set_version(None)
                # Discord presence: back to just "in the launcher".
                _rpc.set_activity(details="Cubeon", state="In the launcher",
                                  large_image=_discord_img, large_text=_discord_img_text)
                state["running_version"] = None  # version is safe to delete again
                set_button_mode("play" if version_id in state["installed"] else "download")
                progress_bar.visible = False
                if code:
                    # A non-zero exit is a crash or a refused launch. Saying so
                    # matters: the old code hid this entirely, so a failed
                    # launch looked identical to a normal quit and the user was
                    # left staring at a Play button with no idea what happened.
                    reason = _explain_exit(code, lines)
                    progress_label.value = reason
                    progress_label.visible = True
                    progress_spinner.visible = False
                    set_status("Crashed")
                else:
                    progress_label.visible = False
                    progress_spinner.visible = False
                    set_status("Ready")
                page.update()

            # launch_game() returns as soon as the process has *started* - it
            # does not wait for the game to close. So the button must switch
            # to "running" right here, not after this call returns.
            # mc_version/loader are passed explicitly (not left to default)
            # so the right profile's mods actually get synced before this
            # launch - see cubeon/launch.py and cubeon/mods.py for why that
            # used to silently fail. cfg is passed so the launch also
            # installs CustomSkinLoader and re-mirrors the active skin under
            # the current username - without that mod, offline players see
            # Steve/Alex and no Cubeon cape (see cubeon/csl.py).
            # Switch to "running" BEFORE spawning, not after. on_exit fires from
            # a watcher thread, and a game that dies immediately (bad Java, mod
            # conflict) can reach it before this line would otherwise run -
            # which would overwrite the crash message with a "running" state.
            # NOTE: we do NOT set the "Minecraft is running" text here on
            # purpose - launch_game() below calls status_cb (e.g. "Installing
            # CustomSkinLoader...") while it sets up, and its status calls
            # would overwrite it. The running indicator is set only after
            # launch_game() returns, once the game process has actually
            # started (see below).
            set_button_mode("running")
            state["running_version"] = version_id  # block deleting it mid-game
            page.update()

            # If the selected version belongs to an installed modpack, launch
            # with the PACK's mc_version/loader - the pack's mods and Cubeon's
            # own injected mods (CustomSkinLoader, Friends) live in the profile
            # the pack declared. Using the Play tab's loader selector instead
            # (the old behavior) put a Forge pack's launch on the vanilla/
            # fabric profile whenever the selector wasn't switched to match:
            # pack mods never synced, skins/CSL and the Friends button landed
            # in a profile nothing read from. Syncing the selector here also
            # keeps the Mods tab and the pack badge agreeing with the launch.
            launch_mc = core.extract_mc_version(version_id)
            launch_loader = state["mod_loader"]
            try:
                for p in core.list_installed_modpacks():
                    if p.get("version_id") in (version_id, target_version):
                        if p.get("mc_version"):
                            launch_mc = p["mc_version"]
                        if p.get("loader"):
                            launch_loader = p["loader"]
                        if state.get("mod_loader") != launch_loader:
                            state["mod_loader"] = launch_loader
                        if state.get("selected_mc_version") != launch_mc:
                            state["selected_mc_version"] = launch_mc
                        break
            except Exception:
                pass  # pack lookup is an enhancement, never a launch blocker

            core.launch_game(
                target_version, username, cfg["ram_mb"], cfg["width"], cfg["height"],
                cfg.get("java_path"), on_exit=on_exit,
                # Clean numeric version, not the raw launch id - this is the
                # same profile key the Mods tab and modpack installer use.
                # Passing version_id here (as before) meant a TLauncher-style
                # id like "1.20.1-forge-47.2.0" synced from a different,
                # always-empty profile every launch, so mods never applied.
                mc_version=launch_mc, loader=launch_loader,
                cfg=cfg, status_cb=status_cb,
            )

            # Broadcast presence to friends: "playing <version>". Safe no-op if
            # the user hasn't claimed a Cubeon name / isn't connected. version_id
            # is the human MC version (not the loader-specific target id), which
            # is what a friend wants to see in their list. Guarded like the
            # on_exit path above: public builds have no Friends service.
            if friends_service is not None:
                friends_service.set_version(version_id)

            # Discord Rich Presence: show the game as being played, with an
            # elapsed timer. Best-effort - no-op if Discord isn't running.
            _rpc.set_activity(
                details="Cubeon",
                state=f"Playing Minecraft {core.extract_mc_version(version_id) or version_id}",
                start=int(time.time() * 1000),
                large_image=_discord_img,
                large_text=_discord_img_text,
            )

            # launch_game() has returned, so the game process is up and any
            # setup (incl. CustomSkinLoader install) is done. The loading bar
            # is now gone - only a quiet status line remains, until on_exit
            # clears it when the game closes.
            #
            # Guarded: if the game already exited (a crash-on-start - bad Java,
            # a mod conflict, a broken pack), on_exit has ALREADY written the
            # real reason. Overwriting it with "Minecraft is running" would
            # strand a wrong status forever and destroy the only explanation
            # the user ever gets.
            with _exit_lock:
                if not exited["done"]:
                    progress_bar.visible = False  # loading is over - no more bar
                    progress_bar.value = 0
                    progress_label.value = "Minecraft is running - this launcher stays open"
                    progress_label.visible = True
                    progress_spinner.visible = False
                    page.update()

        except Exception as ex:
            # If anything goes wrong, show error and reset button. The message
            # has to stay on screen - this is the only report the user ever
            # gets, and it used to be lost whenever the repaint didn't land.
            progress_label.value = f"Error: {type(ex).__name__}: {ex}"[:180]
            progress_label.visible = True
            progress_spinner.visible = False
            progress_bar.visible = False
            set_button_mode("play" if version_id in state["installed"] else "download")
            set_status("Error")
            page.update()
            traceback.print_exc()  # full trace to the console for bug reports

    # --- Server status panel - the right column below the grass block was
    # dead space, and "is my server running" is a genuinely useful thing to
    # surface right here: it's the same version selector Console uses
    # (state["selected_version"]), so this reads live server state without
    # needing its own separate polling loop. ---

    server_status_dot = ft.Container(width=9, height=9, border_radius=RADIUS, bgcolor=TEXT_DIM)
    server_status_text = ft.Text("No server for this version", size=13, color=TEXT_DIM,
                                 font_family=FONT_MONO, weight=ft.FontWeight.W_600)
    server_status_open_console = ft.Container(
        content=ft.Text("Open Console →", size=12, color=ACCENT, weight=ft.FontWeight.W_600),
        ink=True, visible=False,
        on_click=lambda e: switch_tab("server_console"),
    )

    def refresh_server_status_panel():
        version_id = state.get("selected_version")
        try:
            running = bool(version_id) and core.is_server_running(version_id)
        except Exception:
            running = False
        if not version_id:
            server_status_dot.bgcolor = TEXT_DIM
            server_status_text.value = "Pick a version to see server status"
            server_status_open_console.visible = False
        elif running:
            server_status_dot.bgcolor = ACCENT
            server_status_text.value = "Server running for this version"
            server_status_open_console.visible = True
        else:
            server_status_dot.bgcolor = TEXT_DIM
            server_status_text.value = "Server not running"
            server_status_open_console.visible = True
        page.update()

    server_status_panel = ft.Container(
        content=ft.Column(
            [
                section_label("Server status"),
                ft.Row([server_status_dot, server_status_text], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                server_status_open_console,
            ],
            spacing=10,
        ),
        bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS, padding=20, width=280,
    )

    # -----------------------------------------------------------------
    # MANAGE INSTANCE - rename (nickname) or delete the selected version.
    # "Instance" here == an installed Minecraft version (the dropdown above).
    # Rename stores a per-id label in config (version_labels) instead of
    # renaming the on-disk folder, so it can never break a launch or the
    # loader detection that parses the id. Delete removes only that version's
    # own folder; shared mod profiles, skins, and worlds are left alone.
    # -----------------------------------------------------------------
    def _open_dialog(dlg):
        # page.open()/close() only exist on Flet 0.28+, so fall back to the
        # older page.dialog assignment.
        if hasattr(page, "open"):
            page.open(dlg)
        else:
            dlg.open = True
            page.dialog = dlg
            if dlg not in page.overlay:
                page.overlay.append(dlg)
            page.update()

    def _close_dialog(dlg):
        if hasattr(page, "close"):
            page.close(dlg)
        else:
            dlg.open = False
            page.update()

    def _selected_installed_id():
        """The selected version id iff it's actually installed, else None -
        renaming or deleting an online-only entry that isn't downloaded yet
        is meaningless."""
        vid = version_dropdown.value
        return vid if (vid and vid in state["installed"]) else None

    def on_rename_instance(e=None):
        vid = _selected_installed_id()
        if not vid:
            set_status("Install this version before renaming it")
            return
        meta = state["installed_meta"].get(vid, {})
        default_name = meta.get("display_name", vid)
        current = (cfg.get("version_labels") or {}).get(vid) or default_name
        name_field = ft.TextField(
            value=current, label="Instance name", autofocus=True,
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI,
            border_radius=RADIUS, max_length=48,
        )

        def save(e=None):
            new_name = (name_field.value or "").strip()
            labels = dict(cfg.get("version_labels") or {})
            if new_name and new_name != default_name:
                labels[vid] = new_name
            else:
                # Blank, or the same as the default, clears any custom label.
                labels.pop(vid, None)
            cfg["version_labels"] = labels
            core.save_config(cfg)
            _close_dialog(dlg)
            refresh_version_list()
            set_status("Instance renamed")

        name_field.on_submit = save
        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Rename instance", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        name_field,
                        ft.Text(f"Launch id: {vid}", size=11, color=TEXT_DIM, font_family=FONT_MONO),
                        ft.Text("Display nickname only. Leave blank to reset to the default name.",
                                size=12, color=TEXT_DIM),
                    ],
                    spacing=8, tight=True,
                ),
                width=380,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: _close_dialog(dlg)),
                ft.TextButton("Save", on_click=save, style=ft.ButtonStyle(color=ACCENT)),
            ],
        )
        _open_dialog(dlg)

    def on_delete_instance(e=None):
        vid = _selected_installed_id()
        if not vid:
            set_status("Install this version before deleting it")
            return
        if state.get("running_version") == vid:
            set_status("Can't delete a version while it's running")
            return
        meta = state["installed_meta"].get(vid, {})
        label = (cfg.get("version_labels") or {}).get(vid) or meta.get("display_name", vid)

        def confirm(e=None):
            _close_dialog(dlg)
            try:
                core.delete_version(vid)
            except ValueError as ve:
                set_status(str(ve))
                return
            # If this version was a modpack install, stop the Modpacks tab
            # from still listing it as installed. Only removes the small
            # tracking record (_modpack.json) - the mod profile itself
            # (mod_profiles/<mc_version>-<loader>) is left alone, same as
            # delete_version() already leaves it alone, since mod profiles
            # are shared/reusable across reinstalls by design. Without
            # this, "Installed packs" kept showing packs whose version had
            # already been deleted here, with a Play button that led
            # nowhere useful.
            try:
                core.forget_modpack_for_version(vid)
                refresh_installed_packs()
            except Exception:
                pass
            # Forget any nickname and stop last_version/selection pointing at it.
            labels = dict(cfg.get("version_labels") or {})
            if labels.pop(vid, None) is not None:
                cfg["version_labels"] = labels
            if cfg.get("last_version") == vid:
                cfg["last_version"] = None
            if state.get("selected_version") == vid:
                state["selected_version"] = None
            core.save_config(cfg)
            refresh_version_list()
            set_status(f"Deleted {label}")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Delete instance?", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"This permanently deletes '{label}' and its files from "
                                "your versions folder.", size=13, color=TEXT),
                        ft.Text("Your mods, skins, and worlds are not affected.",
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

    rename_instance_btn = ft.IconButton(
        ft.Icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED, icon_color=TEXT_DIM, icon_size=20,
        tooltip="Rename instance", on_click=on_rename_instance,
    )
    delete_instance_btn = ft.IconButton(
        ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=DANGER, icon_size=20,
        tooltip="Delete instance", on_click=on_delete_instance,
    )

    # -----------------------------------------------------------------
    # PLAY TAB LAYOUT
    #
    # Structure (top to bottom):
    #   PLAY title
    #   HERO PANEL  - the launcher proper: big instance title + meta line,
    #                 account/version controls side by side, loader switcher
    #                 left and a right-aligned PLAY button (~340px) so the
    #                 primary action has weight without becoming a runway.
    #   JUMP BACK IN / INSTALLED VERSIONS - real content under the hero so
    #                 the page doesn't end a third of the way down.
    # -----------------------------------------------------------------

    # Hero panel widgets -----------------------------------------------------
    hero_title = ft.Text("Minecraft", size=26, color=TEXT, font_family=FONT_DISPLAY)
    hero_version_text = ft.Text("", size=11, color=TEXT_FAINT, font_family=FONT_MONO)
    hero_loader_chip_text = ft.Text("Vanilla", size=10.5, color=ACCENT,
                                    weight=ft.FontWeight.W_700, font_family=FONT_MONO)
    hero_loader_chip = ft.Container(
        content=hero_loader_chip_text,
        bgcolor=ACCENT_TINT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=8, vertical=3),
    )

    def update_hero():
        """Syncs the hero's big title / meta chips with the current version +
        loader selection. Called wherever those change (version pick, loader
        lock-in after install detection, manual loader switch)."""
        vid = version_dropdown.value
        meta = state["installed_meta"].get(vid) if vid else None
        custom = (cfg.get("version_labels") or {}).get(vid) if vid else None
        display = (meta or {}).get("display_name")
        # A renamed/customised instance leads with its own name; otherwise the
        # title is the game itself: "Minecraft 1.21.11".
        if custom or (display and display != vid):
            hero_title.value = custom or display
        elif vid:
            hero_title.value = f"Minecraft {core.extract_mc_version(vid) or vid}"
        else:
            hero_title.value = "Minecraft"
        hero_version_text.value = vid or "no version selected"
        hero_loader_chip_text.value = core.SUPPORTED_LOADERS.get(
            LOADER_IDS[loader_toggle.selected_index], "Vanilla")

    # Now assemble the actual Play tab UI
    play_tab = ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Play", size=28, color=TEXT, font_family=FONT_DISPLAY),
                            ft.Text("Launch offline / cracked with any installed or downloadable version.",
                                    size=13, color=TEXT_DIM),
                        ],
                        spacing=2,
                    ),
                ],
            ),
            ft.Container(height=20),  # spacer

            # --- HERO PANEL: what am I about to launch, and the controls ---
            ft.Container(
                content=ft.Column(
                    [
                        # Identity band: emblem, big title, contextual actions.
                        ft.Row(
                            [
                                # Rotating grass-block GIF (assets/grass_block.gif),
                                # generated in-house. Promoted from stray corner
                                # decoration to the hero's emblem - same world,
                                # same palette, one glanceable identity.
                                ft.Image(src="grass_block.gif", width=64, height=64, fit=ft.BoxFit.CONTAIN),
                                ft.Container(width=4),
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                hero_title,
                                                ft.Container(width=6),
                                                rename_instance_btn,
                                                delete_instance_btn,
                                            ],
                                            spacing=2,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        ft.Row(
                                            [
                                                hero_loader_chip,
                                                pack_name_badge,
                                                hero_version_text,
                                            ],
                                            spacing=10,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        version_issue_text,
                                    ],
                                    spacing=7,
                                    expand=True,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),

                        ft.Container(height=18),

                        # Configuration band: Account and Version side by side -
                        # one intentional row instead of two isolated form
                        # fields separated by dead space.
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        section_label("Account"),
                                        ft.Container(height=6),
                                        username_field,
                                    ],
                                    spacing=0,
                                    expand=True,
                                ),
                                ft.Container(width=16),
                                ft.Column(
                                    [
                                        section_label("Version"),
                                        ft.Container(height=6),
                                        version_dropdown,
                                        # Online-mode filter lives with the thing
                                        # it filters; "Browse online versions"
                                        # sits directly beneath its sibling.
                                        version_filter_field,
                                        ft.Row([browse_online_link, offline_notice], spacing=14),
                                    ],
                                    spacing=0,
                                    expand=True,
                                ),
                            ],
                        ),

                        ft.Container(height=14),

                        # Action band: loader choice left (a quiet segmented
                        # pill, not a slab), PLAY right at a fixed sane width.
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        loader_toggle,
                                        loader_status_text,
                                        browse_online_row,
                                    ],
                                    spacing=8,
                                ),
                                ft.Container(expand=True),
                                ft.Container(width=340, content=play_button),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),

                        ft.Container(height=12),
                        progress_row,
                        progress_bar,
                    ],
                    spacing=10,
                ),
                **glass_card(hero=True, padding=26),
            ),
        ],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )

    # -----------------------------------------------------------------
    # (The skin section now lives inside the Profile dialog - see the
    # "Signed in as" click target near the top of main(), which builds it
    # via build_skin_section() from skin_tab.py.)
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # MODS TAB - manage installed mods and browse/download new ones (see mods_tab.py)
    # -----------------------------------------------------------------
    mods_tab, refresh_mods_list, load_recommended_mods, refresh_browse_for_new_profile = build_mods_tab(
        page, cfg, state, version_dropdown,
        section_label=section_label,
        **THEME,
    )

    # -----------------------------------------------------------------
    # MODPACKS TAB - install a whole Modrinth .mrpack (version + loader +
    # mods + config) in one click (see modpacks_tab.py / cubeon/modpacks.py).
    # -----------------------------------------------------------------
    def go_to_pack(meta):
        """Handoff from the Modpacks tab: after a pack installs (or when the
        user taps an installed pack's Play), make it the active version on the
        Play tab and jump there.

        Once installed, a modpack is just a normal (mc_version, loader) install:
        its mods live in mod_profiles/<mc_version>-<loader> - the exact folder
        CustomSkinLoader is installed into and sync_mods_to_game copies from at
        launch. So we select the pack's NUMERIC mc_version (e.g. "1.20.1") and
        flip the loader toggle to the pack's loader, precisely as if the user
        had chosen them by hand. That makes the launch pass
        mc_version="1.20.1"/loader="fabric", so the pack's mods AND the skin/cape
        mod actually load, and the version reads as "1.20.1 (Fabric)" instead of
        a bare loader id.

        (The old code selected the launchable "fabric-loader-...-1.20.1" id, which
        launch then forwarded verbatim as the mc_version - pointing the sync and
        CSL install at an empty "fabric_loader_..." profile: no mods, no skin, and
        a "Fabric Loader" label instead of the pack's name.)"""
        refresh_version_list()
        mc = meta.get("mc_version")
        loader = meta.get("loader") or "vanilla"
        # Prime the loader BEFORE selecting the version: on_version_selected ->
        # refresh_loader_support -> lock_loader_to_installed reads
        # state["mod_loader"] and keeps it when installed, so a version carrying
        # more than one loader still locks to this pack's loader.
        if loader in LOADER_IDS:
            state["mod_loader"] = loader
            loader_toggle.selected_index = LOADER_IDS.index(loader)
        # Prefer the numeric MC version; fall back to the launchable id only if
        # the base version somehow isn't listed (e.g. user deleted it).
        target = mc if (mc and any(o.key == mc for o in (version_dropdown.options or []))) \
            else meta.get("version_id")
        if target and any(o.key == target for o in (version_dropdown.options or [])):
            version_dropdown.value = target
            state["selected_version"] = target
            on_version_selected()  # also derives/sets state["selected_mc_version"]
        switch_tab("play")
        page.update()

    modpacks_tab, refresh_installed_packs, load_popular_modpacks = build_modpacks_tab(
        page, cfg, state,
        section_label=section_label, go_to_pack=go_to_pack,
        **THEME,
    )

    # -----------------------------------------------------------------
    # SERVERS GROUP - host a local server for the selected version.
    # Two sidebar sub-items (Console, Settings) sharing one backend module.
    # -----------------------------------------------------------------
    server_console_tab, server_settings_tab, server_plugins_tab, refresh_server_tab = build_server_tab(
        page, cfg, state,
        section_label=section_label, pixel_divider=pixel_divider,
        **THEME,
    )

    # -----------------------------------------------------------------
    # FRIENDS - unique Cubeon name, presence (online + which version they're
    # playing), friend requests, and P2P worlds.
    #
    # There is no Friends *tab*: the UI is the in-game "Cubeon Friends" mod
    # (see mod/), which draws Minecraft's own widgets and talks to the launcher
    # over the localhost bridge. Friends belong in the game's pause menu, where
    # you actually are when you want to invite someone - not behind an
    # alt-tab. FriendsService owns everything the tab used to: the realtime
    # client's callbacks, the P2P state machine, and the bridge endpoints. It's
    # created here and lives for the whole process so presence keeps flowing no
    # matter which tab is showing. See cubeon/friends_service.py.
    # -----------------------------------------------------------------
    # Development builds run the Friends bridge/service. Public builds omit
    # it entirely, so they make no Friends network connection or localhost
    # bridge and remain a normal launcher while the feature is in development.
    from cubeon.features import friends_enabled
    if friends_enabled():
        friends_client = friends.FriendsClient()
        friends_service = FriendsService(cfg, state, friends_client)
        friends_service.start()
    else:
        friends_client = None
        friends_service = None

    # -----------------------------------------------------------------
    # SETTINGS TAB
    # -----------------------------------------------------------------

    # RAM slider - bounded by *this machine's* actual RAM instead of a
    # hardcoded 16384 MB ceiling. That hardcoded max was the bug: a machine
    # with only 8 GB total could still drag the slider up to 16 GB and hand
    # Java an -Xmx bigger than physically available RAM, which reliably
    # crashes Minecraft (or thrashes the whole OS) instead of failing with
    # a clear message.
    #
    # Fix:
    #   - max = detected system RAM (so you can never select more than you
    #     actually have)
    #   - default / recommended point = half of system RAM, shown as a
    #     labelled tick and used to seed new configs
    #   - going above the half point still works (some people do want to
    #     push higher) but shows an explicit warning instead of pretending
    #     it's a normal position on the slider
    system_ram_mb = core.get_system_ram_mb()
    recommended_ram_mb = core.recommended_max_ram_mb(system_ram_mb)
    # Keep a sane minimum (Minecraft won't launch well under ~1GB) and never
    # let max fall below min, e.g. a very low-RAM host.
    ram_min_mb = 1024
    ram_max_mb = max(system_ram_mb, ram_min_mb + 512)
    # If a previously-saved value is now above what this machine actually
    # has (config copied from a beefier PC, RAM physically removed, etc.)
    # clamp it down rather than silently keeping an impossible selection.
    if cfg["ram_mb"] > ram_max_mb:
        cfg["ram_mb"] = recommended_ram_mb
    if cfg["ram_mb"] < ram_min_mb:
        cfg["ram_mb"] = ram_min_mb
    _ram_divisions = max(1, min(32, (ram_max_mb - ram_min_mb) // 256 or 1))

    # The old version drew a static green-to-red gradient bar UNDER a fully
    # transparent Slider. That's what made it look broken: the gradient's red
    # end always sat at the right edge of the track regardless of the actual
    # value, so a slider sitting at its minimum still showed mostly
    # yellow/red - visually implying "almost maxed out" while the label right
    # below it said the opposite. The transparent thumb was also nearly
    # invisible against the dark track, so there was nothing to actually look
    # at to see where the slider currently was.
    #
    # Fixed by letting Slider draw its own active/inactive track (so the
    # colored portion genuinely stops at the thumb) and giving the thumb a
    # solid, visible color. The active color still shifts green -> red, but
    # now the red kicks in only once you cross the recommended half-point,
    # not just from raw slider position.
    def _ram_color(value: float) -> str:
        """Green up to the recommended half-point, then blends toward red
        as you push further above it, reaching full red at the max."""
        if value <= recommended_ram_mb:
            return ACCENT
        span = max(ram_max_mb - recommended_ram_mb, 1)
        frac = (value - recommended_ram_mb) / span
        frac = max(0.0, min(1.0, frac))
        lo = tuple(int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        hi = tuple(int(DANGER[i:i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(lo[c] + (hi[c] - lo[c]) * frac) for c in range(3))
        return "#{:02x}{:02x}{:02x}".format(*mixed)

    ram_slider = ft.Slider(
        min=ram_min_mb, max=ram_max_mb, divisions=_ram_divisions, value=cfg["ram_mb"],
        active_color=_ram_color(cfg["ram_mb"]), inactive_color=SURFACE_HI,
        thumb_color=_ram_color(cfg["ram_mb"]),
        label="{value} MB",
    )
    ram_range_row = ft.Row(
        [
            ft.Text(f"{ram_min_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"Recommended: {recommended_ram_mb} MB (half of {system_ram_mb} MB detected)",
                    size=11, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Text(f"{ram_max_mb} MB", size=11, color=TEXT_DIM, font_family=FONT_MONO),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    ram_label = ft.Text(f"{cfg['ram_mb']} MB allocated", size=13, color=TEXT_DIM, font_family=FONT_MONO)
    ram_warning = ft.Text(
        "",
        size=12, color=DANGER, font_family=FONT_MONO, visible=False,
    )

    def _update_ram_warning(value: int):
        if value > recommended_ram_mb:
            ram_warning.value = (
                f"⚠ Above the recommended half-point ({recommended_ram_mb} MB). "
                f"Allocating too much RAM to Minecraft can starve your OS and "
                f"other apps, or cause instability."
            )
            ram_warning.visible = True
        else:
            ram_warning.visible = False

    _update_ram_warning(cfg["ram_mb"])

    def on_ram_change(e):
        """Updates the RAM label, thumb/track color, warning, and saves the config."""
        value = int(ram_slider.value)
        color = _ram_color(value)
        ram_slider.active_color = color
        ram_slider.thumb_color = color
        ram_label.value = f"{value} MB allocated"
        _update_ram_warning(value)
        cfg["ram_mb"] = value
        core.save_config(cfg)
        page.update()

    ram_slider.on_change = on_ram_change

    # Width and height input fields
    width_field = ft.TextField(
        value=str(cfg["width"]), label="Width", width=140,
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    height_field = ft.TextField(
        value=str(cfg["height"]), label="Height", width=140,
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    # Java path input (optional)
    java_path_field = ft.TextField(
        value=cfg.get("java_path") or "", label="Java path",
        hint_text="Leave blank to auto-detect",
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
    )

    def save_settings(e):
        """Saves the settings from the UI fields to the config file."""
        try:
            cfg["width"] = int(width_field.value or 1280)
            cfg["height"] = int(height_field.value or 720)
        except ValueError:
            pass
        cfg["java_path"] = java_path_field.value.strip() or None
        core.save_config(cfg)
        set_status("Settings saved")

    save_settings_btn = ft.Container(
        content=ft.Text("Save settings", color=BG, weight=ft.FontWeight.W_700, size=14),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(vertical=13),
        alignment=ft.Alignment.CENTER, ink=True, on_click=save_settings,
    )

    # Opt-in crash reporting (see cubeon/crashreport.py): OFF by default and
    # inert until a report endpoint is configured server-side. The checkbox
    # is the user's explicit yes; the config key is the contract the hook
    # reads.
    crash_reports_cb = ft.Checkbox(
        label="Send crash reports (helps fix bugs; log tail only, never "
              "passwords or friends data)",
        value=bool(cfg.get("crash_reports", False)),
        active_color=ACCENT,
    )

    def on_crash_reports_change(e):
        cfg["crash_reports"] = bool(crash_reports_cb.value)
        core.save_config(cfg)

    crash_reports_cb.on_change = on_crash_reports_change

    detected_java = core.find_java()  # Try to auto-detect Java

    # -----------------------------------------------------------------
    # BACKUP SYSTEM (Settings tab)
    # -----------------------------------------------------------------
    # Backs up config, mod profiles, skins/capes, profile picture, and
    # local server configs into a single zip under CUBEON_HOME/backups.
    # World saves are excluded by default (opt-in) since they live under
    # the shared .minecraft dir and can be many GB. See cubeon/backup.py.
    backup_settings = core.backup_module.load_backup_settings()

    backup_status_text = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)

    def _refresh_backup_status():
        existing = core.backup_module.list_backups()
        if not existing:
            backup_status_text.value = "No backups yet."
            return
        newest = existing[0]
        import datetime
        when = datetime.datetime.fromtimestamp(newest.created_ts).strftime("%Y-%m-%d %H:%M")
        backup_status_text.value = (
            f"{len(existing)} backup(s) saved. Most recent: {when} "
            f"({core.backup_module.human_size(newest.size_bytes)})."
        )

    _refresh_backup_status()

    backup_enabled_switch = ft.Switch(
        value=backup_settings["enabled"], active_color=ACCENT,
    )

    frequency_dropdown = ft.Dropdown(
        value=backup_settings["frequency"],
        label="How often",
        options=[
            ft.dropdown.Option("manual", "Manual only"),
            ft.dropdown.Option("daily", "Daily"),
            ft.dropdown.Option("weekly", "Weekly"),
        ],
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        bgcolor=SURFACE_HI, border_radius=RADIUS, expand=True,
        disabled=not backup_settings["enabled"],
    )

    include_saves_switch = ft.Switch(
        value=backup_settings["include_saves"], active_color=ACCENT,
    )

    keep_last_field = ft.TextField(
        value=str(backup_settings["keep_last"]),
        label="Keep last", hint_text="0 = keep all",
        width=150, border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        keyboard_type=ft.KeyboardType.NUMBER,
        disabled=not backup_settings["enabled"],
    )

    def _persist_backup_settings():
        backup_settings["enabled"] = backup_enabled_switch.value
        backup_settings["frequency"] = frequency_dropdown.value
        backup_settings["include_saves"] = include_saves_switch.value
        try:
            backup_settings["keep_last"] = max(0, int(keep_last_field.value or 5))
        except ValueError:
            backup_settings["keep_last"] = 5
        core.backup_module.save_backup_settings(backup_settings)

    def on_backup_enabled_change(e):
        # Auto-backup off -> its knobs go grey too (frequency AND retention);
        # include-saves stays live because the manual "Back up now" reads it.
        frequency_dropdown.disabled = not backup_enabled_switch.value
        keep_last_field.disabled = not backup_enabled_switch.value
        _persist_backup_settings()
        set_status("Backup settings saved")
        page.update()

    def on_backup_setting_change(e):
        _persist_backup_settings()
        set_status("Backup settings saved")
        page.update()

    backup_enabled_switch.on_change = theme.toggle_wrap(on_backup_enabled_change, backup_enabled_switch)
    frequency_dropdown.on_change = on_backup_setting_change
    include_saves_switch.on_change = theme.toggle_wrap(on_backup_setting_change, include_saves_switch)
    keep_last_field.on_blur = on_backup_setting_change

    backup_busy = {"value": False}

    def run_backup_now(e):
        """Runs a manual backup on a background thread so a large mods
        folder or saves/ inclusion doesn't freeze the UI."""
        if backup_busy["value"]:
            return
        backup_busy["value"] = True
        backup_now_btn.content.value = "Backing up..."
        backup_now_btn.disabled = True
        page.update()

        def worker():
            result = core.backup_module.create_backup(
                include_saves=include_saves_switch.value,
            )
            backup_busy["value"] = False
            backup_now_btn.content.value = "Back up now"
            backup_now_btn.disabled = False
            _refresh_backup_status()
            set_status(result.message if result.ok else f"Backup failed: {result.message}")
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    backup_now_btn = ft.Container(
        content=ft.Text("Back up now", color=BG, weight=ft.FontWeight.W_700, size=14),
        bgcolor=ACCENT, border_radius=RADIUS, padding=ft.padding.Padding.symmetric(vertical=13),
        alignment=ft.Alignment.CENTER, ink=True, on_click=run_backup_now, expand=True,
    )

    def open_backups_folder(e):
        """Opens the backups folder in the OS file browser so the user can
        find/copy zips manually (e.g. onto external storage)."""
        import subprocess
        import sys as _sys
        folder = core.backup_module.BACKUPS_DIR
        try:
            os.makedirs(folder, exist_ok=True)
            if _sys.platform == "win32":
                os.startfile(folder)  # noqa
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as ex:
            set_status(f"Couldn't open folder: {ex}")

    open_folder_btn = ft.Container(
        content=ft.Text("Open backups folder", color=TEXT, weight=ft.FontWeight.W_600, size=14),
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=13),
        alignment=ft.Alignment.CENTER, ink=True, on_click=open_backups_folder, expand=True,
    )

    restore_file_picker = ft.FilePicker()

    def on_restore_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. See on_pfp_picked() above for why
        # this stays untyped rather than annotated as
        # ft.FilePickerResultEvent (missing on some pinned Flet builds).
        do_restore(e.files)

    restore_file_picker.on_result = on_restore_picked

    # Same version-spanning registration dance used for the pfp/skin
    # FilePickers above - newer Flet self-registers Services, older Flet
    # needs the explicit page.overlay append.
    _restore_registered = False
    _services_list = getattr(page, "_services", None)
    _already_registered = (
        _services_list is not None
        and hasattr(_services_list, "_services")
        and restore_file_picker in _services_list._services
    )
    _register_fn = getattr(page, "register_service", None)
    if _already_registered:
        _restore_registered = True
    elif callable(_register_fn):
        try:
            _register_fn(restore_file_picker)
            _restore_registered = True
        except Exception:
            _restore_registered = False
    if not _restore_registered:
        try:
            if restore_file_picker not in page.overlay:
                page.overlay.append(restore_file_picker)
        except Exception:
            pass

    def do_restore(files):
        if not files:
            return
        picked = files[0]
        path = getattr(picked, "path", None)
        if not path:
            set_status("Couldn't read the selected file's path")
            return

        def worker():
            result = core.backup_module.restore_backup(path)
            set_status(result.message if result.ok else f"Restore failed: {result.message}")
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    def pick_restore_file(e):
        run_file_picker(
            page, restore_file_picker, on_files=do_restore,
            allow_multiple=False, allowed_extensions=["zip"],
        )

    restore_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.RESTORE_ROUNDED, size=15, color=TEXT_FAINT),
                ft.Text("Restore from a backup zip...", color=TEXT_DIM,
                        weight=ft.FontWeight.W_600, size=13),
            ],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        ),
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=9),
        alignment=ft.Alignment.CENTER, ink=True, on_click=pick_restore_file,
    )

    # Small Minekube credit - a quiet icon on the Settings header row, not
    # a button demanding attention. Cubeon's entire server + sharing stack
    # (Paper hosting tunnels, public addresses) runs on Minekube Connect's
    # software and network, and that deserves a visible "this is what we
    # run on" link where server owners configure things.
    def _open_minekube(e=None):
        """Opens Minekube's site, with the same browser-open fallback as
        every other external link in the app: if no browser can be opened,
        show the URL in a snackbar instead of failing silently."""
        import webbrowser
        try:
            if webbrowser.open("https://connect.minekube.com/"):
                return
        except Exception:
            pass
        snack = ft.Snackbar(ft.Text(
            "Minekube Connect is the software and backend behind all "
            "Cubeon servers. Visit https://connect.minekube.com/"))
        # Same old/new-Flet compatibility fallback as _open_dialog above.
        if hasattr(page, "open"):
            page.open(snack)
        else:
            snack.open = True
            page.snack_bar = snack
            page.update()

    minekube_badge = ft.IconButton(
        ft.Icons.DNS_ROUNDED,
        icon_size=16, icon_color=TEXT_DIM,
        tooltip=("Powered by Minekube Connect: the software and backend "
                 "used for all Cubeon servers. Click to learn more."),
        on_click=_open_minekube,
    )

    # Build the Settings tab UI
    settings_tab = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Settings", size=28, color=TEXT, font_family=FONT_DISPLAY),
                    ft.Container(expand=True),
                    minekube_badge,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text("Memory, resolution, and Java configuration.", size=13, color=TEXT_DIM),
            ft.Container(height=20),
            ft.Container(
                content=ft.Column(
                    [
                        section_label("Memory"),
                        ram_slider,
                        ram_range_row,
                        ram_label,
                        ram_warning,
                        ft.Container(height=8),
                        pixel_divider(),
                        ft.Container(height=8),
                        section_label("Window resolution"),
                        ft.Row([width_field, height_field], spacing=12),
                        ft.Container(height=8),
                        pixel_divider(),
                        ft.Container(height=8),
                        section_label("Java runtime"),
                        java_path_field,
                        ft.Text(
                            f"Auto-detected: {detected_java or 'not found on PATH'}",
                            size=11, color=TEXT_FAINT, font_family=FONT_MONO,
                        ),
                        ft.Container(height=8),
                        section_label("Privacy"),
                        crash_reports_cb,
                        ft.Container(height=8),
                        save_settings_btn,
                    ],
                    spacing=10,
                ),
                bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
            ),
            ft.Container(height=16),
            ft.Container(
                content=ft.Column(
                    [
                        section_label("Backups"),
                        ft.Text(
                            "Zips your config, mod profiles, skins/capes, profile picture, "
                            "and local server configs so they survive a reinstall or a "
                            "wiped drive.",
                            size=12, color=TEXT_DIM,
                        ),
                        ft.Container(height=6),
                        # --- Automatic backups: one quiet grouped panel, the
                        # same surface-within-surface style as the server
                        # properties switch cards - the knobs clearly belong
                        # to the switch above them.
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Column(
                                                [
                                                    ft.Text("Automatic backups", size=13, color=TEXT,
                                                            weight=ft.FontWeight.W_600),
                                                    ft.Text("Runs on a schedule while the launcher is open",
                                                            size=11, color=TEXT_FAINT),
                                                ],
                                                spacing=2, expand=True,
                                            ),
                                            backup_enabled_switch,
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.Row([frequency_dropdown, keep_last_field], spacing=12),
                                    ft.Row(
                                        [
                                            ft.Column(
                                                [
                                                    ft.Text("Include world saves", size=13, color=TEXT,
                                                            weight=ft.FontWeight.W_600),
                                                    ft.Text("Can make backups large - also used by Back up now",
                                                            size=11, color=TEXT_FAINT),
                                                ],
                                                spacing=2, expand=True,
                                            ),
                                            include_saves_switch,
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                ],
                                spacing=12,
                            ),
                            bgcolor=SURFACE_HI, border_radius=RADIUS, padding=14,
                        ),
                        ft.Container(height=8),
                        pixel_divider(),
                        ft.Container(height=8),
                        # --- Status: one line with a clock glyph, not bare mono text.
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.HISTORY_ROUNDED, size=16, color=TEXT_FAINT),
                                backup_status_text,
                            ],
                            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Container(height=4),
                        # --- Actions: primary + secondary side by side, equal
                        # weight per role; restore is the quiet tertiary below.
                        ft.Row(
                            [backup_now_btn, open_folder_btn],
                            spacing=12,
                        ),
                        restore_btn,
                    ],
                    spacing=10,
                ),
                bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=24,
            ),
        ],
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
    )

    # -----------------------------------------------------------------
    # TAB SWITCHING LOGIC
    # -----------------------------------------------------------------

    # Map tab keys to their respective content. Each is a plain, natively
    # scrollable ft.Column (scroll=ft.ScrollMode.AUTO) - no fake-smoothing
    # or blur-on-scroll wrapper.
    tabs = {
        "play": play_tab,
        "mods": mods_tab,
        "modpacks": modpacks_tab,
        "profile": profile_tab,
        "server_console": server_console_tab,
        "server_plugins": server_plugins_tab,
        "server_settings": server_settings_tab,
        "settings": settings_tab,
    }
    SERVER_GROUP_KEYS = {"server_console", "server_plugins", "server_settings"}

    def switch_tab(key):
        """
        Switches the active tab. Updates the navigation buttons' appearance
        and replaces the content area with the chosen tab.
        Also triggers a refresh of the mods list when switching to the Mods
        tab, and of the Servers group when switching to either of its
        sub-items. Picking a Servers sub-item also auto-expands the group
        and highlights its header, so the active section stays visible.
        """
        active_tab["value"] = key
        # Update nav button styles
        for k, btn in nav_buttons.items():
            _style_nav_button(btn, k == key)
        # Servers group header highlights whenever either sub-item is active,
        # and expands so the active sub-item is never hidden behind a collapse.
        if key in SERVER_GROUP_KEYS and not server_group_expanded["value"]:
            toggle_server_group()
        server_group_header.content.controls[0].color = ACCENT if key in SERVER_GROUP_KEYS else TEXT_DIM
        server_group_header.content.controls[1].color = ACCENT if key in SERVER_GROUP_KEYS else TEXT_DIM
        # Replace content
        content_area.content = ft.Container(tabs[key], padding=ft.padding.Padding.symmetric(
            horizontal=28, vertical=24), expand=True)
        # If switching to Mods, refresh the list and load recommendations if not yet loaded
        if key == "mods":
            refresh_mods_list()
            if not state.get("mods_recommendations_loaded"):
                state["mods_recommendations_loaded"] = True
                load_recommended_mods()
        elif key == "modpacks":
            refresh_installed_packs()
            if not state.get("modpacks_loaded"):
                state["modpacks_loaded"] = True
                load_popular_modpacks()
        elif key == "profile":
            refresh_profile_tab()
        elif key in SERVER_GROUP_KEYS:
            refresh_server_tab()
        elif key == "play":
            refresh_server_status_panel()
        page.update()

    # Initialize content area with the Play tab
    content_area.content = ft.Container(play_tab, padding=ft.padding.Padding.symmetric(
        horizontal=28, vertical=24), expand=True)

    # -----------------------------------------------------------------
    # FINAL LAYOUT - assemble the whole page
    # -----------------------------------------------------------------

    # The shell: transparent sidebar on the flat canvas beside the content
    # surface - separation is tonal, no drawn borders. There is no top bar:
    # brand lives in the sidebar.
    #
    # content_area (the tab host) lives INSIDE the surface; switching tabs
    # only ever replaces its .content, so the surface persists.
    content_surface = ft.Container(
        content=content_area,
        bgcolor=CARD_FILL,
        border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS_LG,
        margin=ft.margin.Margin.only(top=12, right=12, bottom=12),
        expand=True,
    )

    page.add(ft.Container(
        content=ft.Row([sidebar, content_surface], expand=True, spacing=0),
        expand=True,
    ))

    # Finally, populate the version dropdown for the first time (offline mode)
    refresh_version_list()

    # Marks the initial synchronous mount as done. Must come after
    # refresh_version_list() (which is itself synchronous and may start
    # background threads like the loader-support check), not before -
    # otherwise a background update could still land while this very
    # function is mid-mount. See cubeon/thread_safe_ui.py for the startup
    # IndexError this fixes (a background page.update() racing Flet's diff
    # of the still-mounting control tree).
    thread_safe_ui.mark_mounted(page)

    # Bring the Friends connection up at startup, so a user who claimed a name
    # shows online to friends and can be invited to a P2P world the moment the
    # launcher opens - the in-game UI has no way to trigger a connect itself.
    # No-op if no name is claimed or the realtime lib is missing; the mod's
    # Account screen reports both states.
    if friends_client is not None and friends_client.is_available and friends.load_identity():
        friends_client.connect()

    # -----------------------------------------------------------------
    # GAMEPAD SUPPORT
    # A plugged-in controller shows a status pill in the sidebar and can
    # drive the launcher's menus. Mapping (Linux gamepad standard layout,
    # works for Xbox/PlayStation/most third-party pads):
    #   A / Start = Play (or Download & Play)   B = back to the Play tab
    #   D-pad left/right = cycle tabs           X = Mods   Y = Modpacks
    #   Select = show this mapping as a toast
    _CONTROLLER_HINT = ("Gamepad:  A/Start = Play · D-pad = switch tabs · "
                        "B = Play tab · X = Mods · Y = Modpacks · Select = help")

    def _controller_show_help():
        try:
            page.open(ft.SnackBar(ft.Text(_CONTROLLER_HINT, size=12, color=ON_ACCENT),
                                  bgcolor=SURFACE_HI, duration=6000))
        except Exception:
            pass

    def _controller_cycle_tab(direction: int):
        keys = [k for k in nav_buttons.keys() if k in tabs]
        if not keys:
            return
        try:
            i = keys.index(active_tab["value"])
        except ValueError:
            i = 0
        switch_tab(keys[(i + direction) % len(keys)])

    def _on_controller_event(button: str):
        try:
            if button in ("a", "start"):
                if active_tab["value"] != "play":
                    switch_tab("play")
                elif not play_button.disabled:
                    on_play_click()
            elif button == "b":
                switch_tab("play")
            elif button == "x":
                switch_tab("mods")
            elif button == "y":
                switch_tab("modpacks")
            elif button == "left":
                _controller_cycle_tab(-1)
            elif button == "right":
                _controller_cycle_tab(1)
            elif button == "select":
                _controller_show_help()
        except Exception:
            pass  # a stray pad press must never break the launcher

    def _on_controller_connect(name: str):
        try:
            # Silent auto-detection: no permanent UI - just a one-time toast
            # telling the player the pad was picked up and can drive menus.
            page.open(ft.SnackBar(
                ft.Text(f"🎮 {name} connected · {_CONTROLLER_HINT}",
                        size=12, color=ON_ACCENT),
                bgcolor=SURFACE_HI, duration=7000))
        except Exception:
            pass

    def _on_controller_disconnect(name: str):
        try:
            page.open(ft.SnackBar(ft.Text(f"🎮 {name} disconnected", size=12, color=ON_ACCENT),
                                  bgcolor=SURFACE_HI, duration=4000))
        except Exception:
            pass

    try:
        _controller_watcher = ControllerWatcher(
            on_event=_on_controller_event,
            on_connect=_on_controller_connect,
            on_disconnect=_on_controller_disconnect,
        )
        _controller_watcher.start()
    except Exception:
        _controller_watcher = None  # no /dev/input (or no perms) - pad stays off

    # -----------------------------------------------------------------
    # SCHEDULED BACKUPS
    # The Settings tab already persists a frequency (daily/weekly) and a
    # last-run timestamp, but nothing was actually triggering them. Check
    # once at startup and then on a slow timer, so even a session left open
    # for days still fires on schedule. is_due() returns False unless
    # backups are enabled AND the interval since the last one has elapsed,
    # so this is a cheap no-op in the common manual/disabled case. Runs on a
    # daemon thread; page.update() from here is safe via thread_safe_ui.
    # -----------------------------------------------------------------
    def _backup_scheduler():
        while True:
            try:
                if core.backup_module.is_due():
                    set_status("Running scheduled backup", busy=True)
                    result = core.backup_module.create_backup()
                    set_status(result.message if result.ok else f"Backup failed: {result.message}")
                    _refresh_backup_status()
                    page.update()
            except Exception:
                # A scheduler that dies silently is bad, but one that takes the
                # app down over a backup hiccup is worse - swallow and retry.
                pass
            time.sleep(1800)  # re-check every 30 minutes

    threading.Thread(target=_backup_scheduler, daemon=True).start()

    # -----------------------------------------------------------------
    # ORPHANED GAME WATCHDOG
    # If the previous launcher run died while Minecraft was still up, the
    # game is still running with no one watching it (holding locks on the
    # mods folder). Offer to end it - once, non-blocking, easy to dismiss.
    # -----------------------------------------------------------------
    try:
        from cubeon import watchdog as _watchdog
        _stale = _watchdog.stale_session()
        if _stale:
            def _kill_orphan(e=None):
                _watchdog.terminate(_stale["pid"])
                try:
                    page.open(ft.SnackBar(ft.Text(
                        f"Ended the leftover Minecraft session (pid {_stale['pid']})",
                        size=12, color=ON_ACCENT), bgcolor=SURFACE_HI))
                    page.update()
                except Exception:
                    pass

            page.open(ft.SnackBar(
                ft.Row([
                    ft.Text("A Minecraft session from before is still running",
                            size=13, color=ON_ACCENT, expand=True),
                    ft.TextButton("Close it", on_click=_kill_orphan,
                                  style=ft.ButtonStyle(color=ON_ACCENT)),
                ]),
                bgcolor=SURFACE_HI, duration=8000))
            page.update()
    except Exception:
        pass  # watchdog is a nicety; never block startup on it

    # -----------------------------------------------------------------
    # UPDATE CHECK
    # One quiet background GET at startup; if a newer release exists, a
    # non-blocking snackbar offers the download page. Never a modal, never
    # an error dialog - a launcher that can't reach GitHub must launch
    # normally. See cubeon/updater.py.
    # -----------------------------------------------------------------
    def _offer_update(info: dict):
        import webbrowser

        def _open_release(e=None):
            try:
                webbrowser.open(info["url"])
            except Exception:
                pass

        try:
            page.open(ft.SnackBar(
                ft.Row([
                    ft.Text(f"Cubeon {info['version']} is available",
                            size=13, color=ON_ACCENT, expand=True),
                    ft.TextButton("Get it", on_click=_open_release,
                                  style=ft.ButtonStyle(color=ON_ACCENT)),
                ]),
                bgcolor=SURFACE_HI, duration=10000))
            page.update()
        except Exception:
            pass  # a missed update hint beats a broken UI

    try:
        from cubeon import updater
        updater.check_in_background(_offer_update, token=cfg.get("update_token"))
    except Exception:
        pass

    # -----------------------------------------------------------------
    # FIRST-RUN ONBOARDING
    # A brand-new config (no "onboarded" flag) gets one lightweight dialog:
    # pick your in-game name, done. No multi-step wizard - everything else
    # (versions, mods) has sane defaults and can be discovered in the UI.
    # -----------------------------------------------------------------
    if "onboarded" not in cfg:
        onboard_name = ft.TextField(
            value=cfg.get("username") or "",
            label="Your in-game name",
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI,
            border_radius=RADIUS, height=52,
            autofocus=True,
            on_submit=lambda e: _onboard_finish(),
        )

        def _onboard_finish(e=None):
            name = onboard_name.value.strip()
            ok, err = core.validate_username(name)
            if not ok:
                onboard_name.error_text = err
                page.update()
                return
            profile_username_field.value = name
            on_profile_username_change()   # validates, saves, syncs skins/avatars
            cfg["onboarded"] = True
            core.save_config(cfg)
            try:
                page.close(onboard_dlg)
                page.update()
            except Exception:
                pass

        onboard_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Welcome to Cubeon", color=TEXT, font_family=FONT_DISPLAY),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Pick the name you'll play as. You can change it "
                            "later in your Profile.", size=13, color=TEXT_DIM),
                    onboard_name,
                ], tight=True, spacing=14),
                width=360,
            ),
            actions=[ft.TextButton("Start playing", on_click=_onboard_finish,
                                   style=ft.ButtonStyle(color=ACCENT))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        try:
            page.open(onboard_dlg)
            page.update()
        except Exception:
            pass  # a missed welcome dialog must not break startup



    # --- Clear the Discord activity when the launcher window closes ---
    # Without this, the "Playing / in the launcher" presence can linger on the
    # player's profile after they quit Cubeon. Best-effort and version-tolerant:
    # on_window_event was renamed on some Flet builds, so absent/odd behavior
    # just means the presence clears on the next launch instead.
    def _on_window_event(e):
        try:
            if getattr(e, "data", None) in ("close", "disconnect"):
                _rpc.clear()
                _rpc.close()
                try:
                    friends_service.stop()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        page.on_window_event = _on_window_event
    except Exception:
        pass

    # F12 toggles the inspector too (same CUBEON_INSPECT gate). Best-effort:
    # if the keyboard event API moved between Flet versions, the sidebar
    # button still works.
    if _inspector_enabled:
        def _on_key(e):
            try:
                if str(getattr(e, "key", "")).lower() in ("f12", "F12"):
                    _open_inspector()
            except Exception:
                pass
        try:
            page.on_keyboard_event = _on_key
        except Exception:
            pass


# This is the standard Python entry point - when the script is run directly, start the Flet app.
if __name__ == "__main__":
    # assets_dir tells Flet where "..." src paths (window icon, sidebar
    # logo) resolve to on disk. Paths in src= are relative to this folder
    # itself - e.g. src="icon.svg" resolves to assets/icon.svg on disk.
    # (Using src="assets/icon.svg" here would double the path and fail.)
    #
    # Built as an ABSOLUTE path from this script's own location rather than
    # the relative string "assets" - a relative path only resolves correctly
    # if the app happens to be launched with the project folder as the
    # current working directory. Launched any other way (a shortcut, an
    # IDE run config, `python /some/other/path/main.py`), Flet can't find
    # the assets folder, silently fails to load icon.svg, and the sidebar
    # logo falls back to a generic placeholder glyph instead of the real
    # Cubeon mark. An absolute path always resolves correctly regardless of
    # cwd at launch time.
    _assets_dir = resolve_assets_dir()
    ft.app(target=main, assets_dir=_assets_dir)

"""
Shared Modrinth project detail dialog.

The Mods tab has its own rich detail menu (version rows with per-version
install wired into the profile pipeline). The modpacks tab and the server
plugins browser had nothing: clicking a row did nothing, so users couldn't
see a pack's description before committing to a huge install. This module is
the generic version of that dialog for any Modrinth project (packs, plugins,
anything resolvable by id/slug): hero art, decision-relevant meta
(downloads/loaders/game versions), the description, recent versions, and a
footer Install CTA handed in by the caller so the install still flows through
the tab's own pipeline.

CurseForge-only hits have no Modrinth ref: `core.get_mod_details` returns
None for those, and this dialog then shows the row's own blurb with the
install CTA - never an empty pane.
"""
import threading

import flet as ft

from cubeon import dialogs
from cubeon import icons as _icons
from cubeon import mods as _mods
from cubeon import thread_safe_ui


def _human_count(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _badge(text, *, accent=False, theme=None):
    CARD_FILL = theme.get("CARD_FILL") if theme else None
    return ft.Container(
        content=ft.Text(text, size=10.5,
                        color=theme.get("ACCENT") if accent else theme.get("TEXT_DIM"),
                        weight=ft.FontWeight.W_700,
                        style=ft.TextStyle(letter_spacing=0.4),
                        font_family=theme.get("FONT_MONO")),
        bgcolor=theme.get("ACCENT_TINT") if accent else CARD_FILL,
        border_radius=theme.get("RADIUS"),
        padding=ft.padding.Padding.symmetric(horizontal=7, vertical=3),
        border=None if accent else ft.border.Border.all(1, theme.get("CARD_BORDER")),
    )


def _loading_row(theme):
    return ft.Row([ft.ProgressRing(width=18, height=18, stroke_width=2.5),
                   ft.Text("Loading details...", size=13,
                           color=theme.get("TEXT_DIM"))], spacing=10)


def _icon_ctrl(url, theme, size=64):
    _icons.prefetch(url)
    if url:
        return ft.Image(src=_icons.src(url), width=size, height=size,
                        border_radius=theme.get("RADIUS"), fit=ft.BoxFit.COVER)
    return ft.Container(width=size, height=size, bgcolor=theme.get("CARD_FILL"),
                        border_radius=theme.get("RADIUS"),
                        content=ft.Icon(ft.Icons.INVENTORY_2_ROUNDED,
                                        color=theme.get("TEXT_FAINT"), size=26),
                        alignment=ft.Alignment.CENTER)


def _versions_section(versions, theme, on_install_version=None):
    """Newest handful of releases - informational only (the footer Install
    button drives the tab's own version-picking install pipeline)."""
    rows = []
    for v in (versions or [])[:8]:
        vnum = str(v.get("version_number") or v.get("name")
                   or "version").split("+", 1)[0]
        gv = v.get("game_versions") or []
        tag = " \u00b7 ".join([str(x).title() for x in (v.get("loaders") or [])[:2]]
                              + [", ".join(gv[:3]) + ("\u2026" if len(gv) > 3 else "")])
        date = str(v.get("date_published") or "")[:10]
        v_install = None
        if on_install_version is not None and v.get("url"):
            v_install = ft.Container(
                content=ft.Text("Install", size=11.5,
                                color=theme.get("ACCENT"),
                                weight=ft.FontWeight.W_700),
                bgcolor=theme.get("ACCENT_TINT"),
                border_radius=theme.get("RADIUS"),
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=5),
                on_click=lambda e, _v=v: on_install_version(_v),
            )
        rows.append(ft.Container(
            content=ft.Row(
                [ft.Column(
                    [ft.Text(vnum, size=13, color=theme.get("TEXT"),
                             weight=ft.FontWeight.W_700),
                     ft.Text(tag, size=11, color=theme.get("TEXT_FAINT"),
                             font_family=theme.get("FONT_MONO"), max_lines=1)],
                    spacing=2, expand=True),
                 ft.Text(date, size=11, color=theme.get("TEXT_FAINT"),
                         font_family=theme.get("FONT_MONO")),
                 *((v_install,) if v_install is not None else ())],
                spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=theme.get("CARD_FILL"), border_radius=theme.get("RADIUS"),
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=7)))
    if not rows:
        return None
    controls = [ft.Text("Recent versions", size=15, color=theme.get("TEXT"),
                        weight=ft.FontWeight.W_700,
                        font_family=theme.get("FONT_DISPLAY")), *rows]
    if len(versions) > 8:
        controls.append(ft.Text(f"\u2026and {len(versions) - 8} more",
                                size=12, color=theme.get("TEXT_FAINT"),
                                font_family=theme.get("FONT_MONO")))
    return ft.Column(controls, spacing=6)


def open_project_detail(page: ft.Page, *, ref: str, theme: dict,
                        title: str = "", icon_url=None, blurb: str = "",
                        install_label: str = "Install", on_install=None,
                        install_disabled: bool = False,
                        install_hint: str = "", loader=None,
                        mc_version=None,
                        on_install_version=None) -> bool:
    """Opens the generic detail dialog for one Modrinth project.

    Returns True when a dialog was opened. `ref` is a Modrinth project id or
    slug; callers skip calling this for hits that have none (CurseForge-only
    rows). `on_install(e)` is the tab's own install flow - the footer button
    just delegates to it, so version picking stays in the pipeline that
    already knows how to do it.
    """
    ref = (ref or "").strip()
    if not ref and not blurb:
        return False

    _body_h = 560
    try:
        _wh = getattr(page, "height", None)
        if not _wh and getattr(page, "window", None) is not None:
            _wh = page.window.height
        if _wh:
            _body_h = max(360, min(640, int(_wh) - 210))
    except Exception:
        _body_h = 560

    detail_body = ft.Column(
        [_loading_row(theme)],
        spacing=14, width=680, height=_body_h,
        scroll=ft.ScrollMode.AUTO,
    )

    def _close(e=None):
        dialogs.close_dialog(page, dlg)

    install_btn = None
    if on_install is not None:
        install_btn = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.DOWNLOAD_ROUNDED,
                         color=theme.get("TEXT_FAINT") if install_disabled
                         else theme.get("ON_ACCENT") or theme.get("BG"), size=16),
                 ft.Text("Installed" if install_disabled else install_label,
                         size=13, weight=ft.FontWeight.W_700,
                         color=theme.get("TEXT_FAINT") if install_disabled
                         else theme.get("ON_ACCENT") or theme.get("BG"))],
                spacing=6, tight=True),
            bgcolor=None if install_disabled else theme.get("ACCENT"),
            border_radius=theme.get("RADIUS"),
            padding=ft.padding.Padding.symmetric(horizontal=18, vertical=9),
            on_click=None if install_disabled else
            (lambda e: (dialogs.close_dialog(page, dlg), on_install(e))[1]),
        )

    footer = ft.Row(
        [ft.Text(install_hint, size=11.5, color=theme.get("TEXT_FAINT"),
                 expand=True, max_lines=2,
                 overflow=ft.TextOverflow.ELLIPSIS) if install_hint
         else ft.Container(expand=True),
         ft.TextButton("Close", on_click=_close),
         *((install_btn,) if install_btn is not None else ())],
        alignment=ft.MainAxisAlignment.END, spacing=10)

    dlg = ft.AlertDialog(
        modal=False, bgcolor=theme.get("SURFACE"),
        content=ft.Container(
            width=720,
            content=ft.Column(
                [
                    ft.Row(
                        [_icon_ctrl(icon_url or None, theme),
                         ft.Column(
                             [ft.Text(title or "Details", size=18,
                                      color=theme.get("TEXT"),
                                      weight=ft.FontWeight.W_800,
                                      font_family=theme.get("FONT_DISPLAY"),
                                      max_lines=2,
                                      overflow=ft.TextOverflow.ELLIPSIS),
                              ft.Text(blurb or "", size=12.5,
                                      color=theme.get("TEXT_DIM"), max_lines=2)],
                             spacing=4, expand=True)],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(height=2),
                    detail_body,
                    ft.Container(height=4),
                    footer,
                ], spacing=10, tight=True)))
    dialogs.open_dialog(page, dlg)

    def worker():
        if not ref:
            detail_body.controls.clear()
            detail_body.controls.append(ft.Text(
                blurb or "", size=12.5, color=theme.get("TEXT_DIM")))
            thread_safe_ui.refresh(detail_body)
            return
        details, versions = None, []
        try:
            details = _mods.get_mod_details(ref) or {}
        except Exception:
            details = {}
        try:
            versions = _mods.get_mod_versions(ref, mc_version=mc_version,
                                              loader=loader) or []
        except Exception:
            versions = []

        controls = []
        if details:
            pills = []
            if details.get("downloads"):
                pills.append(_badge(_human_count(details["downloads"])
                                    + " downloads", theme=theme))
            loaders = details.get("loaders") or []
            if loaders:
                pills.append(_badge(" / ".join(str(x).title()
                                               for x in loaders[:3]),
                                    theme=theme))
            gvs = details.get("game_versions") or []
            if gvs:
                pills.append(_badge("Minecraft " + ", ".join(gvs[:3])
                                    + ("\u2026" if len(gvs) > 3 else ""),
                                    theme=theme))
            if pills:
                controls.append(ft.Row(pills, spacing=6, run_spacing=6,
                                       wrap=True))
            body = (details.get("body") or "").strip()
            if body:
                controls.append(ft.Container(height=2))
                controls.append(ft.Markdown(
                    body, selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                    shrink_wrap=True))
            vs = _versions_section(versions, theme,
                                   on_install_version=on_install_version)
            if vs is not None:
                controls.append(ft.Container(height=2))
                controls.append(vs)
        else:
            # Unresolvable (CurseForge-only entry, offline, deleted): show
            # what the row already knew rather than an empty dialog.
            if blurb:
                controls.append(ft.Text(blurb, size=12.5,
                                        color=theme.get("TEXT_DIM")))
            controls.append(ft.Text(
                "Full details aren't available for this project right now.",
                size=12, color=theme.get("TEXT_FAINT")))
        if not controls:
            controls.append(ft.Text(
                "Couldn't load details. Check your connection and try again.",
                size=13, color=theme.get("TEXT_DIM")))

        detail_body.controls.clear()
        detail_body.controls.extend(controls)
        thread_safe_ui.refresh(detail_body)

    threading.Thread(target=worker, daemon=True,
                     name="cubeon-detail-dialog").start()
    return True

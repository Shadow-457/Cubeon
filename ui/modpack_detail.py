"""Retained modpack detail page; installation stays with the catalogue's callbacks."""
import logging
import threading
from urllib.parse import quote, urlsplit

import flet as ft
import launcher_core as core
from cubeon import i18n, icons, thread_safe_ui
from ui.image_memory import preview_image
from ui.install_feedback import compact_status
from ui.project_readme import readme_markdown


def _http_url(value):
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in ("https", "http") and parsed.netloc else None
    except ValueError:
        return None


class ModpackDetailPage:
    def __init__(self, page, theme, artwork):
        self.page = page
        self.theme = theme
        self.artwork = artwork
        self.control = ft.Column(visible=False, expand=True, spacing=16,
                                 data="modpack-detail-page")
        self.on_visibility_change = None
        self.generation = 0

    def close(self, event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if not self.control.visible:
                return False
            self.generation += 1
            self.control.visible = False
            self.control.controls.clear()
            if self.on_visibility_change:
                self.on_visibility_change(False)
            thread_safe_ui.refresh(self.control)
        return True

    def _image(self, url, size, current):
        source = icons.peek_src(url)
        image = preview_image(
            src=source if icons.valid_source(source) else "icon_64.png",
            width=size, height=size, data=url, fit=ft.BoxFit.COVER,
            border_radius=self.theme["RADIUS"], gapless_playback=True,
            error_content=preview_image(src="icon_64.png", width=size, height=size))
        self._load_image(image, url, current)
        return image

    def _load_image(self, image, url, current):
        image.data = url
        source = icons.peek_src(url)
        if icons.valid_source(source):
            image.src = source
        elif url:
            def ready(source):
                with thread_safe_ui.TREE_LOCK:
                    if current() and image.data == url and icons.valid_source(source):
                        image.src = source
                        thread_safe_ui.refresh(image)
            self.artwork.request(url, ready)

    def _install_button(self, action, feedback, installed, current, *, data):
        theme = self.theme
        label = ft.Text(i18n.t("Installed" if installed else "Install"), size=12.5,
                        weight=ft.FontWeight.W_700)
        icon = ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=16)
        button = ft.Container(
            ft.Row([icon, label], spacing=8, tight=True), width=136, height=36,
            alignment=ft.Alignment.CENTER, border_radius=theme["RADIUS"],
            disabled=installed or action is None, data=data)

        def click(event):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if current() and not button.disabled and action:
                    action(event)
        button.on_click = click
        done = {"installed": installed, "result": feedback.result_id}

        def paint(job):
            if done["result"] != job.result_id:
                done["result"] = job.result_id
                done["installed"] = job.result == "success"
            installed_now = done["installed"]
            button.disabled = job.busy or installed_now or action is None
            label.value = compact_status(job.text) if job.busy else i18n.t(
                "Installed" if installed_now else "Try again" if job.result == "error" else "Install")
            label.color = icon.color = theme["TEXT_DIM"] if button.disabled else theme["ON_ACCENT"]
            icon.icon = ft.Icons.CHECK_ROUNDED if installed_now else ft.Icons.DOWNLOAD_ROUNDED
            button.bgcolor = theme["SURFACE_HI"] if button.disabled else theme["ACCENT"]
            button.tooltip = job.text if job.busy or job.result == "error" else None
        feedback.watch(button, paint)
        return button

    def open(self, pack, *, on_install, on_install_version, feedback, installed=False):
        ft.context.disable_auto_update()
        theme = self.theme
        pack = dict(pack)
        source = pack.get("source") or pack.get("provider") or "modrinth"
        ref = str(pack.get("project_id") or pack.get("slug") or "").strip()
        with thread_safe_ui.TREE_LOCK:
            self.generation += 1
            generation = self.generation

            def current():
                return self.control.visible and self.generation == generation

            title = ft.Text(pack.get("title") or "Modpack", size=22, color=theme["ACCENT"],
                            font_family=theme["FONT_DISPLAY"], weight=ft.FontWeight.W_700,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            description = ft.Text(pack.get("description") or "", size=12.5,
                                  color=theme["TEXT_DIM"], max_lines=2,
                                  overflow=ft.TextOverflow.ELLIPSIS)
            author = pack.get("author") or pack.get("author_name")
            subtitle = ft.Text(" · ".join(filter(None, [f"by {author}" if author else "",
                                                        source.title()])),
                               size=11.5, color=theme["TEXT_DIM"])
            image = self._image(pack.get("icon_url"), 58, current)
            install = self._install_button(on_install, feedback, installed, current,
                                           data="modpack-detail-install")
            hero = ft.Container(ft.Row([
                image, ft.Column([title, subtitle, description], spacing=5, expand=True), install],
                spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=16, height=120, bgcolor=theme["SURFACE_HI"],
                border_radius=theme["RADIUS"])
            tabs = ft.Row(spacing=8, data="modpack-detail-tabs")
            body = ft.Column([
                ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme["ACCENT"]),
                        ft.Text("Loading details...", size=13, color=theme["TEXT_DIM"])], spacing=12)],
                spacing=16, expand=True, scroll=ft.ScrollMode.AUTO, data="modpack-detail-body")
            self.control.controls = [ft.Row([
                ft.TextButton(content=i18n.t("Back"), icon=ft.Icons.ARROW_BACK_ROUNDED,
                              on_click=self.close, data="modpack-detail-back",
                              style=ft.ButtonStyle(color=theme["ACCENT"])),
                ft.Container(expand=True),
                ft.Text("Modpack", size=11, color=theme["TEXT_DIM"])],
                vertical_alignment=ft.CrossAxisAlignment.CENTER), hero, tabs, body]
            self.control.visible = True
            if self.on_visibility_change:
                self.on_visibility_change(True)
            thread_safe_ui.refresh(self.control)

        def retry(event):
            with thread_safe_ui.TREE_LOCK:
                if current():
                    self.open(pack, on_install=on_install, on_install_version=on_install_version,
                              feedback=feedback, installed=installed)

        def render(details, versions, errors):
            if not current():
                return
            details = {**pack, "game_versions": pack.get("versions") or [], **details}
            title.value = details.get("title") or title.value
            title.tooltip = title.value
            description.value = details.get("description") or description.value
            author = details.get("author") or details.get("author_name")
            subtitle.value = " · ".join(filter(None, [f"by {author}" if author else "", source.title()]))
            if details.get("icon_url") != image.data:
                self._load_image(image, details.get("icon_url"), current)
            thread_safe_ui.refresh(hero)

            def open_link(event):
                url = _http_url(event.data)
                if url:
                    self.page.run_task(ft.UrlLauncher().launch_url, url)

            def overview():
                readme = ft.Markdown(
                    readme_markdown(details.get("body") or details.get("description") or "")
                    or "No description available.", selectable=True, shrink_wrap=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                    image_error_content=ft.Text("Image unavailable", color=theme["TEXT_DIM"], size=11),
                    on_tap_link=open_link, data="modpack-detail-readme",
                    md_style_sheet=ft.MarkdownStyleSheet(
                        p_text_style=ft.TextStyle(color=theme["TEXT"], size=13, height=1.6),
                        a_text_style=ft.TextStyle(color=theme["ACCENT"]),
                        h1_text_style=ft.TextStyle(color=theme["TEXT"], size=22, weight=ft.FontWeight.W_700),
                        h2_text_style=ft.TextStyle(color=theme["TEXT"], size=18, weight=ft.FontWeight.W_700),
                        h3_text_style=ft.TextStyle(color=theme["TEXT"], size=15, weight=ft.FontWeight.W_600),
                        list_bullet_text_style=ft.TextStyle(color=theme["TEXT_DIM"], size=13),
                        code_text_style=ft.TextStyle(color=theme["ACCENT"], font_family=theme["FONT_MONO"], size=12),
                        block_spacing=14))
                content = [readme]
                if errors.get("details"):
                    content.extend([ft.Text("Full details aren't available right now.",
                                            color=theme["TEXT_DIM"], size=12),
                                    ft.TextButton(content="Retry", on_click=retry)])
                sidebar = ft.Column([
                    ft.Text(i18n.t("About this modpack"), color=theme["ACCENT"], size=13,
                            font_family=theme["FONT_DISPLAY"])], spacing=10)
                values = [("Provider", source.title()),
                          ("Downloads", f"{details.get('downloads') or 0:,}"),
                          ("Minecraft", ", ".join(details.get("game_versions") or []) or "Declared by the pack"),
                          ("Loaders", ", ".join(str(x).title() for x in details.get("loaders") or [])
                           or "Declared by the pack"),
                          ("License", details.get("license") or "Not specified")]
                for label, value in values:
                    sidebar.controls.append(ft.Column([
                        ft.Text(i18n.t(label), color=theme["TEXT_DIM"], size=10.5),
                        ft.Text(value, color=theme["TEXT"], size=11.5, selectable=True)], spacing=4))
                slug = quote(str(details.get("slug") or ref), safe="")
                project_url = (f"https://www.curseforge.com/minecraft/modpacks/{slug}" if source == "curseforge"
                               else f"https://modrinth.com/modpack/{slug}")
                for label, url in [(f"Project on {source.title()}", project_url),
                                   ("Source code", details.get("source_url")),
                                   ("Report an issue", details.get("issues_url")),
                                   ("Wiki", details.get("wiki_url")), ("Discord", details.get("discord_url"))]:
                    url = _http_url(url)
                    if url:
                        sidebar.controls.append(ft.TextButton(content=i18n.t(label), url=url,
                            icon=ft.Icons.OPEN_IN_NEW_ROUNDED, style=ft.ButtonStyle(color=theme["ACCENT"])))
                content.append(ft.Text("Installs its own Minecraft version and loader.",
                                       color=theme["TEXT_DIM"], size=12))
                return ft.ResponsiveRow([
                    ft.Container(ft.Column(content, spacing=16), col={"xs": 12, "md": 9}),
                    ft.Container(sidebar, padding=16, bgcolor=theme["SURFACE_HI"],
                                 border_radius=theme["RADIUS"], col={"xs": 12, "md": 3},
                                 data="modpack-detail-metadata")],
                    spacing=24, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)

            def version_pane():
                if not versions:
                    message = ("Couldn't load published versions." if errors.get("versions") else
                               "Version selection is handled during installation." if source == "curseforge" else
                               "No published versions available.")
                    controls = [ft.Text(message, color=theme["TEXT_DIM"], size=13)]
                    if errors.get("versions"):
                        controls.append(ft.TextButton(content="Retry", on_click=retry))
                    return ft.Column(controls, spacing=12)
                rows = ft.Column(spacing=8)
                limit = {"value": 25}

                def populate(event=None):
                    ft.context.disable_auto_update()
                    with thread_safe_ui.TREE_LOCK:
                        if not current():
                            return
                        rows.controls.clear()
                        for version in versions[:limit["value"]]:
                            labels = [ft.Text(str(version.get("version_number") or version.get("name") or "Version"),
                                              size=13, color=theme["TEXT"], weight=ft.FontWeight.W_700),
                                      ft.Text(" · ".join([
                                          ", ".join(version.get("game_versions") or []),
                                          ", ".join(str(x).title() for x in version.get("loaders") or [])]),
                                          size=11, color=theme["TEXT_DIM"], max_lines=2)]
                            controls = [ft.Column(labels, spacing=4, expand=True),
                                        ft.Text(str(version.get("date_published") or "")[:10],
                                                size=11, color=theme["TEXT_DIM"])]
                            if on_install_version and version.get("url"):
                                controls.append(self._install_button(
                                    lambda e, v=version: on_install_version(v), feedback, installed, current,
                                    data="modpack-detail-version-install"))
                            rows.controls.append(ft.Container(ft.Row(controls, spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=12, bgcolor=theme["CARD_FILL"], border_radius=theme["RADIUS"]))
                        if len(versions) > limit["value"]:
                            def more(event):
                                limit["value"] += 25
                                populate(event)
                            rows.controls.append(ft.TextButton(content="Show more versions", on_click=more))
                        thread_safe_ui.refresh(rows)
                populate()
                return rows

            def gallery():
                images = [item for item in details.get("gallery") or [] if _http_url(item.get("url"))]
                if not images:
                    return ft.Text("No gallery images available.", color=theme["TEXT_DIM"], size=13)
                return ft.ResponsiveRow([ft.Container(ft.Column([
                    preview_image(src=item["url"], width=320, height=180, fit=ft.BoxFit.CONTAIN,
                                  error_content=ft.Text("Image unavailable", color=theme["TEXT_DIM"])),
                    ft.Text(item.get("title") or "", color=theme["TEXT_DIM"], size=12)], spacing=8),
                    col={"xs": 12, "md": 6, "lg": 4}) for item in images], spacing=16, run_spacing=16)

            builders = {"Overview": overview, "Versions": version_pane, "Gallery": gallery}
            panes = {}

            def select(name):
                ft.context.disable_auto_update()
                with thread_safe_ui.TREE_LOCK:
                    if not current():
                        return
                    if name not in panes:
                        panes[name] = builders[name]()
                    for button in tabs.controls:
                        selected = button.data == "modpack-detail-tab-" + name.lower()
                        button.style = ft.ButtonStyle(color=theme["ACCENT"] if selected else theme["TEXT_DIM"],
                            bgcolor=theme["SURFACE_HI"] if selected else None,
                            shape=ft.RoundedRectangleBorder(radius=theme["RADIUS"]))
                    body.controls = [panes[name]]
                    thread_safe_ui.refresh(tabs)
                    thread_safe_ui.refresh(body)
            tabs.controls = [ft.TextButton(content=i18n.t(name),
                on_click=lambda event, name=name: select(name), data="modpack-detail-tab-" + name.lower())
                for name in builders]
            select("Overview")

        def worker():
            details, versions, errors = {}, [], {}
            if source == "modrinth" and ref:
                try:
                    details = core.get_mod_details(ref) or {}
                except Exception as error:
                    errors["details"] = str(error)
                try:
                    versions = core.get_mod_versions(ref) or []
                except Exception as error:
                    errors["versions"] = str(error)
            with thread_safe_ui.TREE_LOCK:
                render(details, versions, errors)

        try:
            threading.Thread(target=worker, daemon=True, name="cubeon-modpack-detail").start()
        except Exception as error:
            logging.getLogger(__name__).warning("Couldn't start modpack detail lookup", exc_info=True)
            with thread_safe_ui.TREE_LOCK:
                render({}, [], {"details": str(error), "versions": str(error)})

"""Offline Linux setup, run by the installer AppImage before launcher startup."""
import asyncio
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import flet as ft

from . import theme, thread_safe_ui
from .updater import APP_VERSION


def bundle_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def install(source, destination, *, root=None, progress=lambda text: None):
    """Use the same offline, per-user installer as the command-line package."""
    root = Path(root or bundle_root())
    source = Path(source).resolve()
    destination = Path(destination).expanduser()
    if not destination.is_absolute() or any(c in str(destination) for c in '\r\n\x00'):
        raise ValueError('Choose a full folder path for Cubeon.')
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('The installer file is missing. Download the complete setup again.')
    script = root / 'setup' / 'install_linux.sh'
    if not script.is_file():
        script = root / 'packaging' / 'install_linux.sh'
    icon = root / 'assets' / 'icon_256.png'
    if not script.is_file() or not icon.is_file():
        raise ValueError('This setup is incomplete. Download the installer again.')
    parent = destination
    while not parent.exists():
        parent = parent.parent
    previous = destination / 'Cubeon.AppImage'
    needed = source.stat().st_size + (previous.stat().st_size if previous.is_file() else 0) + 1024**2
    if shutil.disk_usage(parent).free < needed:
        raise ValueError(f'Free at least {needed / 1024**2:.0f} MB in the installation drive, then try again.')
    progress('Installing Cubeon and adding it to your application menu…')
    env = dict(os.environ, CUBEON_INSTALL_DIR=str(destination), CUBEON_ICON=str(icon))
    result = subprocess.run(['bash', str(script), str(source)], env=env,
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise ValueError(detail[-1] if detail else 'Setup could not finish. Check the folder permissions and try again.')
    return destination / 'cubeon'


def open_launcher(path):
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    for key in ('APPIMAGE', 'APPDIR', 'CUBEON_APPIMAGE_PATH'):
        env.pop(key, None)
    subprocess.Popen([str(path)], env=env, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LinuxSetup:
    def __init__(self, page, source):
        self.page, self.source = page, source
        self.busy = False
        self.closing = False
        self.launcher = None
        self.location = ft.TextField(label='Installation folder', value=str(Path.home() / '.local/opt/Cubeon'),
                                     color=theme.TEXT, label_style=ft.TextStyle(color=theme.TEXT_DIM),
                                     border_color=theme.BORDER, focused_border_color=theme.ACCENT,
                                     border_radius=theme.RADIUS, text_size=13)
        self.status = ft.Text('Ready to install. No downloads or administrator password needed.',
                              color=theme.TEXT_DIM, size=13)
        self.progress = ft.ProgressBar(visible=False, color=theme.ACCENT, bgcolor=theme.SURFACE_HI)
        self.open_after = theme.animated_switch(label='Open Cubeon when setup finishes', value=True)
        self.title = ft.Text('Install Cubeon', size=27, weight=ft.FontWeight.W_700, color=theme.TEXT)
        self.subtitle = ft.Text(f'Version {APP_VERSION} · Linux', size=13, color=theme.TEXT_DIM)
        self.primary = ft.FilledButton('Install Cubeon', on_click=self.start, height=48,
                                      style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.ON_ACCENT,
                                                           shape=ft.RoundedRectangleBorder(radius=theme.RADIUS)))
        self.close = ft.TextButton('Cancel', on_click=self.finish)
        self.browse = ft.IconButton(ft.Icons.FOLDER_OPEN_ROUNDED, tooltip='Choose installation folder',
                                   icon_color=theme.TEXT_DIM, on_click=self.pick_folder)
        self.control = ft.Container(
            padding=32, expand=True, bgcolor=theme.BG,
            content=ft.Column([
                ft.Row([ft.Image(src='icon_256.png', width=56, height=56),
                        ft.Column([self.title, self.subtitle], spacing=8)], spacing=16),
                ft.Container(height=16),
                ft.Text('Everything you need to start playing.', size=17, color=theme.TEXT),
                ft.Text('Set up Cubeon once. Open it from your application menu and keep it up to date inside the launcher.',
                        color=theme.TEXT_DIM, size=13),
                ft.Container(height=8),
                ft.Container(content=ft.Row([ft.Container(self.location, expand=True), self.browse]),
                             padding=16, bgcolor=theme.SURFACE, border_radius=theme.RADIUS_LG,
                             border=ft.Border.all(1, theme.BORDER)),
                self.open_after, ft.Container(expand=True), self.progress, self.status,
                ft.Row([self.close, self.primary], alignment=ft.MainAxisAlignment.END, spacing=12),
            ], spacing=12, expand=True),
        )

    async def pick_folder(self, _e):
        if self.busy:
            return
        chosen = await ft.FilePicker().get_directory_path(initial_directory=self.location.value,
                                                          dialog_title='Choose a folder for Cubeon')
        if chosen and not self.busy:
            self.location.value = chosen
            thread_safe_ui.refresh(self.location)

    def paint(self):
        thread_safe_ui.refresh(self.control)

    def start(self, _e=None):
        with thread_safe_ui.TREE_LOCK:
            if self.busy:
                return
            if self.launcher:
                try:
                    open_launcher(self.launcher)
                    self.page.run_task(self._close)
                except OSError:
                    self.status.value = 'Cubeon is installed. Open it from your application menu.'
                    self.paint()
                return
            destination = self.location.value
            self.busy = True
            self.primary.disabled = self.close.disabled = self.location.disabled = self.browse.disabled = True
            self.open_after.disabled = True
            self.progress.visible = True
            self.status.value = 'Preparing your installation…'
            self.paint()
        try:
            threading.Thread(target=self._install, args=(destination,), daemon=True, name='linux-setup').start()
        except Exception:
            self._failed('Could not start setup. Try again.')

    def _install(self, destination):
        try:
            def progress(text):
                with thread_safe_ui.TREE_LOCK:
                    self.status.value = text
                    self.paint()
            launcher = install(self.source, destination, progress=progress)
            with thread_safe_ui.TREE_LOCK:
                self.launcher = launcher
                self.busy = False
                self.title.value = 'Cubeon is ready'
                self.subtitle.value = 'Find Cubeon in your application menu.'
                self.status.value = 'Installation complete. Your games and settings stay in your user folders.'
                self.progress.visible = False
                self.primary.content = 'Open Cubeon'
                self.primary.disabled = self.close.disabled = False
                self.close.content = 'Done'
                self.paint()
                open_after = self.open_after.value
            if open_after:
                self.start()
        except Exception as error:
            self._failed(str(error) if isinstance(error, ValueError) else 'Setup could not finish. Try again.')

    def _failed(self, message):
        with thread_safe_ui.TREE_LOCK:
            self.busy = False
            self.primary.disabled = self.close.disabled = self.location.disabled = self.browse.disabled = False
            self.open_after.disabled = False
            self.progress.visible = False
            self.status.value = message
            self.paint()

    async def _close(self):
        if self.busy or self.closing:
            return
        self.closing = True
        try:
            # This is the confirmed close path after the install gate. A
            # graceful close can be intercepted by the native close handler.
            await self.page.window.destroy()
        except RuntimeError as error:
            if str(error) == 'Session closed':
                return
            self._close_failed()
        except Exception:
            self._close_failed()

    def _close_failed(self):
        logging.getLogger(__name__).exception('Could not close Cubeon Setup')
        self.closing = False
        with thread_safe_ui.TREE_LOCK:
            self.page.window.prevent_close = True
            self.status.value = 'Could not close setup. Try again.'
            self.paint()

    def finish(self, _e=None):
        if not self.busy:
            self.page.run_task(self._close)


def run_installer():
    from .color_templates import apply_template
    apply_template('green')
    source = os.environ.get('APPIMAGE') or os.environ.get('CUBEON_APPIMAGE_PATH')
    async def main(page):
        page.title = 'Cubeon Setup'
        page.window.width, page.window.height = 720, 540
        page.window.min_width, page.window.min_height = 680, 520
        page.window.bgcolor = page.bgcolor = theme.BG
        page.padding = 0
        page.fonts = dict(theme.FONT_URLS)
        theme.apply_page_theme(page)
        thread_safe_ui.install(page)
        setup = LinuxSetup(page, source or '')
        page.window.prevent_close = True
        page.window.on_event = lambda e: setup.finish() if e.type == ft.WindowEventType.CLOSE else None
        page.add(setup.control)
        # Hidden desktop starts need a real property change, followed by the
        # native show method; Flet can suppress writes of the True default.
        page.window.visible = False
        page.window.visible = True
        page.update()
        try:
            await asyncio.wait_for(page.window.to_front(), timeout=5)
        except Exception:
            pass
    ft.run(main, assets_dir=str(bundle_root() / 'assets'), view=ft.AppView.FLET_APP_HIDDEN)

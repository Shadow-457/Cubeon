"""Render real loading/ready Cosmetics, Chat and Stats in an isolated native window."""
import asyncio
import inspect
import os
from pathlib import Path
import sys
import threading
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
os.environ.setdefault('GALLIUM_DRIVER', 'llvmpipe')
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from PIL import ImageGrab
from cubeon import cosmetics, milestones, thread_safe_ui
from cubeon.theme import THEME, FONT_URLS, apply_page_theme, section_label
from ui import appearance_preview, chat_tab, stats_tab
from test_skin_loading import build as build_skin, tab
from test_chat_optimistic import FakeService, texts
from test_loading_skeletons import friend_click
from _fuzz_common import walk, install_safe_stubs

OUT = ROOT / 'archive/ui-captures/loading-skeletons'
completed = []


def find(root, data):
    return next(control for control in walk(root) if control.data == data)


async def main(page):
    install_safe_stubs()
    page.title = 'Cubeon Loading States Check'
    apply_page_theme(page)
    page.fonts = FONT_URLS
    page.bgcolor = THEME['BG']
    page.padding = 20
    page.window.width, page.window.height = 1200, 760
    page.window.left, page.window.top = 0, 0
    thread_safe_ui.install(page)
    host = ft.Container(expand=True)
    page.add(host)
    thread_safe_ui.mark_mounted(page)
    OUT.mkdir(parents=True, exist_ok=True)

    async def capture(name):
        await asyncio.sleep(.65)
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(OUT / f'{name}.png')
        print('CAPTURE', name, flush=True)

    async def until(predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(.05)
        raise AssertionError('Loading fixture did not finish')

    preview_gate, thumb_gate = threading.Event(), threading.Event()
    original_model = appearance_preview.CharacterModel.from_config
    original_thumb = cosmetics.render_thumbnail
    def model(*args, **kwargs):
        assert preview_gate.wait(20)
        return original_model(*args, **kwargs)
    def thumbnail(*args, **kwargs):
        assert thumb_gate.wait(20)
        return original_thumb(*args, **kwargs)
    with patch.object(appearance_preview.CharacterModel, 'from_config', side_effect=model), \
         patch.object(cosmetics, 'render_thumbnail', side_effect=thumbnail):
        skin = build_skin(page)
        host.content = skin
        thread_safe_ui.refresh(host)
        loading = find(skin, 'appearance-loading')
        assert loading.visible
        await asyncio.sleep(3)
        await capture('cosmetics-preview-loading')
        preview_gate.set()
        await until(lambda: not loading.visible)
        tab(skin, 'Back').on_click(None)
        placeholders = [c for c in walk(skin) if c.data == 'content-skeleton' and c.width == 76]
        assert placeholders and all(c.visible for c in placeholders)
        await capture('cosmetics-library-loading')
        thumb_gate.set()
        await until(lambda: all(not c.visible for c in placeholders))
        await capture('cosmetics-library-ready')

    class Service(FakeService):
        def __init__(self):
            super().__init__()
            self.roster_gate, self.history_gate = threading.Event(), threading.Event()
        def roster_payload(self):
            assert self.roster_gate.wait(20)
            return super().roster_payload()
        def chat_payload(self, *args, **kwargs):
            assert self.history_gate.wait(20)
            return super().chat_payload(*args, **kwargs)
    service = Service()
    with patch.object(chat_tab._faces, 'get_face_b64', return_value=None):
        chat, refresh = chat_tab.build_chat_tab(page, {}, {'active_tab': 'chat'}, service,
                                               section_label=section_label, **THEME)
        host.content = chat
        thread_safe_ui.refresh(host)
        await capture('chat-roster-loading')
        service.roster_gate.set()
        await until(lambda: not find(chat, 'chat-roster-loading').visible)
        friend_click(chat, 'alice')
        assert find(chat, 'chat-history-loading').visible
        await capture('chat-history-loading')
        service.echo('The conversation is ready.')
        service.history_gate.set()
        await until(lambda: not find(chat, 'chat-history-loading').visible)
        assert texts(chat, 'The conversation is ready.') == ['The conversation is ready.']
        await capture('chat-history-ready')
        poller = inspect.getclosurevars(refresh).nonlocals['poll_thread']
        poll_vars = inspect.getclosurevars(poller._target).nonlocals
        poll_vars['stop'].set()
        poll_vars['_wake'].set()

    stats_gate = threading.Event()
    def snapshot():
        assert stats_gate.wait(20)
        return {'seconds_played': 10800, 'session_history': [], 'activity': {}}
    with patch.object(milestones, 'snapshot', side_effect=snapshot):
        stats, refresh = stats_tab.build_stats_tab(page, {}, {}, section_label=section_label,
                                                 go_to_tab=lambda *_: None, **THEME)
        host.content = stats
        thread_safe_ui.refresh(host)
        assert find(stats, 'stats-chart-loading').visible
        await asyncio.sleep(1.5)
        await capture('stats-loading-wide')
        page.window.width = 480
        page.update()
        await capture('stats-loading-compact')
        stats_gate.set()
        await until(lambda: not find(stats, 'stats-chart-loading').visible)
        assert find(stats, 'stats-metric:0').value == '3h'
        await capture('stats-ready-compact')
    print('NATIVE_SKELETON_PASS: Cosmetics preview/thumbnails, Chat roster/history, Stats wide/compact loading and real content.', flush=True)
    completed.append(True)


if __name__ == '__main__':
    async def checked(page):
        try:
            await main(page)
        except Exception:
            traceback.print_exc()
        finally:
            await page.window.close()
    ft.run(checked, assets_dir=str(ROOT / 'assets'))
    sys.exit(not completed)

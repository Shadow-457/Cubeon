"""Window-close race tests. --native also probes both installed Flet clients.

Native probes open a small window, close it automatically, capture diagnostics
under /tmp, and terminate only their own process group if a client lingers.
"""
import asyncio
import importlib.metadata
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon.window_close import WindowCloser


class Page:
    def __init__(self, error=None, gate=None):
        self.window = self
        self.error = error
        self.gate = gate
        self.calls = 0
        self.tasks = []

    async def close(self):
        self.calls += 1
        if self.gate:
            await self.gate.wait()
        if self.error:
            raise self.error

    def run_task(self, handler):
        task = asyncio.create_task(handler())
        self.tasks.append(task)
        return task


class WindowCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_disappears_before_close_reply(self):
        page = Page(RuntimeError('Session closed'))
        closer = WindowCloser(page)
        closer.request()
        self.assertEqual(await asyncio.gather(*page.tasks), [True])
        self.assertTrue(await closer.close())
        self.assertEqual(page.calls, 1)

    async def test_double_click_and_inflight_restart_send_one_request(self):
        page = Page(gate=asyncio.Event())
        closer = WindowCloser(page)
        closer.request()
        closer.request()
        await asyncio.sleep(0)
        self.assertTrue(await closer.close())
        page.gate.set()
        self.assertEqual(await asyncio.gather(*page.tasks), [True])
        self.assertEqual(page.calls, 1)

    async def test_close_event_before_queued_task(self):
        page = Page()
        closer = WindowCloser(page)
        closer.request()
        closer.mark_closed()
        self.assertEqual(await asyncio.gather(*page.tasks), [True])
        self.assertEqual(page.calls, 0)

    async def test_unexpected_error_is_logged_and_can_retry(self):
        page = Page(RuntimeError('Native close rejected'))
        states = []
        closer = WindowCloser(page, states.append)
        with self.assertLogs('cubeon.window_close', level='ERROR') as logged:
            self.assertFalse(await closer.close())
        self.assertIn('Native close rejected', '\n'.join(logged.output))
        self.assertFalse(states[-1])
        page.error = None
        self.assertTrue(await closer.close())
        self.assertEqual(page.calls, 2)

    async def test_page_already_gone_at_scheduling_time(self):
        page = Page()
        def gone(handler):
            raise RuntimeError('Session closed')
        page.run_task = gone
        closer = WindowCloser(page)
        self.assertTrue(closer.request())
        self.assertTrue(await closer.close())
        self.assertEqual(page.calls, 0)


def native_child():
    import flet as ft
    async def main(page):
        page.title = 'Cubeon close verification'
        page.window.width = 240
        page.window.height = 160
        page.add(ft.Text('Testing window close'), ft.ProgressRing())
        closer = WindowCloser(page)
        async def finish():
            await asyncio.sleep(1.5)
            print('NATIVE_CLOSE_REQUEST', flush=True)
            print('NATIVE_CLOSE_RESULT', await closer.close(), flush=True)
        page.run_task(finish)
    print('FLET_VERSION', importlib.metadata.version('flet'), flush=True)
    ft.run(main)


def native_probes():
    executables = [sys.executable, str(ROOT / '.venv-build/bin/python')]
    for index, executable in enumerate(dict.fromkeys(executables)):
        proc = subprocess.Popen([executable, str(Path(__file__).resolve()), '--native-child'],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)
        try:
            output, _ = proc.communicate(timeout=7)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            output, _ = proc.communicate(timeout=3)
        finally:
            # The process group contains only this test and its own Flet view.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        path = Path('/tmp') / f'cubeon-window-close-probe-{index}.log'
        path.write_text(output)
        if 'NATIVE_CLOSE_RESULT True' not in output or 'exception calling callback' in output:
            raise RuntimeError(f'Native close did not settle: {path}\n{output}')
        print(f'{executable}: close settled, captured native diagnostics in {path}')


if __name__ == '__main__':
    if '--native-child' in sys.argv:
        native_child()
    elif '--native' in sys.argv:
        native_probes()
    else:
        unittest.main()

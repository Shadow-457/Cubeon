"""Chat draft, shortcode, filtering, resize and follow-position regressions."""
from copy import deepcopy
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import time
import weakref
from unittest.mock import patch, Mock

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from cubeon import thread_safe_ui
from cubeon.theme import THEME, section_label
from test_chat_optimistic import FakePage, FakeService
from ui import chat_tab as chat


def scope(function):
    return dict(zip(function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__)))


class QueuePage(FakePage):
    def __init__(self):
        super().__init__()
        self.focus_calls = 0

    def run_task(self, fn, *args, **kwargs):
        if fn.__name__ == 'focus':
            self.focus_calls += 1
        return None


class ScrollPage(QueuePage):
    def __init__(self):
        super().__init__()
        self.scroll_tasks = []

    def run_task(self, fn, *args, **kwargs):
        if fn.__name__ == 'latest':
            self.scroll_tasks.append(fn)
        return super().run_task(fn, *args, **kwargs)

class ChatUXTests(unittest.TestCase):
    def setUp(self):
        self.page, self.service = QueuePage(), FakeService()
        self.roster = self.service.roster_payload()
        self.roster['friends'][0].update(uid='00000010', unread=3)
        self.roster['friends'].append({'name': 'bob', 'uid': '00000011',
                                      'minecraft_username': 'Bob', 'online': False})
        self.service.roster_payload = lambda: deepcopy(self.roster)
        self.service.peer_metadata = lambda name: next(f for f in self.roster['friends'] if f['name'] == name)
        self.repaint = patch.object(thread_safe_ui, 'refresh')
        self.repaint.start()
        self.addCleanup(self.repaint.stop)
        with (patch.object(chat.threading.Thread, 'start'),
              patch.object(chat._faces, 'get_face_b64', return_value=None)):
            self.root, self.refresh = chat.build_chat_tab(self.page, {}, {}, self.service,
                                                        section_label=section_label, **THEME)
        self.render = scope(scope(scope(self.refresh)['_tick'])['_tick_locked'])['_render_roster']
        self.friends = scope(scope(self.render)['_rebuild_friends'])
        self.select = scope(self.friends['_friend_rows']['alice']['row'].on_click)['_select']
        self.controls = scope(self.select)
        self.composer = self.controls['composer']

    def type(self, text):
        self.composer.value = text
        self.composer.on_change(None)

    def test_shortcode_suggestions_complete_and_survive_switch(self):
        self.select('alice')
        self.type('Bring a :di')
        suggestions = scope(self.controls['_sync_emoji_suggestions'])['emoji_suggestions']
        self.assertTrue(suggestions.visible)
        suggestions.controls[0].on_click(None)
        self.assertEqual(self.composer.value, 'Bring a 💎')
        self.assertFalse(suggestions.visible)
        self.select('bob')
        self.select('alice')
        self.assertEqual(self.composer.value, 'Bring a 💎')
        self.type('GG :smile: :+1: :pickaxe: :unknown:')
        self.assertEqual(self.composer.value, 'GG 😄 👍 ⛏️ :unknown:')

    def test_composer_has_no_manual_emoji_button(self):
        self.select('alice')
        self.assertIs(self.controls['composer_row'].controls[0], self.composer)
        self.assertEqual(len(self.controls['composer_row'].controls), 2)
        self.composer.on_focus(None)
        self.assertTrue(scope(scope(self.composer.on_focus)['_composer_focus'])['state']['chat_composing'])
        self.composer.on_blur(None)

    def test_empty_conversation_has_composer_and_send_tracks_connection(self):
        self.select('bob')
        self.assertTrue(self.controls['empty_state'].visible)
        self.assertTrue(self.controls['composer_row'].visible)
        send = scope(scope(self.composer.on_change)['_sync_composer'])['send_btn']
        self.assertTrue(send.disabled)
        self.type('Hello')
        self.assertFalse(send.disabled)
        self.roster['connected'] = False
        self.refresh()
        self.assertTrue(send.disabled)
        self.assertEqual(self.composer.value, 'Hello')
        self.roster['connected'] = True
        self.refresh()
        self.assertFalse(send.disabled)

    def test_filter_keeps_cached_rows_and_id_search(self):
        row = self.friends['_friend_rows']['alice']['row']
        choose = scope(self.friends['unread_filter'].on_click)['_choose_filter']
        choose('unread')
        self.assertEqual(self.friends['friends_col'].controls, [row])
        choose('all')
        field = self.friends['find_field']
        field.value = '00000011'
        field.on_change(None)
        self.assertEqual(self.friends['friends_col'].controls,
                         [self.friends['_friend_rows']['bob']['row']])
        field.value = ''
        field.on_change(None)
        self.assertIs(self.friends['_friend_rows']['alice']['row'], row)

    def test_latest_follow_reader_pause_jump_and_resize(self):
        for i in range(60):
            self.service.echo(f'message {i} ' + 'long text ' * 10)
        transcript = self.controls['transcript']
        self.select('alice')
        self.assertTrue(transcript.build_controls_on_demand)
        self.assertTrue(transcript.reverse)
        newest = transcript.controls[0].content.controls[0].content.controls[0].value
        self.assertTrue(newest.startswith('message 59 '))
        transcript.on_scroll(SimpleNamespace(extent_before=200, event_type=ft.ScrollType.UPDATE))
        self.assertTrue(scope(self.controls['_stick_bottom'])['_stick']['at_end'])
        transcript.on_scroll(SimpleNamespace(extent_before=600, event_type=ft.ScrollType.USER,
                                            direction=ft.ScrollDirection.REVERSE))
        self.service.echo('new incoming line')
        self.refresh()
        self.assertFalse(transcript.auto_scroll)
        self.assertTrue(self.controls['jump_row'].visible)
        button = scope(self.controls['_stick_bottom'])['jump_row'].content.controls[1]
        button.on_click(None)
        self.assertTrue(scope(self.controls['_stick_bottom'])['_stick']['at_end'])
        self.assertFalse(self.controls['jump_row'].visible)
        body = transcript.controls[1].content.controls[0].content.controls[0]
        previous_width = body.width
        self.root.controls[-1].on_size_change(SimpleNamespace(width=260))
        self.assertLess(body.width, previous_width)
        self.assertLessEqual(body.width, 260)

    def test_tab_return_keeps_messages_and_refresh_only_wakes_worker(self):
        for i in range(60):
            self.service.echo(f'message {i}')
        self.select('alice')
        self.type('Unfinished draft')
        transcript = self.controls['transcript']
        rows = tuple(transcript.controls)
        tick = scope(self.refresh)['_tick']
        state = scope(scope(self.composer.on_focus)['_composer_focus'])['state']
        payload = Mock(wraps=self.service.chat_payload)
        roster = Mock(wraps=self.service.roster_payload)
        with (patch.object(self.service, 'chat_payload', payload),
              patch.object(self.service, 'roster_payload', roster)):
            state['active_tab'] = 'mods'
            tick()
            state['active_tab'] = 'chat'
            poll_thread = scope(self.refresh)['poll_thread']
            with patch.object(poll_thread, 'is_alive', return_value=True):
                roster.reset_mock()
                payload.reset_mock()
                self.refresh()
                roster.assert_not_called()
                payload.assert_not_called()
                self.assertTrue(scope(self.refresh)['_wake'].is_set())
            self.assertEqual(tuple(transcript.controls), rows)
            self.assertEqual(self.composer.value, 'Unfinished draft')
            self.service.echo('Arrived while away')
            tick()
            payload.assert_called_once_with('alice', 59)
            self.assertEqual(tuple(transcript.controls[1:]), rows)
            self.assertEqual(transcript.controls[0].content.controls[0].content.controls[0].value,
                             'Arrived while away')

    def test_sending_returns_focus_to_composer(self):
        self.select('alice')
        self.type('GG')
        before = self.page.focus_calls
        send = scope(scope(self.composer.on_change)['_sync_composer'])['send_btn']
        with patch.object(chat.threading.Thread, 'start'):
            send.on_click(None)
        self.assertGreater(self.page.focus_calls, before)
        self.assertEqual(self.composer.value, '')

    def test_latest_scroll_targets_zero_and_skips_hidden_tab(self):
        self.select('alice')
        transcript = self.controls['transcript']
        page = ScrollPage()
        transcript._parent = weakref.ref(page)
        jump = self.controls['_stick_bottom']
        page_cell = dict(zip(jump.__code__.co_freevars, jump.__closure__))['page']
        page_cell.cell_contents = page
        commands = []

        async def invoke(name, args):
            commands.append((name, args))

        transcript._invoke_method = invoke
        self.service.echo('newest')
        self.refresh()
        jump(force=True)
        asyncio.run(page.scroll_tasks.pop(0)())
        self.assertEqual(commands[0][0], 'scroll_to')
        self.assertEqual(commands[0][1]['offset'], 0)
        self.assertIsNone(commands[0][1]['delta'])
        jump(force=True)
        state = scope(jump)['state']
        state['active_tab'] = 'mods'
        asyncio.run(page.scroll_tasks.pop(0)())
        self.assertEqual(len(commands), 1)
        state['active_tab'] = 'chat'
        listener = f'{type(transcript).__qualname__}({transcript._i})'
        for message in ('Session closed', f'{listener} Control must be added to the page first',
                        f'TimeoutException after 0:00:10.000000: Timeout waiting for invoke method listener for {listener}.scroll_to'):
            async def closed(name, args):
                raise RuntimeError(message)
            transcript._invoke_method = closed
            jump(force=True)
            asyncio.run(page.scroll_tasks.pop(0)())
        async def broken(name, args):
            raise RuntimeError('Unexpected renderer error')
        transcript._invoke_method = broken
        jump(force=True)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected renderer error'):
            asyncio.run(page.scroll_tasks.pop(0)())

    def test_reversed_transcript_trims_oldest(self):
        self.service.echo('seed')
        self.select('alice')
        transcript = self.controls['transcript']
        tick = scope(self.refresh)['_tick']
        for i in range(450):
            self.service.echo(f'ordered {i}')
        tick()
        bodies = [row.content.controls[0].content.controls[0].value
                  for row in transcript.controls
                  if len(row.content.controls) == 1]
        self.assertEqual(bodies[0], 'ordered 449')
        self.assertEqual(bodies[-1], 'ordered 50')
        self.assertEqual(len(bodies), chat._MAX_TRANSCRIPT)

    def test_dates_stay_above_their_messages_in_reversed_list(self):
        self.service.echo('yesterday message')
        self.service.echo('today message')
        now = int(time.time() * 1000)
        self.service.ring[0]['ts'] = now - 86400000
        self.select('alice')
        rows = self.controls['transcript'].controls
        self.assertEqual(rows[0].content.controls[0].content.controls[0].value, 'today message')
        self.assertEqual(rows[1].content.controls[1].value, 'Today')
        self.assertEqual(rows[2].content.controls[0].content.controls[0].value, 'yesterday message')
        self.assertEqual(rows[3].content.controls[1].value, 'Yesterday')


if __name__ == '__main__':
    unittest.main()

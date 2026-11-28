"""Chat draft, shortcode, filtering, resize and follow-position regressions."""
from copy import deepcopy
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import time
import weakref
import os
import subprocess
import traceback
from unittest.mock import patch, Mock

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from cubeon import thread_safe_ui
from cubeon import emoji
from cubeon._emoji_data import UNICODE_SHORTCODES
from cubeon.theme import THEME, section_label
from test_chat_optimistic import FakePage, FakeService, walk
from ui import chat_tab as chat


def scope(function):
    return dict(zip(function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__)))


class QueuePage(FakePage):
    def __init__(self):
        super().__init__()
        self.focus_calls = 0

    def run_task(self, fn, *args, **kwargs):
        if fn.__name__ in ('focus', 'request_focus'):
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

    def test_typing_and_seen_follow_the_active_conversation(self):
        self.service.send_chat_typing = Mock(return_value=True)
        payload = self.service.chat_payload
        self.service.chat_payload = lambda name, after: {
            **payload(name, after), "typing": name == "alice", "seen_id": "confirmed" if name == "alice" else None}
        self.service.echo("Hello")
        self.service.ring[-1]["id"] = "confirmed"
        self.select("alice")
        typing = next(c for c in walk(self.root) if c.data == "chat-typing")
        seen = next(c for c in walk(self.root) if c.data == "chat-seen")
        self.assertTrue(typing.visible and seen.visible)
        self.type("Next message")
        self.refresh()
        self.refresh()
        self.service.send_chat_typing.assert_called_once_with("alice")
        self.service.echo("Not read yet")
        self.service.ring[-1]["id"] = "unread"
        self.refresh()
        self.assertFalse(seen.visible)
        self.select("bob")
        self.assertFalse(typing.visible or seen.visible)

    def test_shortcode_suggestions_complete_and_survive_switch(self):
        self.select('alice')
        self.type('Bring a :diam')
        suggestions = scope(self.controls['_sync_emoji_suggestions'])['emoji_suggestions']
        self.assertTrue(suggestions.visible)
        suggestions.controls[0].on_click(None)
        self.assertEqual(self.composer.value, 'Bring a 💎')
        self.assertFalse(suggestions.visible)
        self.select('bob')
        self.select('alice')
        self.assertEqual(self.composer.value, 'Bring a 💎')
        self.type('GG :smile: :+1: :pickaxe: :unknown:')
        self.assertEqual(self.composer.value, 'GG :smile: :+1: :pickaxe: :unknown:')
        jobs = []
        with patch.object(chat.threading.Thread, 'start', lambda thread: jobs.append(thread)):
            self.composer.on_submit(None)
        jobs[0].run()
        self.assertEqual(self.service.sent, [('alice', 'GG 😄 👍 ⛏️ :unknown:')])

    def test_every_unicode_sequence_is_available_from_the_shared_table(self):
        self.assertIs(chat._EMOJI_CODES, emoji.SHORTCODES)
        self.assertEqual(len(set(UNICODE_SHORTCODES.values())), emoji.EMOJI_COUNT)
        self.assertGreaterEqual(emoji.EMOJI_COUNT, 3972)
        self.assertTrue(set(UNICODE_SHORTCODES.values()) <= set(emoji.SHORTCODES.values()))
        for code, value in emoji.all_shortcodes():
            self.assertEqual(emoji.expand_emoji(':' + code.upper() + ':'), value)

    def test_closed_codes_preserve_typing_and_expand_when_sent(self):
        self.select('alice')
        for text, expected in (
            ('Hi :flag_us: :thumbs_up_medium_skin_tone: :woman_astronaut: :melting_face:!', 'Hi 🇺🇸 👍🏽 👩\u200d🚀 🫠!'),
            (':keycap_number_sign::keycap_asterisk::flag_wales: :unknown:', '#️⃣*️⃣🏴\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f :unknown:'),
            (':distorted_face: :hairy_creature:', '\U0001faea \U0001fac8'),
        ):
            self.type(text)
            self.assertEqual(self.composer.value, text)
            jobs = []
            with patch.object(chat.threading.Thread, 'start', lambda thread: jobs.append(thread)):
                self.composer.on_submit(None)
            jobs[0].run()
            self.assertEqual(self.service.sent[-1], ('alice', expected))

    def test_search_reaches_name_tokens_and_deduplicates_aliases(self):
        self.assertEqual(emoji.suggestions('THUMBSUP')[0], 'thumbsup')
        self.assertIn('face_with_peeking_eye', emoji.suggestions('peeking'))
        self.assertLessEqual(len(emoji.suggestions('')), 5)
        results = emoji.suggestions('flag')
        self.assertEqual(len(results), len({emoji.SHORTCODES[code] for code in results}))
        self.assertEqual(emoji.suggestions('not_a_real_emoji'), [])
        self.assertEqual(emoji.suggestions('smile', limit=0), [])

    def test_typing_keeps_suggestion_buttons_and_editor_without_focus_requests(self):
        self.select('alice')
        suggestions = scope(self.controls['_sync_emoji_suggestions'])['emoji_suggestions']
        host = scope(self.controls['_sync_emoji_suggestions'])['emoji_host']
        self.type(':')
        buttons = list(suggestions.controls)
        glyphs = [button.content for button in buttons]
        editor_row = self.controls['composer_row']
        before = self.page.focus_calls
        with patch.object(ft.context, 'disable_auto_update') as disable:
            for text in (':', ':f', ':fl', ':flag', ':flag_', ':flag_us', ':unknown', ':'):
                self.type(text)
                self.assertEqual(buttons[:len(suggestions.controls)], suggestions.controls)
                self.assertEqual(glyphs[:len(suggestions.controls)], [button.content for button in suggestions.controls])
                self.assertIs(editor_row.controls[0], self.composer)
                self.assertTrue(host.visible)
                self.assertEqual(self.page.focus_calls, before)
            self.assertEqual(disable.call_count, 8)
        self.assertEqual(len(buttons), 48)
        self.type(':unknown')
        self.assertEqual(host.height, 0)
        self.assertFalse(suggestions.visible)
        self.type(':FLAG_US')
        choice = next(button for button in buttons if button.visible and button.tooltip == 'Insert :flag_us:')
        choice.on_click(None)
        self.assertEqual(self.composer.value, '🇺🇸')
        self.assertGreater(self.page.focus_calls, before)

    def test_full_picker_pages_every_sequence_and_reuses_loaded_controls(self):
        self.select('alice')
        picker = scope(self.controls['_sync_emoji_suggestions'])
        grid = picker['emoji_suggestions']
        results = scope(picker['_append_emoji_page'])['emoji_results']
        self.type(':')
        self.assertEqual(len(results['codes']), emoji.EMOJI_COUNT)
        self.assertEqual(len(grid.controls), 48)
        self.assertTrue(grid.build_controls_on_demand)
        self.assertEqual(picker['emoji_host'].height, 184)
        self.assertIn(f'{emoji.EMOJI_COUNT:,}', picker['emoji_count'].value)
        event = SimpleNamespace(pixels=952, max_scroll_extent=1000, viewport_dimension=164)
        with patch.object(ft.context, 'disable_auto_update') as disable:
            grid.on_scroll(SimpleNamespace(pixels=100, max_scroll_extent=1000, viewport_dimension=164))
            self.assertEqual(len(grid.controls), 48)
            while results['loaded'] < len(results['codes']):
                previous = results['loaded']
                grid.on_scroll(event)
                self.assertLessEqual(results['loaded'] - previous, 48)
            self.assertGreater(disable.call_count, 80)
        self.assertEqual({button.content.value for button in grid.controls}, set(UNICODE_SHORTCODES.values()))
        self.assertEqual(len(grid.controls), emoji.EMOJI_COUNT)
        pool = list(grid.controls)
        self.type('x')
        grid.on_scroll(event)
        self.assertEqual(grid.controls, [])
        self.type(':')
        self.assertEqual(grid.controls, pool[:48])

    def test_picker_searches_tones_flags_and_tokens_and_resets_scroll(self):
        self.select('alice')
        grid = scope(self.controls['_sync_emoji_suggestions'])['emoji_suggestions']
        with patch.object(chat.scrolling, 'to_top') as reset:
            for query, expected in (('flag_us', '🇺🇸'), ('medium_skin_tone', '👍🏽'),
                                    ('astronaut', '👩\u200d🚀'), ('peeking', '🫣')):
                self.type(':' + query.upper())
                results = scope(scope(self.controls['_sync_emoji_suggestions'])['_append_emoji_page'])['emoji_results']
                self.assertIn(expected, {emoji.SHORTCODES[code] for code in results['codes']})
            self.assertEqual(reset.call_count, 4)
            reset.assert_called_with(self.page, grid)

    def test_unknown_and_literal_colons_preserve_text_and_sending_expands_all_codes(self):
        self.select('alice')
        literal = '12:30 https://example.com :unknown: raw 😀'
        self.type(literal)
        self.assertEqual(self.composer.value, literal)
        self.composer.value = ':woman_astronaut: :flag_us:'
        send = scope(scope(self.composer.on_change)['_sync_composer'])['send_btn']
        jobs = []
        with patch.object(chat.threading.Thread, 'start', lambda thread: jobs.append(thread)):
            send.on_click(None)
        jobs[0].run()
        self.assertEqual(self.service.sent, [('alice', '👩\u200d🚀 🇺🇸')])

    def test_enter_accepts_top_emoji_match_without_sending_the_draft(self):
        self.select('alice')
        self.type('A :wilte')
        before = self.page.focus_calls
        self.composer.on_submit(None)
        self.assertEqual(self.composer.value, 'A 🥀')
        self.assertEqual(self.service.sent, [])
        self.assertGreater(self.page.focus_calls, before)
        self.select('bob')
        self.select('alice')
        self.assertEqual(self.composer.value, 'A 🥀')
        jobs = []
        with patch.object(chat.threading.Thread, 'start', lambda thread: jobs.append(thread)):
            self.composer.on_submit(None)
        jobs[0].run()
        self.assertEqual(self.service.sent, [('alice', 'A 🥀')])

    def test_enter_sends_unknown_shortcode_when_no_match_is_open(self):
        self.select('alice')
        self.type('A :zzz_unknown')
        jobs = []
        with patch.object(chat.threading.Thread, 'start', lambda thread: jobs.append(thread)):
            self.composer.on_submit(None)
        jobs[0].run()
        self.assertEqual(self.service.sent, [('alice', 'A :zzz_unknown')])

    def test_composer_has_no_manual_emoji_button(self):
        self.select('alice')
        self.assertIs(self.controls['composer_row'].controls[0], self.composer)
        self.assertEqual(len(self.controls['composer_row'].controls), 2)
        self.composer.on_focus(None)
        self.assertTrue(scope(scope(self.composer.on_focus)['_composer_focus'])['state']['chat_composing'])
        self.composer.on_blur(None)

    def test_supported_links_render_bounded_media_embeds(self):
        self.service.echo('gif https://media.tenor.com/example/cube.gif?width=640!')
        self.service.echo('video https://youtu.be/dQw4w9WgXcQ?t=4')
        self.service.echo('site https://ylet.online')
        self.select('alice')
        embeds = [control for control in walk(self.controls['transcript'])
                  if isinstance(control, ft.Stack) and isinstance(control.data, dict)
                  and control.data.get('chat_link_embed')]
        self.assertEqual({embed.data['kind'] for embed in embeds}, {'gif', 'youtube', 'link'})
        sources = {control.src for control in walk(self.controls['transcript'])
                   if isinstance(control, ft.Image)}
        self.assertIn('https://media.tenor.com/example/cube.gif?width=640', sources)
        self.assertIn('https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', sources)
        labels = {control.value for control in walk(self.controls['transcript'])
                  if isinstance(control, ft.Text)}
        self.assertIn('ylet.online', labels)
        previous_widths = [embed.width for embed in embeds]
        self.root.controls[-1].on_size_change(SimpleNamespace(width=260))
        self.assertTrue(all(embed.width < before
                            for embed, before in zip(embeds, previous_widths)))

    def test_link_preview_parser_rejects_lookalike_hosts(self):
        preview = chat._link_preview(
            'site https://example.com/page then https://youtube.com/shorts/dQw4w9WgXcQ)')
        self.assertEqual(preview['kind'], 'youtube')
        self.assertEqual(preview['url'], 'https://youtube.com/shorts/dQw4w9WgXcQ')
        lookalike = chat._link_preview('https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ')
        self.assertEqual(lookalike['kind'], 'link')
        self.assertEqual(lookalike['host'], 'youtube.com.evil.test')
        self.assertIsNone(chat._link_preview('javascript:alert(1)'))

    def test_giphy_share_link_renders_inline_and_keeps_original_link(self):
        url = 'https://giphy.com/gifs/tim-and-eric-hacked-awesome-show-DsA5XPVvKIstEah1by'
        self.service.echo(url)
        self.select('alice')
        bubble = self.controls['transcript'].controls[0].content.controls[0]
        self.assertEqual(bubble.content.controls[0].value, url)
        embed = bubble.content.controls[1]
        self.assertEqual(embed.data['kind'], 'gif')
        self.assertEqual(embed.data['url'], url)
        image = next(control for control in walk(embed) if isinstance(control, ft.Image))
        self.assertEqual(image.src, 'https://media.giphy.com/media/DsA5XPVvKIstEah1by/giphy.gif')
        self.assertEqual(image.fit, ft.BoxFit.CONTAIN)
        self.assertIsNotNone(image.error_content)
        previous_width = embed.width
        self.root.controls[-1].on_size_change(SimpleNamespace(width=260))
        self.assertLess(embed.width, previous_width)

    def test_giphy_share_variants_and_invalid_links(self):
        for url in (
            'https://giphy.com/gifs/DsA5XPVvKIstEah1by',
            'https://www.giphy.com/gifs/show-DsA5XPVvKIstEah1by/?utm_source=share',
            'https://m.giphy.com/stickers/show-DsA5XPVvKIstEah1by',
            'https://giphy.com/embed/DsA5XPVvKIstEah1by',
        ):
            with self.subTest(url=url):
                preview = chat._link_preview('https://ylet.online then ' + url + ')')
                self.assertEqual(preview['kind'], 'gif')
                self.assertEqual(preview['url'], url)
                self.assertEqual(preview['source'],
                                 'https://media.giphy.com/media/DsA5XPVvKIstEah1by/giphy.gif')
        for url in (
            'https://giphy.com.evil.test/gifs/show-DsA5XPVvKIstEah1by',
            'https://giphy.com/search/happy',
            'https://giphy.com/gifs/',
            'https://giphy.com/gifs/show-',
            'https://giphy.com/embed/id%2Fother',
        ):
            with self.subTest(url=url):
                self.assertEqual(chat._link_preview(url)['kind'], 'link')

    def test_empty_conversation_has_composer_and_send_tracks_connection(self):
        self.select('bob')
        self.assertTrue(scope(self.controls['_sync_empty_state'])['empty_state'].visible)
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

    def test_latest_follow_and_resize_without_jump_button(self):
        for i in range(60):
            self.service.echo(f'message {i} ' + 'long text ' * 10)
        transcript = self.controls['transcript']
        self.select('alice')
        self.assertTrue(transcript.build_controls_on_demand)
        self.assertTrue(transcript.reverse)
        newest = transcript.controls[0].content.controls[0].content.controls[0].value
        self.assertTrue(newest.startswith('message 59 '))
        self.service.echo('new incoming line')
        self.refresh()
        self.assertFalse(transcript.auto_scroll)
        self.assertIsNone(transcript.on_scroll)
        self.assertFalse(any(getattr(control, 'content', None) == 'Jump to latest'
                             for control in walk(self.root)))
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
        jump(force=True)
        stale = page.scroll_tasks.pop(0)
        self.select('bob')
        self.select('alice')
        asyncio.run(stale())
        self.assertEqual(len(commands), 1)
        page.scroll_tasks.clear()
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
                  if isinstance(row.content, ft.Row)]
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
        self.assertEqual(rows[1].content.value, 'Today')
        self.assertEqual(rows[2].content.controls[0].content.controls[0].value, 'yesterday message')
        self.assertEqual(rows[3].content.value, 'Yesterday')


async def native_emoji(page):
    """Type through the real desktop editor; suggestions must retain focus."""
    from PIL import ImageGrab
    from cubeon.theme import FONT_URLS, apply_page_theme
    from unittest.mock import patch
    state = {'active_tab': 'chat'}
    service = FakeService()
    apply_page_theme(page)
    page.fonts = FONT_URLS
    page.padding = 24
    page.window.width, page.window.height = 1200, 760
    page.window.left = page.window.top = 0
    thread_safe_ui.install(page)
    with patch.object(chat.threading.Thread, 'start'), patch.object(chat._faces, 'get_face_b64', return_value=None):
        root, refresh = chat.build_chat_tab(page, {}, state, service, section_label=section_label, **THEME)
    tick = scope(refresh)['_tick']
    render = scope(scope(tick)['_tick_locked'])['_render_roster']
    friends = scope(scope(render)['_rebuild_friends'])
    select = scope(friends['_friend_rows']['alice']['row'].on_click)['_select']
    composer = scope(select)['composer']
    picker = scope(scope(select)['_sync_emoji_suggestions'])
    choices = picker['emoji_suggestions']
    results = scope(picker['_append_emoji_page'])['emoji_results']
    blur_events = []
    original_blur = composer.on_blur
    def blurred(event):
        blur_events.append(composer.value)
        original_blur(event)
    composer.on_blur = blurred
    page.add(root)
    thread_safe_ui.mark_mounted(page)
    select('alice')
    await asyncio.sleep(1.5)
    print('NATIVE_EMOJI: mounted', flush=True)
    out = Path(__file__).resolve().parents[1] / 'archive/ui-captures/chat-emoji'
    out.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'initial.png')
    async def command(*args):
        process = subprocess.Popen(['xdotool', *args])
        assert await asyncio.to_thread(process.wait, timeout=10) == 0
        await asyncio.sleep(.3)
    await command('mousemove', '750', str(int(page.height - 64)), 'click', '1')
    assert state.get('chat_composing'), 'The native editor did not gain focus.'
    blur_events.clear()
    await command('type', '--clearmodifiers', '--delay', '55', ':')
    assert len(results['codes']) == emoji.EMOJI_COUNT, repr(composer.value)
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'all-emojis.png')
    loaded = results['loaded']
    await command('mousemove', '600', str(int(page.height - 150)), 'click', '--repeat', '12', '--delay', '90', '5')
    assert results['loaded'] > loaded, 'The native picker did not load the next emoji page.'
    assert state.get('chat_composing') and not blur_events
    print('NATIVE_EMOJI: scrolled', flush=True)
    await command('type', '--clearmodifiers', '--delay', '55', 'thumbsup')
    await command('key', 'Return')
    assert composer.value == '👍' and not service.sent
    for fragment in (' works ', ':zzz_unknown:', '!', ' next'):
        await command('type', '--clearmodifiers', '--delay', '55', fragment)
        assert state.get('chat_composing'), f'Lost native typing focus after {fragment!r}: {composer.value!r}'
        assert not blur_events, f'Suggestions blurred the composer: {blur_events}'
    assert composer.value == '👍 works :zzz_unknown:! next', composer.value
    print('NATIVE_EMOJI: continuous typing', flush=True)
    # Exercise names from the full catalog after scrolling and narrowing it.
    await command('type', '--clearmodifiers', '--delay', '40', ' :flag_us: :woman_astronaut:')
    assert composer.value.endswith(' :flag_us: :woman_astronaut:'), composer.value
    assert state.get('chat_composing') and not blur_events
    print('NATIVE_EMOJI: full codes', flush=True)
    await command('type', '--clearmodifiers', '--delay', '40', ' :melting')
    assert choices.controls[0].tooltip == 'Insert :melting_face:'
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'searched.png')
    await command('mousemove', '384', str(int(page.height - 248)), 'click', '1')
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'clicked.png')
    print(f'NATIVE_EMOJI: clicked, focus={state.get("chat_composing")}, text={composer.value!r}', flush=True)
    await asyncio.sleep(.2)
    await command('type', '--clearmodifiers', '--delay', '40', ' done')
    assert composer.value.endswith(' 🫠 done'), composer.value
    assert state.get('chat_composing')
    await command('type', '--clearmodifiers', '--delay', '40', ' :wilte')
    await command('key', 'Return')
    print('NATIVE_EMOJI: Enter completion', flush=True)
    assert composer.value.endswith(' 🥀'), composer.value
    assert not service.sent, 'Emoji completion sent the draft.'
    await command('type', '--clearmodifiers', '--delay', '40', ' rose')
    assert composer.value.endswith(' 🥀 rose') and state.get('chat_composing')
    await command('type', '--clearmodifiers', '--delay', '25', ' :flag_us: wow :woman_astronaut: next :smile: fine')
    assert composer.value.endswith(' :flag_us: wow :woman_astronaut: next :smile: fine'), composer.value
    await command('key', 'shift+Return')
    assert composer.value.endswith('\n') and not service.sent, composer.value
    await command('type', '--clearmodifiers', '--delay', '25', 'next line')
    assert composer.value.endswith('\nnext line') and state.get('chat_composing')
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'typed.png')
    message = composer.value
    await command('key', 'Return')
    assert service.sent == [('alice', emoji.expand_emoji(message))] and not composer.value
    await command('type', '--clearmodifiers', '--delay', '25', 'after send')
    assert composer.value == 'after send' and state.get('chat_composing')
    print('NATIVE_EMOJI_PASS: full picker, wheel pagination, search, click/Enter completion, Shift+Enter and send focus.', flush=True)
    await page.window.close()


if __name__ == '__main__':
    if '--native' in sys.argv:
        failures = []
        async def checked(page):
            try:
                await native_emoji(page)
            except Exception:
                failures.append(True)
                traceback.print_exc()
            finally:
                await page.window.close()
        ft.run(checked, assets_dir=str(Path(__file__).resolve().parents[1] / 'assets'))
        sys.exit(bool(failures))
    else:
        unittest.main()

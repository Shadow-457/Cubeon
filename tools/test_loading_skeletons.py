"""Offline loading lifecycles: retained geometry, failure cleanup and stale history."""
import inspect
import os
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from cubeon import background_refresh, milestones, thread_safe_ui, cosmetics
from cubeon.theme import THEME, section_label
from ui import chat_tab, stats_tab, appearance_preview, skin_tab
from test_chat_optimistic import FakePage, FakeService, walk, texts
from test_skin_loading import build as build_skin, tab


class QueuedThread:
    jobs = []
    def __init__(self, target, args=(), **kwargs):
        self.target = lambda: target(*args)
    def start(self):
        self.jobs.append(self.target)
    def is_alive(self):
        return True


def queued_module():
    QueuedThread.jobs = []
    return SimpleNamespace(**{**vars(threading), 'Thread': QueuedThread})


def find(root, data):
    return next(control for control in walk(root) if getattr(control, 'data', None) == data)


def friend_click(root, name):
    candidates = [control for control in walk(root) if callable(getattr(control, 'on_click', None))
                  and name in ' '.join(texts(control)).lower()]
    row = min(candidates, key=lambda control: len(walk(control)))
    row.on_click(SimpleNamespace(control=row))


class LoadingSkeletons(unittest.TestCase):
    def setUp(self):
        self.repaint = patch.object(thread_safe_ui, 'refresh')
        self.repaint.start()
        self.addCleanup(self.repaint.stop)

    def stats(self):
        self.queued = patch.object(background_refresh, 'threading', queued_module())
        self.queued.start()
        self.addCleanup(self.queued.stop)
        root, refresh = stats_tab.build_stats_tab(FakePage(), {}, {}, section_label=section_label,
                                                  go_to_tab=lambda *_: None, **THEME)
        return root, refresh

    def chat(self, service=None):
        service = service or FakeService()
        self.queued = patch.object(chat_tab, 'threading', queued_module())
        self.queued.start()
        self.addCleanup(self.queued.stop)
        root, refresh = chat_tab.build_chat_tab(FakePage(), {}, {}, service,
                                                section_label=section_label, **THEME)
        tick = inspect.getclosurevars(refresh).nonlocals['_tick']
        return root, refresh, tick

    def test_stats_reads_after_build_and_retains_ready_dashboard(self):
        with patch.object(milestones, 'snapshot', return_value={'seconds_played': 3600}) as read:
            root, refresh = self.stats()
            self.assertFalse(read.called)
            self.assertTrue(find(root, 'stats-chart-loading').visible)
            metrics = [find(root, f'stats-metric:{index}') for index in range(4)]
            self.assertTrue(all(not metric.visible for metric in metrics))
            QueuedThread.jobs.pop(0)()
            self.assertFalse(find(root, 'stats-chart-loading').visible)
            self.assertEqual(metrics[0].value, '1h')
            hosts = [(c, c.height) for c in walk(root) if isinstance(c, ft.Stack) and c.height in (30, 16)]
            refresh(background=True)
            self.assertFalse(find(root, 'stats-chart-loading').visible)
            self.assertEqual(metrics[0].value, '1h')
            QueuedThread.jobs.pop(0)()
            self.assertEqual([(id(c), c.height) for c, _ in hosts], [(id(c), height) for c, height in hosts])
            self.assertTrue(all(metric is find(root, f'stats-metric:{index}') for index, metric in enumerate(metrics)))

    def test_stats_failure_clears_loading_and_retry_recovers(self):
        with patch.object(milestones, 'snapshot', side_effect=OSError('offline fixture')):
            root, refresh = self.stats()
            with self.assertLogs('cubeon.background_refresh', level='WARNING'):
                QueuedThread.jobs.pop(0)()
        self.assertFalse(find(root, 'stats-chart-loading').visible)
        self.assertFalse(find(root, 'stats-servers-loading').visible)
        self.assertTrue(any('Couldn\'t load stats' in value for value in texts(root)))
        with patch.object(milestones, 'snapshot', return_value={'seconds_played': 7200}):
            refresh(background=True)
            QueuedThread.jobs.pop(0)()
        self.assertEqual(find(root, 'stats-metric:0').value, '2h')
        with patch.object(milestones, 'snapshot', side_effect=OSError('refresh fixture')):
            refresh(background=True)
            with self.assertLogs('cubeon.background_refresh', level='WARNING'):
                QueuedThread.jobs.pop(0)()
        self.assertEqual(find(root, 'stats-metric:0').value, '2h')

    def test_chat_skeletons_do_not_enter_transcript_or_trigger_click_reads(self):
        service = FakeService()
        root, refresh, tick = self.chat(service)
        roster = find(root, 'chat-roster-loading')
        self.assertTrue(roster.visible)
        tick()
        self.assertFalse(roster.visible)
        with patch.object(service, 'chat_payload', wraps=service.chat_payload) as read:
            friend_click(root, 'alice')
            self.assertFalse(read.called)
            loading = find(root, 'chat-history-loading')
            self.assertTrue(loading.visible)
            transcript = next(c for c in walk(root) if isinstance(c, ft.ListView) and c.reverse)
            self.assertEqual(transcript.controls, [])
            tick()
        self.assertFalse(loading.visible)
        self.assertEqual(transcript.controls, [])
        self.assertTrue('Say hello to Alice' in texts(root))
        self.assertIs(loading, find(root, 'chat-history-loading'))

    def test_chat_failure_clears_placeholder_and_next_poll_recovers(self):
        service = FakeService()
        root, refresh, tick = self.chat(service)
        with patch.object(service, 'roster_payload', side_effect=OSError('fixture')):
            tick()
        self.assertFalse(find(root, 'chat-roster-loading').visible)
        tick()
        friend_click(root, 'alice')
        with patch.object(service, 'chat_payload', side_effect=OSError('fixture')):
            tick()
        self.assertFalse(find(root, 'chat-history-loading').visible)
        self.assertIn("Couldn't load this conversation", texts(root))
        service.echo('Ready now')
        tick()
        self.assertEqual(texts(root, 'Ready now'), ['Ready now'])

    def test_chat_stale_history_cannot_finish_new_selection(self):
        service = FakeService()
        original = service.roster_payload
        service.roster_payload = lambda: {**original(), 'friends': original()['friends'] + [
            {'name': 'bob', 'minecraft_username': 'Bob'}]}
        root, refresh, tick = self.chat(service)
        tick()
        friend_click(root, 'alice')
        def switched_history(*args, **kwargs):
            friend_click(root, 'bob')
            return {'messages': [{'seq': 0, 'dir': 'in', 'name': 'Alice', 'text': 'Stale Alice', 'ts': 0}]}
        with patch.object(service, 'chat_payload', side_effect=switched_history):
            tick()
        self.assertTrue(find(root, 'chat-history-loading').visible)
        self.assertEqual(texts(root, 'Stale Alice'), [])
        tick()
        self.assertFalse(find(root, 'chat-history-loading').visible)

    def test_appearance_skeleton_scales_and_retires_without_replacing_image(self):
        stage = appearance_preview.AppearancePreview({})
        image = stage.image
        self.assertTrue(stage.skeleton.visible)
        stage.resize(160, repaint=False)
        self.assertEqual(stage.skeleton.width, stage.image.width)
        self.assertEqual(stage.skeleton.controls[0].width, 34)
        stage._publish(0, stage._camera_key(), b'first frame fixture', 0)
        self.assertFalse(stage.skeleton.visible)
        self.assertIs(stage.image, image)
        with patch.object(appearance_preview, 'threading', queued_module()):
            stage.refresh(invalidate=True)
        self.assertFalse(stage.skeleton.visible)
        self.assertEqual(stage.image.src, b'first frame fixture')

    def test_appearance_failure_removes_loading_silhouette(self):
        with patch.object(appearance_preview, 'threading', queued_module()):
            stage = appearance_preview.AppearancePreview({})
            stage.refresh()
            with patch.object(appearance_preview.CharacterModel,
                              'from_config', side_effect=OSError('fixture')):
                with self.assertLogs('ui.appearance_preview', level='ERROR'):
                    QueuedThread.jobs.pop(0)()
        self.assertFalse(stage.skeleton.visible)
        self.assertIn("Couldn't load preview", stage.note.value)

    def test_cosmetic_thumbnail_skeletons_keep_artwork_slots(self):
        queued = queued_module()
        with patch.object(skin_tab, 'threading', queued), patch.object(appearance_preview, 'threading', queued), \
             patch.object(cosmetics, 'render_thumbnail', return_value=None):
            root = build_skin(FakePage())
            start = len(QueuedThread.jobs)
            tab(root, 'Back').on_click(None)
            placeholders = [c for c in walk(root) if getattr(c, 'data', None) == 'content-skeleton' and c.width == 76]
            self.assertTrue(placeholders)
            geometry = [(c.width, c.height) for c in placeholders]
            for job in QueuedThread.jobs[start:]:
                job()
            self.assertEqual([(c.width, c.height) for c in placeholders], geometry)
            self.assertTrue(all(isinstance(c.content, ft.Icon) for c in placeholders))
            self.assertTrue(all(c.bgcolor is None for c in placeholders))


if __name__ == '__main__':
    unittest.main()

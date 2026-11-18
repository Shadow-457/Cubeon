"""Setup validates drafts and only closes after a successful save."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import thread_safe_ui
from cubeon.config import validate_username
from ui import onboarding
from test_chat_optimistic import FakePage, walk


def scope(fn):
    return dict(zip(fn.__code__.co_freevars,
                    (cell.cell_contents for cell in fn.__closure__)))


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.finish_result = (True, '')
        self.pending = []
        self.page = FakePage()
        self.focus = []
        self.page.run_task = lambda fn: self.focus.append(fn.__name__)
        self.refresh = patch.object(thread_safe_ui, 'refresh')
        self.refresh.start()
        self.addCleanup(self.refresh.stop)

        def timer(delay, callback):
            self.pending.append(callback)
            return Mock()
        self.timer = patch.object(onboarding.threading, 'Timer', side_effect=timer)
        self.timer.start()
        self.addCleanup(self.timer.stop)
        self.root = onboarding.build_onboarding(
            self.page, initial_name='Steve', friends_on=True,
            validate_name=validate_username, on_finish=self.save)
        self.root.opacity = 1
        self.next = next(c for c in walk(self.root) if getattr(c, 'data', None) == 'onboarding-next')
        self.field = scope(self.next.on_click)['name_field']

    def save(self, name):
        self.assertFalse(thread_safe_ui.TREE_LOCK._is_owned())
        self.saved.append(name)
        return self.finish_result

    def set_name(self):
        self.next.on_click(None)
        self.field.value = '  Alex_123  '
        self.field.on_change(None)

    def test_name_is_not_saved_while_typing(self):
        self.set_name()
        self.assertEqual(self.saved, [])
        self.assertIn('focus', self.focus)
        self.assertEqual(self.field.value, '  Alex_123  ')

    def test_invalid_name_stays_editable_then_clears_error(self):
        self.next.on_click(None)
        self.field.value = 'bad name'
        self.field.on_submit(None)
        self.assertTrue(onboarding._has_field_error(self.field))
        self.assertEqual(self.next.content, 'Continue')
        self.assertEqual(self.saved, [])
        self.field.value = 'Alex_123'
        self.field.on_change(None)
        self.assertFalse(onboarding._has_field_error(self.field))
        self.field.on_submit(None)
        self.assertEqual(self.saved, [])
        self.next.on_click(None)
        self.assertEqual(self.saved, ['Alex_123'])

    def test_save_failure_preserves_name_and_retries(self):
        self.set_name()
        self.field.on_submit(None)
        self.finish_result = (False, 'Disk is full')
        self.next.on_click(None)
        self.assertTrue(self.root.visible)
        self.assertEqual(self.root.opacity, 1)
        self.assertTrue(onboarding._has_field_error(self.field))
        self.assertEqual(self.field.value, '  Alex_123  ')
        self.assertEqual(self.next.content, 'Continue')
        self.finish_result = (True, '')
        self.field.on_submit(None)
        self.next.on_click(None)
        self.assertEqual(self.saved, ['Alex_123', 'Alex_123'])
        self.assertEqual(self.root.opacity, 0)
        self.pending[-1]()
        self.assertFalse(self.root.visible)

    def test_finish_runs_once_even_with_reentrant_click(self):
        self.set_name()
        self.field.on_submit(None)
        finish = scope(self.next.on_click)['_finish']
        finish_scope = scope(finish)
        cell = dict(zip(finish.__code__.co_freevars, finish.__closure__))['on_finish']
        def save(name):
            self.next.on_click(None)
            return self.save(name)
        cell.cell_contents = save
        self.next.on_click(None)
        self.next.on_click(None)
        self.assertEqual(self.saved, ['Alex_123'])
        self.assertTrue(finish_scope['state']['done'])

    def test_skip_uses_a_valid_name(self):
        self.field.value = 'bad name'
        skip = next(c for c in walk(self.root) if getattr(c, 'data', None) == 'onboarding-skip')
        skip.on_click(None)
        self.assertEqual(self.saved, ['Steve'])
        self.assertEqual(self.root.opacity, 0)

    def test_back_preserves_the_draft(self):
        self.set_name()
        back = next(c for c in walk(self.root) if getattr(c, 'data', None) == 'onboarding-back')
        back.on_click(None)
        self.next.on_click(None)
        self.assertEqual(self.field.value, '  Alex_123  ')
        self.assertEqual(self.saved, [])


if __name__ == '__main__':
    unittest.main()

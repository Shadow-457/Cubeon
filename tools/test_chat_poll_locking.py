"""Chat polling must not deadlock a socket callback delivering a launcher notice."""
import os
import sys
import threading
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import thread_safe_ui
from cubeon.theme import THEME, section_label
from test_chat_optimistic import FakePage, FakeService
from ui import chat_tab


class ConnectionService(FakeService):
    def __init__(self):
        super().__init__()
        self.lifecycle = threading.RLock()
        self.reading = threading.Event()
        self.online = False

    def roster_payload(self):
        self.reading.set()
        with self.lifecycle:
            result = super().roster_payload()
            result.update(connected=self.online, available=True,
                          connection={"state": "connected" if self.online else "retrying"})
            return result


service = ConnectionService()
with (patch.object(chat_tab.threading.Thread, "start"),
      patch.object(chat_tab._faces, "get_face_b64", return_value=None),
      patch.object(thread_safe_ui, "refresh")):
    root, refresh = chat_tab.build_chat_tab(FakePage(), {}, {}, service,
                                          section_label=section_label, **THEME)
service.reading.clear()
socket_ready = threading.Event()
notice_done = threading.Event()
errors = []


def socket_callback():
    with service.lifecycle:
        socket_ready.set()
        if not service.reading.wait(2):
            errors.append("poll did not reach connection state")
            return
        # Mirrors a FriendsClient callback delivering a ui/toast notice.
        with thread_safe_ui.TREE_LOCK:
            service.online = True
            notice_done.set()


def poll():
    try:
        refresh()
    except Exception as error:
        errors.append(error)


callback = threading.Thread(target=socket_callback, daemon=True)
reader = threading.Thread(target=poll, daemon=True)
callback.start()
assert socket_ready.wait(2), "socket callback did not start"
reader.start()
callback.join(2)
reader.join(2)
assert notice_done.is_set() and not reader.is_alive(), "Chat poll and socket notice deadlocked"
assert not errors, errors


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


assert any(getattr(c, "value", None) == "Connected" for c in walk(root)), "connected state stayed stale"
print("PASS: socket notice finishes, Chat poll resumes, and Connected renders")

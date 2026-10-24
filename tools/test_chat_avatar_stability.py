"""Chat avatars stay mounted through roster, presence, and profile updates."""
import base64
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.object_patch import ObjectPatch
from flet.messaging.protocol import configure_encode_object_for_msgpack
from cubeon import thread_safe_ui
from cubeon.theme import THEME, section_label
from test_chat_optimistic import FakePage, FakeService
from ui import chat_tab as chat

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'}   {label}")


class RosterService(FakeService):
    def __init__(self):
        super().__init__()
        self.roster = super().roster_payload()
        self.roster["friends"].append({
            "name": "bob", "minecraft_username": "Bob", "online": False})
        self.roster.update(requests_in=["carol"], requests_out=["dave"])

    def roster_payload(self):
        return deepcopy(self.roster)

    def peer_metadata(self, name):
        return {"minecraft_username": name.title()}


def closure(function):
    return dict(zip(function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__)))


with tempfile.TemporaryDirectory() as directory:
    picture = Path(directory) / "profile.png"
    picture.write_bytes(b"uploaded profile picture")
    sources = {name: base64.b64encode(name.encode()).decode("ascii")
               for name in ("Alice", "Bob", "Carol", "Dave", "Steve")}
    page = FakePage()
    service = RosterService()
    with (patch.object(chat.threading.Thread, "start"),
          patch.object(chat._faces, "get_face_b64", side_effect=sources.get),
          patch.object(chat._profile, "get_profile_picture_path", return_value=str(picture)) as pfp,
          patch.object(thread_safe_ui, "refresh")):
        root, refresh = chat.build_chat_tab(
            page, {"username": "Steve"}, {}, service,
            section_label=section_label, **THEME)
        tick = closure(refresh)["_tick"]
        render = closure(tick)["_render_roster"]
        scope = closure(render)
        rebuild_friends = scope["_rebuild_friends"]
        friends_scope = closure(rebuild_friends)
        friends_list = friends_scope["friends_col"]
        requests_list = closure(scope["_rebuild_requests"])["requests_col"]
        identity = closure(closure(tick)["_apply_identity"])
        you_avatar = identity["you_avatar"]
        header_avatar = closure(scope["_refresh_header"])["header_avatar"]

        with patch("builtins.open", wraps=open) as reads:
            refresh()
            service.roster["connected"] = False
            refresh()
            service.roster["connected"] = True
            refresh()
            check("polling an unchanged self PFP never reopens the file", reads.call_count == 0)

        friend_rows = tuple(friends_list.controls)
        request_rows = tuple(requests_list.controls)
        avatars = tuple(row.content.controls[0].content for row in friend_rows + request_rows)
        self_image = you_avatar.content
        friend_rows[0].on_click(SimpleNamespace(control=friend_rows[0]))
        header_image = header_avatar.content
        check("selecting a conversation retains roster rows and avatars",
              tuple(friends_list.controls) == friend_rows
              and all(row.content.controls[0].content is image
                      for row, image in zip(friend_rows + request_rows, avatars)))
        check("avatars use gapless playback with separate header and roster controls",
              all(image.gapless_playback for image in avatars + (self_image, header_image))
              and header_image is not avatars[0])

        encode = configure_encode_object_for_msgpack(BaseControl)
        initial, added, removed = ObjectPatch.from_diff(None, root, BaseControl)
        msgpack.packb(initial.to_message(), default=encode)
        service.roster["friends"][0].update(
            online=False, unread=102, last_text="new message", last_ts=1000)
        refresh()
        changes, added, removed = ObjectPatch.from_diff(root, root, BaseControl)
        encoded = msgpack.packb(changes.to_message(), default=encode)
        check("presence and unread updates neither remount nor retransmit PFPs",
              not added and not removed and b"src" not in encoded)
        check("presence updates retain header and roster images",
              header_avatar.content is header_image
              and friend_rows[0].content.controls[0].content is avatars[0])
        check("roster labels and capped unread badge update in place",
              friend_rows[0].content.controls[1].controls[2].value == "new message"
              and friend_rows[0].content.controls[2].controls[1].content.value == "99+")
        check("friend and request rows survive unrelated roster changes",
              tuple(friends_list.controls) == friend_rows
              and tuple(requests_list.controls) == request_rows)

        sources["Alice"] = base64.b64encode(b"changed face").decode("ascii")
        refresh()
        check("a real face change updates src without replacing the image",
              friend_rows[0].content.controls[0].content is avatars[0]
              and avatars[0].src == sources["Alice"]
              and header_avatar.content is header_image
              and header_image.src == sources["Alice"])
        sources["Carol"] = base64.b64encode(b"changed request face").decode("ascii")
        refresh()
        check("request face changes update the existing avatar",
              request_rows[0].content.controls[0].content is avatars[2]
              and avatars[2].src == sources["Carol"])

        service.roster["friends"][1]["minecraft_username"] = "Bobby"
        sources["Bobby"] = base64.b64encode(b"renamed face").decode("ascii")
        refresh()
        check("renaming a friend retains the row and updates their face",
              friends_list.controls[1] is friend_rows[1]
              and friend_rows[1].content.controls[1].controls[0].value == "Bobby"
              and friend_rows[1].content.controls[0].content is avatars[1]
              and avatars[1].src == sources["Bobby"])

        friend_rows[1].on_click(SimpleNamespace(control=friend_rows[1]))
        check("switching conversations reuses the header image",
              header_avatar.content is header_image
              and header_image.src == sources["Bobby"])

        query = friends_scope["find_field"]
        query.value = "alice"
        query.on_change(SimpleNamespace(control=query))
        query.value = ""
        query.on_change(SimpleNamespace(control=query))
        check("filtering restores cached friend rows", tuple(friends_list.controls) == friend_rows)

        picture.write_bytes(b"new uploaded profile picture")
        refresh()
        check("replacing the self PFP is detected at the same path",
              you_avatar.content is self_image
              and self_image.src == base64.b64encode(picture.read_bytes()).decode("ascii"))
        pfp.return_value = None
        refresh()
        check("removing the self PFP restores the skin face in place",
              you_avatar.content is self_image and self_image.src == sources["Steve"])
        sources["Steve"] = None
        refresh()
        check("missing self picture and face show initials", isinstance(you_avatar.content, ft.Text))
        sources["Steve"] = base64.b64encode(b"late self face").decode("ascii")
        refresh()
        check("a late-downloaded face replaces initials", isinstance(you_avatar.content, ft.Image))

        service.roster["friends"].pop()
        service.roster.update(requests_in=[], requests_out=[])
        refresh()
        check("removed peers and requests leave no cached rows",
              set(friends_scope["_friend_rows"]) == {"alice"}
              and not closure(scope["_rebuild_requests"])["_request_rows"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

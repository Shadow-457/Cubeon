#!/usr/bin/env python3
"""
Local OS notifications (Phase 7) - the module, the toggles, the call sites.

    python3 tools/test_osnotify.py

Everything is offline: no toast is ever shown, no subprocess is ever spawned,
no socket is ever opened. The platform notifier is a fake `_send`.
"""
import os
import sys
import xml.etree.ElementTree as ET

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


import _sandbox_home  # noqa: E402

_sandbox_home.isolate()

from cubeon import osnotify  # noqa: E402

print("\n1. the seven kinds are the seven kinds")

check("7 kinds", len(osnotify.KINDS) == 7, str(len(osnotify.KINDS)))
check("the install kinds are all there",
      {k for k, *_ in osnotify.KINDS} ==
      {"instance", "mod", "modpack", "resourcepack", "texturepack",
       "friend", "update"})
_keys = [key for _k, key, _l, _s in osnotify.KINDS]
check("config keys are unique", len(set(_keys)) == len(_keys), str(_keys))
check("every kind has a label and a subtitle",
      all(label and sub for _k, _key, label, sub in osnotify.KINDS))

print("\n2. the per-kind switch")

check("a missing key defaults to ON", osnotify.enabled("mod", {}) is True)
check("an explicit False turns it off",
      osnotify.enabled("mod", {"notify_mod": False}) is False)
check("an explicit True turns it on",
      osnotify.enabled("mod", {"notify_mod": True}) is True)
check("the switches are independent (mod off, instands on)",
      osnotify.enabled("mod", {"notify_mod": False}) is False
      and osnotify.enabled("instance", {"notify_mod": False}) is True)
check("an unknown kind is never enabled", osnotify.enabled("nope", {}) is False)
os.environ["CUBEON_OSNOTIFY_OFF"] = "1"
check("CUBEON_OSNOTIFY_OFF=1 disables everything",
      osnotify.enabled("mod", {"notify_mod": True}) is False)
check("...including the backend", osnotify.backend_name() == "")
check("...so notify() reports nothing queued",
      osnotify.notify("mod", "x", "y", force=True) is False)
del os.environ["CUBEON_OSNOTIFY_OFF"]

print("\n3. the throttle collapses duplicates, and only duplicates")

osnotify._recent.clear()
check("the first one goes", osnotify._throttled("mod", "A", now=100.0) is False)
check("the same one immediately after does not",
      osnotify._throttled("mod", "A", now=100.1) is True)
check("a different title is not collapsed",
      osnotify._throttled("mod", "B", now=100.1) is False)
check("a different kind is not collapsed",
      osnotify._throttled("modpack", "A", now=100.1) is False)
check("after the gap it goes again",
      osnotify._throttled("mod", "A", now=100.0 + osnotify._MIN_GAP + 0.01) is False)
osnotify._recent.clear()

print("\n4. notify(): the gate before the toast")


class _InlineThread:
    def __init__(self, target=None, name=None, daemon=None):
        self._target = target
        self.name = name

    def start(self):
        self._target()


sent = []
_saved_send = osnotify._send
_saved_backend = osnotify.backend_name
_saved_which = osnotify.shutil.which
try:
    osnotify._send = lambda title, body: sent.append((title, body)) or True
    osnotify.shutil.which = lambda _name: "/usr/bin/notify-send"

    osnotify._recent.clear()
    check("a disabled kind sends nothing",
          osnotify.notify("mod", "A", "B", cfg={"notify_mod": False},
                          thread_factory=_InlineThread) is False
          and not sent)
    check("an enabled kind DOES send (and reports queued)",
          osnotify.notify("mod", "A", "B", cfg={"notify_mod": True},
                          thread_factory=_InlineThread) is True)
    check("the title and body reached the backend",
          sent == [("A", "B")], str(sent))

    osnotify._recent.clear()
    osnotify.notify("mod", "C", "D", cfg={"notify_mod": False}, force=True,
                    thread_factory=_InlineThread)
    check("force=True ignores the toggle (the Settings test button needs this)",
          sent[-1] == ("C", "D"), str(sent))

    osnotify._recent.clear()
    osnotify._send = lambda title, body: sent.append((title, body)) or True
    before = len(sent)
    osnotify.notify("mod", "E", "F", cfg={}, thread_factory=_InlineThread)
    osnotify.notify("mod", "E", "F", cfg={}, thread_factory=_InlineThread)
    check("a duplicate inside the gap is sent once", len(sent) - before == 1,
          f"sent {len(sent) - before}")

    osnotify._recent.clear()
    osnotify.shutil.which = lambda _name: None
    check("with no notifier installed, nothing is queued",
          osnotify.notify("mod", "G", "H", cfg={}, thread_factory=_InlineThread) is False)
    check("an empty title is never sent",
          osnotify.notify("mod", "", "H", cfg={}, force=True,
                          thread_factory=_InlineThread) is False)
finally:
    osnotify._send = _saved_send
    osnotify.backend_name = _saved_backend
    osnotify.shutil.which = _saved_which
    osnotify._recent.clear()

print("\n5. install_finished() is one shape for every finished download")

_body = []
_saved_send = osnotify._send
osnotify.shutil.which = lambda _name: "/usr/bin/notify-send"
osnotify._send = lambda title, body: _body.append((title, body)) or True
try:
    osnotify._recent.clear()
    osnotify.install_finished("modpack", "Cobblemon", cfg={})
    check("names the thing and says it is ready",
          _body and _body[-1][0] == "Cobblemon is ready", str(_body))
    osnotify._recent.clear()
    osnotify.install_finished("mod", "   ", cfg={})
    check("a nameless install still reads as a sentence",
          _body and _body[-1][0] == "Mods is ready", str(_body))
finally:
    osnotify._send = _saved_send
    osnotify.shutil.which = _saved_which
    osnotify._recent.clear()

print("\n6. 'my most-talked-to friend came online'")

check("the highest count wins",
      osnotify.top_friend({"Alex": 3, "Sam": 41, "Jo": 7}) == "Sam")
check("ties break alphabetically, so the answer is stable",
      osnotify.top_friend({"Sam": 9, "alex": 9}) == "alex")
check("no history -> None (not 'everyone')", osnotify.top_friend({}) is None)
check("zero counts are not history",
      osnotify.top_friend({"Alex": 0, "Sam": 0}) is None)
check("junk counts are ignored, not fatal",
      osnotify.top_friend({"Alex": "x", "Sam": None, "Jo": 2}) == "Jo")

_saved_send = osnotify._send
_sent2 = []
osnotify._send = lambda title, body: _sent2.append((title, body)) or True
osnotify.shutil.which = lambda _name: "/usr/bin/notify-send"
try:
    osnotify._recent.clear()
    counts = {"Alex": 3, "Sam": 41}
    check("the top friend notifies",
          osnotify.friend_came_online("Sam", counts, cfg={}) is True)
    check("...and it names them", _sent2[-1][0] == "Sam is online")
    osnotify._recent.clear()
    check("a DIFFERENT friend does not (that is the whole feature)",
          osnotify.friend_came_online("Alex", counts, cfg={}) is False)
    check("matching is case-insensitive",
          osnotify.friend_came_online("sam", counts, cfg={}) is True)
    osnotify._recent.clear()
    check("with no history at all, nobody notifies",
          osnotify.friend_came_online("Sam", {}, cfg={}) is False)
    check("the friend toggle still applies",
          osnotify.friend_came_online("Sam", counts,
                                      cfg={"notify_friend": False}) is False)
finally:
    osnotify._send = _saved_send
    osnotify.shutil.which = _saved_which
    osnotify._recent.clear()

print("\n7. the update ping")

_saved_send = osnotify._send
_sent3 = []
osnotify._send = lambda title, body: _sent3.append((title, body)) or True
osnotify.shutil.which = lambda _name: "/usr/bin/notify-send"
try:
    osnotify._recent.clear()
    check("a new version notifies",
          osnotify.update_available("1.2.3", cfg={}) is True)
    check("...and names the version", "1.2.3" in _sent3[-1][1], str(_sent3))
    osnotify._recent.clear()
    check("an empty version does not",
          osnotify.update_available("", cfg={}) is False)
finally:
    osnotify._send = _saved_send
    osnotify.shutil.which = _saved_which
    osnotify._recent.clear()

print("\n8. the platform payloads are well-formed")

# Exercise the REAL path: _send_powershell escapes, then builds the XML. A
# raw-format test would pass while the shipped code still emitted invalid XML.
_captured = []
_saved_run = osnotify._run
osnotify._run = lambda argv, **kw: _captured.append(argv) or True
try:
    osnotify._send_powershell("A & B <x>", 'D"E')
finally:
    osnotify._run = _saved_run
_ps = _captured[-1][-1] if _captured else ""
check("the PowerShell command was built", bool(_captured), str(_captured))
check("it escapes the title's XML metacharacters",
      "A &amp; B &lt;x&gt;" in _ps, _ps[:160])
_xml = _ps.split("@'", 1)[1].split("'@", 1)[0] if "@'" in _ps else ""
try:
    ET.fromstring(_xml)
    check("...and the toast payload is valid XML", True)
except Exception as err:  # pragma: no cover - only on a real regression
    check("...and the toast payload is valid XML", False, f"{err}: {_xml}")
check("AppleScript escaping handles quotes and backslashes",
      osnotify._as_escape('a"b\\c') == 'a\\"b\\\\c',
      osnotify._as_escape('a"b\\c'))

print("\n8b. a content type maps to a kind that has a switch")

check("mod maps to mod", osnotify.content_kind("mod") == "mod")
check("resourcepack maps to resourcepack",
      osnotify.content_kind("resourcepack") == "resourcepack")
check("shader maps to the texture-pack switch (the launcher has no separate "
      "texture-pack type - a texture pack IS a resource pack)",
      osnotify.content_kind("shader") == "texturepack")
check("every mapped kind has a Settings switch",
      all(osnotify.content_kind(t) in osnotify.KIND_KEYS
          for t in ("mod", "resourcepack", "shader", "")))
check("an unknown content type falls back to mod rather than inventing a kind",
      osnotify.content_kind("wat") == "mod")

print("\n8c. it can never raise, whatever it is handed")

osnotify.shutil.which = lambda _name: "/usr/bin/notify-send"
_hostile = [
    ("a cfg that is not a dict",
     lambda: osnotify.notify("mod", "A", "B", cfg=[1, 2, 3])),
    ("a None cfg value",
     lambda: osnotify.notify("mod", "A", "B", cfg={"notify_mod": None})),
    ("a numeric install name",
     lambda: osnotify.install_finished("mod", 12345, cfg={})),
    ("an object as a friend name",
     lambda: osnotify.friend_came_online(object(), {"x": 1}, cfg={})),
    ("a non-dict counts",
     lambda: osnotify.friend_came_online("a", 7, cfg={})),
    ("junk as a version", lambda: osnotify.update_available(None, cfg={})),
    ("an unknown kind", lambda: osnotify.notify("wat", "A", "B", cfg={})),
]
for _label, _call in _hostile:
    try:
        _call()
        check(f"survives {_label}", True)
    except Exception as _err:  # pragma: no cover - only on a real regression
        check(f"survives {_label}", False, repr(_err))

print("\n9. this module stays LOCAL (the whole point)")


def _fn_body(source, name):
    """The text of a module-level def, up to the next top-level def."""
    start = source.find(f"def {name}(")
    if start < 0:
        return ""
    rest = source[start:]
    nxt = rest.find("\ndef ", 1)
    return rest if nxt < 0 else rest[:nxt]


_src = open(os.path.join(_ROOT, "cubeon", "osnotify.py"), encoding="utf-8").read()
check("no network client is imported",
      not any(word in _src for word in
              ("import socket", "import urllib", "import requests",
               "import http", "urlopen", "websocket")),
      "a local notifier must never open a socket")
check("no server or endpoint constant",
      "https://" not in _src and "http://" not in _src)
check("it never touches the launcher's UI",
      "import flet" not in _src and "page.update" not in _src)
check("the send runs off the calling thread",
      "thread_factory(target=_work" in _src)
check("a missing notifier is a quiet no-op, not an error",
      "if not available():" in _src and "return False" in _src)

print("\n10. the Settings toggles are wired to these kinds")

_settings = open(os.path.join(_ROOT, "ui", "settings_tab.py"), encoding="utf-8").read()
_main = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
check("Settings has a Notifications section",
      '"notifications"' in _settings and "notifications_pane" in _settings,
      "the user asked for a toggle per type")
check("the toggle rows come from osnotify.KINDS, not a copied list",
      "osnotify.KINDS" in _settings)
check("the switches save instantly",
      "save_config" in _settings and "notifications_pane" in _settings)
check("main.py notifies on a finished version install",
      "osnotify" in _main and "install_finished(" in _main)
check("main.py pings for a new Cubeon version",
      "update_available(" in _main)
_mods = open(os.path.join(_ROOT, "ui", "mods_tab.py"), encoding="utf-8").read()
_packs = open(os.path.join(_ROOT, "ui", "modpacks_tab.py"), encoding="utf-8").read()
check("a finished mod install notifies",
      "osnotify" in _mods and "install_finished(" in _mods)
check("a finished modpack install notifies",
      "osnotify" in _packs and "install_finished(" in _packs)
_friends = open(os.path.join(_ROOT, "cubeon", "friends_service.py"),
                encoding="utf-8").read()
check("a friend coming online notifies (most-talked-to only)",
      "friend_came_online(" in _friends)

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("OS-notify test: FAIL")
    sys.exit(1)
print("OS-notify test: PASS")

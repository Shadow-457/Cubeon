"""
Discord Rich Presence for Cubeon - show "Cubeon" on your Discord profile.

Just like TLauncher shows up as a game you're "playing", the launcher tells the
local Discord desktop client what it's doing. Two things are required, and they
live on different sides:

  1. DISCORD'S SIDE (you, once, no code):
     Register an application at https://discord.com/developers/applications,
     then copy its numeric Application ID into the launcher config as
     ``discord_client_id``. Discord only shows an activity for an application
     id it knows about - there is no way to skip this, and no "permission" to
     ask for; you just create the app yourself. Optionally add an image (the
     big icon shown next to the activity) under Rich Presence / Art Assets.

  2. OUR SIDE (code, this module):
     The launcher connects to the LOCAL Discord desktop client over its IPC
     pipe (NOT the internet, NOT a bot token - the Discord app must be running
     on this machine for the activity to appear anywhere) and issues
     SET_ACTIVITY frames via Discord's Local RPC protocol.

Why hand-rolled instead of pypresence: this launcher keeps its runtime tiny and
fully pinned, and every dependency has to be enumerated in the PyInstaller
specs. The protocol is only a few frames, so we speak it directly with the
standard library (socket / ctypes) - no new dependency to pin, no spec churn,
and nothing to break packaging on another machine.

Failure-safety is the whole job: if Discord isn't running, the client id is
empty, or any socket call fails, every method here is a silent no-op. A broken
or missing Rich Presence must never interfere with launching the game.
"""

import json
import os
import struct
import threading
import time

# Discord Local RPC opcodes (must match discord-rpc).
_OP_HANDSHAKE = 0
_OP_FRAME = 1

_HEADER = struct.Struct("<II")  # opcode (uint32 LE) + frame length (uint32 LE)


def _frame(opcode: int, payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return _HEADER.pack(opcode, len(body)) + body


class DiscordPresence:
    """A tiny Discord Local RPC client. Everything is fail-safe: any error at
    any point just stops the activity from being sent - it never raises to the
    caller (the launcher) and never breaks gameplay."""

    def __init__(self, client_id: str, *, enabled: bool = True):
        self.client_id = (client_id or "").strip()
        self.enabled = bool(enabled)
        self._ipc = None            # socket (unix) or ("pipe", handle) on Windows
        self._lock = threading.Lock()
        self._last = {}             # last sent activity, to dedupe no-op updates
        self._stop = threading.Event()
        # Discord may not be running when the launcher starts (or may be
        # restarted mid-session). set_activity only fires on real state changes,
        # so without a retry the presence would stay missing until the next
        # state change. A quiet background thread re-attempts the connection
        # and replays the current activity every few seconds until it sticks.
        if self.enabled and self.client_id:
            t = threading.Thread(target=self._retry_loop, daemon=True)
            t.start()

    def _retry_loop(self) -> None:
        while not self._stop.wait(10.0):
            with self._lock:
                if self._ipc is not None or not self._last:
                    continue  # connected, or nothing to announce yet
                payload = {
                    "cmd": "SET_ACTIVITY",
                    "args": {"pid": os.getpid(), "activity": self._last.get("activity") or {}},
                    "nonce": _nonce(),
                }
                try:
                    if not self._ensure_connected():
                        continue
                    self._write_frame(_OP_FRAME, payload)
                except Exception:
                    self._drop_ipc()

    # ------------------------------------------------------------------
    # Public API - the only things main.py should call.
    # ------------------------------------------------------------------

    def set_activity(self, *, details=None, state=None, start=None, end=None,
                     large_image=None, large_text=None,
                     small_image=None, small_text=None,
                     buttons=None) -> None:
        """Publish a Rich Presence activity. Any field may be omitted (empty
        fields are dropped, as Discord rejects clutter). Thread-safe; a no-op if
        the feature is off or Discord isn't reachable."""
        activity = {}
        if details:
            activity["details"] = str(details)[:128]
        if state:
            activity["state"] = str(state)[:128]
        if start is not None:
            activity.setdefault("timestamps", {})["start"] = int(start)
        if end is not None:
            activity.setdefault("timestamps", {})["end"] = int(end)
        assets = {}
        if large_image:
            assets["large_image"] = str(large_image)
        if large_text:
            assets["large_text"] = str(large_text)
        if small_image:
            assets["small_image"] = str(small_image)
        if small_text:
            assets["small_text"] = str(small_text)
        if assets:
            activity["assets"] = assets
        if buttons:
            cleaned = [b for b in buttons
                       if isinstance(b, dict) and b.get("label") and b.get("url")]
            if cleaned:
                activity["buttons"] = cleaned[:2]  # Discord caps at 2 buttons

        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": _nonce(),
        }
        self._memoize_and_send("activity", activity, payload)

    def clear(self) -> None:
        """Removes Cubeon's activity from the profile (empty activity, per the
        Discord spec). Safe to call when the launcher window closes or when a
        disconnected/exited state should show nothing."""
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": {}},
            "nonce": _nonce(),
        }
        self._memoize_and_send("activity", None, payload)

    def close(self) -> None:
        """Best-effort clear + drop the socket. Idempotent."""
        with self._lock:
            try:
                self.clear()
            finally:
                self._drop_ipc()

    # ------------------------------------------------------------------
    # Internal plumbing.
    # ------------------------------------------------------------------

    def _memoize_and_send(self, key, value, payload) -> None:
        if not self.enabled or not self.client_id:
            return
        with self._lock:
            if self._last.get(key) == value and self._ipc is not None:
                return  # nothing changed - don't spam Discord every call
            # Remember the desired state even if the send fails, so the
            # background retry loop can replay it once Discord appears.
            self._last[key] = value
            try:
                if not self._ensure_connected():
                    return
                self._write_frame(_OP_FRAME, payload)
            except Exception:
                self._drop_ipc()

    def _ensure_connected(self) -> bool:
        if self._ipc is not None:
            return True
        if os.name == "nt":
            return self._connect_windows_pipe() is not None
        for path in _unix_ipc_paths():
            try:
                import socket
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect(path)
                self._ipc = s
                break
            except OSError:
                continue
        if self._ipc is None:
            return False
        try:
            self._write_frame(_OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
            return True
        except Exception:
            self._drop_ipc()
            return False

    def _connect_windows_pipe(self):
        try:
            import ctypes
            from ctypes import wintypes

            PIPE_PATH = r"\\?\pipe\discord-ipc-0"
            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_EXISTING = 3
            ERROR_PIPE_BUSY = 231

            kernel32 = ctypes.windll.kernel32
            for _ in range(50):
                handle = kernel32.CreateFileW(
                    PIPE_PATH,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None)
                INVALID = ctypes.c_void_p(-1).value
                if handle and handle != INVALID:
                    self._ipc = ("pipe", handle)
                    try:
                        self._write_frame(_OP_HANDSHAKE,
                                          {"v": 1, "client_id": self.client_id})
                    except Exception:
                        self._drop_ipc()
                        return None
                    return self._ipc
                err = ctypes.get_last_error()
                if err == ERROR_PIPE_BUSY:
                    time.sleep(0.05)
                    continue
                return None
        except Exception:
            return None
        return None

    def _write_frame(self, opcode: int, payload: dict) -> None:
        data = _frame(opcode, payload)
        if isinstance(self._ipc, tuple):
            self._write_pipe(data)
        else:
            self._ipc.sendall(data)
            try:
                self._ipc.setblocking(False)
                while self._ipc.recv(4096):
                    pass
            except Exception:
                pass

    def _write_pipe(self, data: bytes) -> None:
        import ctypes

        written = ctypes.c_ulong(0)
        buf = ctypes.create_string_buffer(data)
        handle = self._ipc[1]
        ok = ctypes.windll.kernel32.WriteFile(
            handle, buf, len(data), ctypes.byref(written), None)
        if not ok:
            raise OSError("WriteFile failed for Discord pipe")

    def _drop_ipc(self) -> None:
        if not self._ipc:
            return
        try:
            if isinstance(self._ipc, tuple):
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._ipc[1])
            else:
                self._ipc.close()
        except Exception:
            pass
        self._ipc = None


def _nonce() -> str:
    return "cubeon-" + str(int(time.time() * 1000)) + "-" + str(id(object()))


def _unix_ipc_paths():
    candidates = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(os.path.join(runtime, "discord-ipc-0"))
    tmp = os.environ.get("TMPDIR") or "/tmp"
    candidates.append(os.path.join(tmp, "discord-ipc-0"))
    try:
        candidates.append(f"/run/user/{os.getuid()}/discord-ipc-0")
    except (AttributeError, OSError):
        pass
    return candidates
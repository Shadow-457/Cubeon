"""
Gamepad support for Cubeon - detect a plugged-in controller and let it drive
the launcher.

No new dependency: Linux exposes joysticks as /dev/input/jsN with a tiny
binary event protocol (32 bytes: time, value, type, number), which we read
directly with the standard library - the same "keep the runtime tiny" spirit
as discord_rpc.py. Button semantics follow the Linux gamepad standard mapping
that xpad / xpadneo / HID quirks all produce, so one mapping covers Xbox,
PlayStation and most third-party pads. Everything is fail-safe: no controller,
no read permission, or a mid-session unplug just updates state - it never
raises into the launcher.
"""

import fcntl
import glob
import os
import struct
import threading
import time

_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80

# struct: time (u32), value (i16), type (u8), number (u8)
_EVENT = struct.Struct("IhBB")

# JSIOCGNAME(len) - ioctl to read the device's human-readable name.
# _IOC(direction=READ(2), type='j'(0x6a), nr=0x13, size=len)
_JSIOCGNAME = lambda n: (2 << 30) | (n << 16) | (0x6A << 8) | 0x13

_BUTTON_NAMES = {
    0: "a", 1: "b", 2: "x", 3: "y",
    4: "lb", 5: "rb", 6: "lt", 7: "rt",
    8: "select", 9: "start", 10: "guide",
    11: "l3", 12: "r3",
}
# xpad/hid-common also use 13..16 for dpad-as-buttons on some drivers.
_BUTTON_NAMES.update({13: "up", 14: "down", 15: "left", 16: "right"})

_HAT_X, _HAT_Y = 16, 17  # ABS_HAT0X / ABS_HAT0Y in the js API


def _device_name(path: str) -> str:
    try:
        import ctypes
        with open(path, "rb") as f:
            buf = ctypes.create_string_buffer(128)
            fcntl.ioctl(f.fileno(), _JSIOCGNAME(128), buf)
            name = buf.value.decode("utf-8", "replace").strip()
            if name:
                return name
    except Exception:
        pass
    return os.path.basename(path)


class ControllerWatcher:
    """Watches /dev/input/js* in a background thread and translates raw
    events into launcher-friendly callbacks:

      on_connect(device_name)    - a gamepad was plugged in / appeared
      on_disconnect(device_name) - it went away
      on_event(button)           - a button was PRESSED (no auto-repeat):
                                   "a", "b", "x", "y", "start", "select",
                                   "lb", "rb", "up", "down", "left", "right"
    """

    def __init__(self, on_event=None, on_connect=None, on_disconnect=None,
                 scan_interval: float = 2.0):
        self.on_event = on_event
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.scan_interval = scan_interval
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._known: dict = {}   # js path -> device name
        self._open: dict = {}    # js path -> file object
        self.current_name = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="controller-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_connected(self) -> bool:
        return bool(self._open)

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(self.scan_interval):
            try:
                self._scan()
            except Exception:
                pass

    def _scan(self) -> None:
        present = {p: os.path.basename(p) for p in glob.glob("/dev/input/js*")}
        with self._lock:
            for path in list(self._open):
                if path not in present:
                    self._close(path)
            for path in sorted(present):
                if path in self._open:
                    continue
                name = _device_name(path)
                try:
                    f = open(path, "rb", buffering=0)
                    os.set_blocking(f.fileno(), False)
                except OSError:
                    continue
                self._open[path] = f
                self._known[path] = name
                self.current_name = name
                if self.on_connect:
                    try:
                        self.on_connect(name)
                    except Exception:
                        pass
                threading.Thread(target=self._reader, args=(path,), daemon=True).start()

    def _close(self, path: str) -> None:
        f = self._open.pop(path, None)
        name = self._known.pop(path, None)
        try:
            if f:
                f.close()
        except Exception:
            pass
        if self._open:
            self.current_name = next(iter(self._known.values()), None)
        else:
            self.current_name = None
            if name and self.on_disconnect:
                try:
                    self.on_disconnect(name)
                except Exception:
                    pass

    def _reader(self, path: str) -> None:
        f = self._open.get(path)
        if f is None:
            return
        while not self._stop.is_set() and self._open.get(path) is f:
            try:
                data = f.read(_EVENT.size)
            except OSError:
                data = b""
            if data:
                self._dispatch(data)
            elif not os.path.exists(path):
                # The read ended AND the node is gone -> unplugged.
                with self._lock:
                    self._close(path)
                return
            else:
                time.sleep(0.05)

    def _dispatch(self, data: bytes) -> None:
        while len(data) >= _EVENT.size:
            _, value, etype, number = _EVENT.unpack_from(data)
            data = data[_EVENT.size:]
            if etype & _JS_EVENT_INIT:
                continue  # initial state dump, not a real press
            if etype & _JS_EVENT_BUTTON:
                if value != 1:
                    continue  # only presses, not releases
                btn = _BUTTON_NAMES.get(number, f"btn{number}")
            elif etype & _JS_EVENT_AXIS:
                if number == _HAT_X:
                    btn = "right" if value > 0 else ("left" if value < 0 else None)
                elif number == _HAT_Y:
                    btn = "down" if value > 0 else ("up" if value < 0 else None)
                else:
                    continue  # sticks/triggers are noise for menu driving
            else:
                continue
            if btn and self.on_event:
                try:
                    self.on_event(btn)
                except Exception:
                    pass

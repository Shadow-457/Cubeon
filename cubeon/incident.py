"""Crash forensics for the flet desktop client.

WHY THIS MODULE EXISTS (2026-10-18 report)
------------------------------------------
A Linux/KDE user reported Cubeon "crashing"; KDE's Crash Reporting System
showed TWO dialogs for

    ~/.flet/client/flet-desktop-light-0.86.5/flet/flet has encountered a
    fatal error and was closed.

That binary is the FLET CLIENT - the Flutter/GTK window process Cubeon's
Python half talks to - dying to a signal. main.py's ``__main__`` recovery
ladder already HANDLES it (a pre-paint death is retried in-process with
software OpenGL, twice; a mid-session death re-execs the whole launcher,
twice; then it gives up). What did not exist was the EVIDENCE:

  * every message about a crash was a ``print()`` to stdout, which nobody who
    launches Cubeon from a desktop menu ever sees, let alone can send to us;
  * ``setup_logging()`` was only reached from ``main()`` - the flet SESSION
    callback - so a PRE-PAINT crash left *nothing at all* in
    ``~/.cubeon_launcher/cubeon.log``, because ``main()`` never ran.

So the only artifact a crash report could contain was a screenshot. This
module turns the facts already in hand (the client's exit status, whether the
UI painted, whether the software-GL fallback was armed, the session/desktop/
flet versions, and the tail of the client's own output) into ONE greppable
record per session end.

Nothing here decides anything: main.py owns the recovery, this module only
describes what happened, so a bug here can never change recovery behaviour.
Every public function is total - a crash path must not be able to raise.
"""
import logging
import os
import signal

log = logging.getLogger(__name__)

# How many lines of the client's own output are kept for a crash report. The
# client is chatty (GTK/Mesa warnings, OpenGL frame timeouts), so the tail is
# both capped and de-duplicated - see ClientOutputTail.
TAIL_LINES = 25

_SIGNAL_NAMES = {}
for _sig in getattr(signal, "Signals", ()) or ():
    try:
        _SIGNAL_NAMES[int(_sig)] = _sig.name
    except Exception:   # pragma: no cover - platform dependent
        pass


def describe_exit(code) -> str:
    """A support-readable name for a flet client exit status.

    ``0`` is a normal close. A NEGATIVE value is a signal death (-11 SIGSEGV,
    -6 SIGABRT, -9 SIGKILL, ...) and is the only hard evidence that the client
    CRASHED rather than exited. ``None`` means the status could not be
    observed: flet reaps the client itself, so the capture wrapper in
    ``main.py::_capture_flet_client_exit`` has to be installed for us to see
    it, and when it is missing every end looks like a clean close.
    """
    try:
        code = None if code is None else int(code)
    except (TypeError, ValueError):
        return f"{code!r} (unparseable exit status)"
    if code is None:
        return "unobserved"
    if code == 0:
        return "0 (clean exit)"
    if code < 0:
        name = _SIGNAL_NAMES.get(-code)
        if name:
            return f"{code} ({name} - killed by signal)"
        return f"{code} (killed by unknown signal {-code})"
    return f"{code} (nonzero exit)"


def flet_version() -> str:
    """Both halves of flet, for a report. Never raises.

    The CLIENT version matters most - it is the process that crashes - and it
    is a separate download that lives in ``~/.flet/client/``; ``flet`` (the
    Python package) and ``flet_desktop`` can disagree with it after an
    upgrade, which is itself a known source of broken launchers.
    """
    try:
        import flet
        flet_v = str(getattr(flet, "__version__", "?") or "?")
    except Exception:
        flet_v = "?"
    try:
        import flet_desktop
        client = getattr(flet_desktop, "version", None)
        # flet_desktop.version is a MODULE (0.86+: ``version.version``).
        client_v = str(getattr(client, "version", None)
                       or getattr(client, "__version__", None)
                       or (client if isinstance(client, str) else "?") or "?")
    except Exception:
        client_v = "?"
    return f"flet={flet_v} client={client_v}"


def environment_facts(env=None) -> str:
    """The environment facts that decide which crash you are looking at."""
    env = os.environ if env is None else env

    def _get(key):
        try:
            return env.get(key)
        except Exception:
            return None

    return " ".join([
        f"session={_get('XDG_SESSION_TYPE') or '?'}",
        # KDE/GNOME/... - the flet client's GTK path differs per desktop.
        f"desktop={_get('XDG_CURRENT_DESKTOP') or _get('DESKTOP_SESSION') or '?'}",
        # "on" means this session was ALREADY the software-GL retry: if it
        # still crashed, llvmpipe is not the answer and the driver is not the
        # only suspect.
        f"software_gl={'on' if _get('LIBGL_ALWAYS_SOFTWARE') else 'off'}",
        f"gpu_restarts={_get('CUBEON_GPU_RESTARTS') or '0'}",
        flet_version(),
        client_binary(env),
        gallium_driver(),
    ])


# Where distros keep Mesa's gallium driver library. The 2026-10-18 backtrace
# died inside `libgallium-26.1.6-arch1.1.so`, and on Arch the FILENAME carries
# the Mesa version - which is the entire point of reading it.
_GALLIUM_DIRS = (
    "/usr/lib", "/usr/lib64", "/usr/lib32", "/usr/local/lib", "/usr/lib/dri",
    "/usr/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu/dri",
    "/usr/lib/aarch64-linux-gnu", "/usr/lib/aarch64-linux-gnu/dri",
)


def gallium_driver() -> str:
    """The Mesa gallium driver library on disk - i.e. the object that crashed.

    The 2026-10-18 core dump's backtrace is unambiguous:

        #0 libc (SEGV_ACCERR) <- #1-#7 libgallium-26.1.6-arch1.1.so
        <- #8-#9 libflutter_linux_gtk.so <- #10-#18 libgtk-3
        -> g_signal_emit -> gtk_container_propagate_draw

    So the crash is a Mesa driver fault during a paint, three layers below
    anything Cubeon's Python does. Reporting the library name is what makes
    the ONE fact that matters about a user's graphics stack visible in their
    own log: which Mesa they are actually running. Mesa 26.1.x is the
    regression train this crash belongs to (radeonsi/gallivm; 26.2+ carries
    the fixes), so `gallium=26.1.6-arch1.1` answers "is this the known Mesa
    bug?" in a single grep. Never raises.
    """
    try:
        for directory in _GALLIUM_DIRS:
            try:
                names = os.listdir(directory)
            except OSError:
                continue
            hits = sorted(n for n in names
                          if n == "libgallium_dri.so"
                          or n.startswith("libgallium-"))
            if hits:
                return f"gallium={hits[-1]}"
    except Exception:   # pragma: no cover - defensive
        pass
    return "gallium=?"



def client_binary(env=None) -> str:
    """The flet client binary we are spawning, and whether it looks intact.

    A PARTIAL client unpack is one of the very few client-side faults that is
    ours to fix: flet unpacks ``~/.flet/client/flet-desktop-*`` once and then
    trusts it forever, so an interrupted download (disk full, machine powered
    off, antivirus) leaves a binary that dies on EVERY launch - which looks
    exactly like the driver crash main.py retries around. Reporting the size
    and whether the engine library is present makes the two distinguishable
    from a user's log, without a guessy size threshold.
    """
    env = os.environ if env is None else env
    try:
        home = env.get("HOME") or os.path.expanduser("~")
        root = os.path.join(home, ".flet", "client")
        if not os.path.isdir(root):
            return "client_bin=<no ~/.flet/client>"
        names = sorted(n for n in os.listdir(root)
                       if n.startswith("flet-desktop"))
        if not names:
            return "client_bin=<no flet-desktop client>"
        # Prefer the version flet actually uses; fall back to the newest dir.
        try:
            import flet_desktop
            ver = getattr(getattr(flet_desktop, "version", None), "version",
                          None)
        except Exception:
            ver = None
        pick = None
        if ver:
            pick = next((n for n in reversed(names) if str(ver) in n), None)
        pick = pick or names[-1]
        bundle = os.path.join(root, pick, "flet")
        stub = os.path.join(bundle, "flet")
        stub_exe = os.path.join(bundle, "flet.exe")
        if not (os.path.exists(stub) or os.path.exists(stub_exe)):
            return f"client_bin=<{pick}: NO flet binary>"
        try:
            size = os.path.getsize(stub if os.path.exists(stub) else stub_exe)
        except OSError:
            size = -1
        engine = False
        try:
            for name in os.listdir(os.path.join(bundle, "lib")):
                low = name.lower()
                if low.startswith("libflutter") or low.startswith("flutter_"):
                    engine = True
                    break
        except OSError:
            pass
        return (f"client_bin={pick} ({size} B, "
                f"engine={'yes' if engine else 'NO'})")
    except Exception:
        return "client_bin=?"



def crash_record(kind, code, ui_painted, tail=(), env=None) -> str:
    """One greppable line (plus the client's tail) describing a session end.

    A clean close returns the line alone - the tail of a session that ended
    normally is just noise. For a crash the tail is the whole point: it is
    the client's own last words, and it is where a Mesa/GTK/wayland library
    name or an engine assertion shows up.
    """
    head = (f"flet session ended: kind={kind} "
            f"client_exit={describe_exit(code)} "
            f"ui_painted={bool(ui_painted)} {environment_facts(env)}")
    if kind == "clean_close":
        return head
    lines = []
    try:
        for line in (tail or ()):
            if line is None:
                continue
            line = str(line).rstrip("\n")
            if line:
                lines.append(f"    | {line}")
    except Exception:
        pass
    if lines:
        head += (f"\n  last flet client output ({len(lines)} lines, newest "
                 f"last):\n" + "\n".join(lines))
    return head


def record_session_end(kind, code, ui_painted, tail=(), env=None) -> str:
    """Log one session end, at the level its severity deserves. Never raises."""
    try:
        record = crash_record(kind, code, ui_painted, tail, env)
    except Exception:
        record = f"flet session ended: kind={kind} (record failed)"
    try:
        if kind == "clean_close":
            log.info("%s", record)
        else:
            log.warning("%s", record)
    except Exception:
        pass
    return record


def record_giving_up(attempts, kind="pre_paint_crash") -> None:
    """The recovery ladder is exhausted - say so, once, at ERROR. Never raises.

    Without this the launcher vanished after its last retry and cubeon.log
    ended on a normal-looking line, which is what made the 2026-10-18 report
    unanswerable.
    """
    try:
        log.error(
            "giving up after %s flet client %s(s) - see the 'flet session "
            "ended' records above for the exit status, the environment, the "
            "gallium/Mesa version and the client's own last output. The "
            "client has now died on hardware GL and on both software "
            "rasterizers (llvmpipe, then softpipe), so no environment Cubeon "
            "can set will help: a graphics driver update is the usual fix for "
            "a libgallium crash that reproduces on every attempt",
            attempts, kind)
    except Exception:
        pass


class ClientOutputTail:
    """A bounded, de-duplicated tail of the flet client's own output.

    ``main.py`` already streams the client's stdout+stderr through a filter,
    so the text a crashing client prints is available - but the client is
    chatty, and a dying one repeats a single line hundreds of times (the
    OpenGL frame timeout), which would push the interesting earlier lines
    straight out of a plain ring buffer. Consecutive identical lines
    therefore collapse to one, and the cap holds the context that actually
    names the failing library.
    """

    def __init__(self, maxlen: int = TAIL_LINES):
        try:
            self._maxlen = max(1, int(maxlen))
        except Exception:
            self._maxlen = TAIL_LINES
        self._lines = []

    def add(self, line) -> None:
        """Append one line; blanks and immediate repeats are dropped."""
        try:
            line = str(line).rstrip("\n")
            if not line or (self._lines and self._lines[-1] == line):
                return
            self._lines.append(line)
            if len(self._lines) > self._maxlen:
                del self._lines[:len(self._lines) - self._maxlen]
        except Exception:
            pass

    def clear(self) -> None:
        """Drop everything - a fresh client starts its own output."""
        self._lines = []

    def lines(self) -> list:
        return list(self._lines)

    def __len__(self) -> int:
        return len(self._lines)


def wayland_x11_fallback(env=None) -> dict:
    """Env that pushes the client onto XWayland - or an empty dict.

    The Mesa/libgallium SIGSEGV that main.py retries around is not the only
    way the flet client dies on Linux; the GTK/Wayland path is the other one
    (same binary, same "fatal error" dialog), and "run it under XWayland" is
    the standard workaround for it.

    Deliberately narrow, because changing the display backend has real
    downsides (XWayland fractional scaling is worse than native Wayland):

      * only on a Wayland session - on X11 there is nothing to change;
      * never when the user set ``GDK_BACKEND`` themselves;
      * only when ``DISPLAY`` exists, i.e. an X server is actually reachable.
        Without that XWayland is absent and forcing x11 would fail the client
        start outright instead of merely looking worse.

    main.py applies it ONLY on a retry (the first attempt already crashed), so
    a session that works natively on Wayland keeps working natively.
    """
    env = os.environ if env is None else env
    try:
        if (env.get("XDG_SESSION_TYPE") or "").lower() != "wayland":
            return {}
        if env.get("GDK_BACKEND"):
            return {}
        if not env.get("DISPLAY"):
            return {}
    except Exception:
        return {}
    return {"GDK_BACKEND": "x11"}


def driver_for_attempt(attempts) -> str:
    """Which software rasterizer a retry should use, given the number of client
    attempts that have ALREADY failed (1 = the first retry). Never raises.

    llvmpipe is the fast default - except that it is LLVM-based, and the
    2026-10-18 crash is in the LLVM JIT rasterizer (gallivm) that llvmpipe
    shares with radeonsi's software fallback. That is precisely why the
    software-GL retry could not save the session: the same `libgallium` code
    crashed again under llvmpipe (the module map already recorded the crash as
    "both hw AND llvmpipe" before anyone had a backtrace for it).

    softpipe - Mesa's reference rasterizer - is plain C with no JIT at all, so
    it is a genuinely DIFFERENT code path and the last thing left to try
    before giving up. It is slow, which is why it is only ever the final
    attempt, and why the wedge watchdog's burst-gap rule (which exists to
    spare a merely slow client) matters here.
    """
    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = 1
    return "softpipe" if attempts >= 2 else "llvmpipe"


def retry_environment(attempts, env=None) -> dict:
    """The complete environment for a software-GL retry. Never raises.

    Applied by main.py ONLY when its `use_software_gl` marker exists, i.e.
    after a client has already died - never to a first attempt.
    """
    env = os.environ if env is None else env
    out = {
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "GALLIUM_DRIVER": driver_for_attempt(attempts),
    }
    try:
        out.update(wayland_x11_fallback(env))
    except Exception:   # pragma: no cover - defensive
        pass
    return out

"""Wedge-watchdog: a flet client that renders no frames is detected and killed.

The 2026-09-19 report: "when i click restart cubeon on seasonal update area in
settings cubeon does closes but never opens and i am not able to open cubeon
with the background process", plus dead client windows that kept running.

Root cause traced live on this machine (Mesa 26.1 / AMD Polaris): the flet
desktop client does not always CRASH - it can WEDGE. Window mapped, not one
OpenGL frame rendered, ~180% CPU, and ``ft.run`` never returning. Everything
that can recover a session (tray Open/Quit handling, the software-GL retry
ladder, Settings > "Restart to apply") lives AFTER ``ft.run`` returns, so a
wedged client makes every one of those paths unreachable: the window freezes
on screen forever and the launcher can never be reopened or quit.

main.py's ``_wedge_watchdog`` kills such a client so ``ft.run`` returns and the
existing recovery ladder runs. The client's own log is the evidence: GLib
writes ``** (flet:N): WARNING **: <time>: Timed out waiting for OpenGL frame
...`` on **stderr**.

Locked-in behaviors:

  1. the wedge detector fires on the measured signature (two GL-frame-timeout
     lines ~0.15s apart) - the watchdog kills the wedged client
  2. the fake client here never exits by itself, so any progress proves the
     launcher actually killed it
  3. the classified ladder takes over: "client died before showing the window
     (attempt 1)" -> software-GL retry
  4. the detector keeps working on the retry clients too (attempt 2)
  5. the ladder TERMINATES ("giving up") instead of looping forever
  6. no client process is left behind (no ghost window)
  7. capture is stream-agnostic: the fake logs to stderr like the real client,
     and main.py merges stdout+stderr into one pipe so a client logging to
     either fd can never silently defeat the counter. (The first version of
     this test proved NOTHING because its fake printed to stdout while the
     wrapper piped only stderr - the counter never moved.)

Run:  python3 tools/test_wedge_watchdog.py
"""
import os
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sandbox = tempfile.mkdtemp(prefix="cubeon-wedge-test-")
home = os.path.join(sandbox, "home")
game = os.path.join(sandbox, "game")
os.makedirs(home, exist_ok=True)
os.makedirs(game, exist_ok=True)
fake = os.path.join(sandbox, "fake_wedge_client.py")
driver = os.path.join(sandbox, "driver.py")

with open(fake, "w", encoding="utf-8") as f:
    f.write(textwrap.dedent('''
        """A wedged flet client: GL-frame timeouts, then alive and silent.

        Measured real shape (rt2.log pid 29728): TWO GLib timeout lines
        ~0.15s apart on stderr, then silence forever while the process
        stays alive. The long sleep is deliberate - this client NEVER exits
        on its own, so any progress in the launcher proves a real kill.
        """
        import os, sys, time
        for _ in range(2):
            sys.stderr.write(
                "** (flet:%d): WARNING **: Timed out waiting for OpenGL "
                "frame of size 1280x720 (have 1x1)\\n" % os.getpid())
            sys.stderr.flush()
            time.sleep(0.15)
        time.sleep(600)
    '''))

with open(driver, "w", encoding="utf-8") as f:
    f.write(textwrap.dedent('''
        """Runs the REAL main.py with the fake client installed."""
        import os, sys, runpy
        sys.path.insert(0, %(root)r)
        os.environ["CUBEON_GAME_DIR"] = %(game)r
        import cubeon.paths as paths
        paths.CUBEON_HOME = %(home)r
        paths.CONFIG_PATH = os.path.join(%(home)r, "config.json")
        paths.CACHE_DIR = os.path.join(%(home)r, "cache")
        paths.SKINS_DIR = os.path.join(%(home)r, "skins")
        paths.CAPES_DIR = os.path.join(%(home)r, "capes")
        import flet_desktop as fd
        fd.__locate_and_unpack_flet_view = (
            lambda page_url, assets_dir, hidden:
            ([%(py)r, "-u", %(fake)r], os.environ.copy(),
             os.path.join(%(home)r, "client.pid")))
        sys.argv = ["main.py"]
        runpy.run_path(os.path.join(%(root)r, "main.py"), run_name="__main__")
    ''' % {"root": ROOT, "home": home, "game": game, "fake": fake,
           "py": sys.executable}))

env = dict(os.environ)
env["CUBEON_GAME_DIR"] = game
env["PYTHONUNBUFFERED"] = "1"
out = ""
exited = False
try:
    proc = subprocess.run([sys.executable, "-u", driver], capture_output=True,
                          text=True, timeout=180, env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    exited = True
except subprocess.TimeoutExpired as ex:
    out = ((ex.stdout or b"").decode("utf-8", "replace")
           + (ex.stderr or b"").decode("utf-8", "replace"))
except Exception as ex:  # pragma: no cover - defensive
    out = "driver failed to run: %r" % (ex,)

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")
        if extra:
            print(f"       {extra.strip()[:400]}")


print("wedge watchdog")

check("the wedge detector fires on the measured signature",
      "producing no OpenGL frames" in out,
      "the client's GL-frame timeouts were never turned into a kill")
check("the wedged client is killed so ft.run returns",
      "client died before showing the window" in out,
      "the recovery ladder never saw a session end")
check("the ladder retries with software OpenGL (attempt 1)",
      "attempt 1" in out)
check("the detector still fires on the retry client (attempt 2)",
      "attempt 2" in out)
check("the ladder terminates instead of looping forever",
      "giving up" in out)
check("the launcher process exits (no hung session loop)", exited,
      "the driver never returned within 180s")

# No ghost window: the fake clients are the only processes whose command line
# carries this test's fake path.
if os.path.isdir("/proc"):
    left = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        if fake in cmd:
            left.append(entry)
    check("no client process is left behind", not left,
          f"still running: {left}")
else:
    print("  skip no-ghost check (not Linux: no /proc)")

# The capture must stay stream-agnostic (see the docstring) and every spawned
# client must open a fresh judging window.
try:
    with open(os.path.join(ROOT, "main.py"), "r", encoding="utf-8") as fh:
        src = fh.read()
    check("the client's stdout and stderr are merged into one pipe",
          "stderr=asyncio.subprocess.STDOUT" in src,
          "the wedge detector watched a single fd again")
    check("each spawned client opens a fresh judging window",
          "_wedge_arm(proc.pid)" in src)
except OSError as ex:
    check("main.py is readable", False, repr(ex))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
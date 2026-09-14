#!/usr/bin/env python3
"""Launch a second, fully-isolated Cubeon launcher for testing.

The real launcher and a sandbox instance can run AT THE SAME TIME:

  - The friends bridge binds a random 127.0.0.1 port + random token
    (cubeon/local_api.py), so two launchers never collide.
  - Every piece of Cubeon state (identity.json, auth_key.json, config.json,
    skins, capes, window geometry, the friends cache) lives under
    CUBEON_HOME = ~/.cubeon_launcher, derived from Path.home(). Overriding
    HOME therefore gives the sandbox a COMPLETELY FRESH ACCOUNT: new stable
    secret -> new auto-minted name -> new server-assigned 12-digit ID.

That fresh account is the point: to test friends/chat you need two accounts,
so friend the sandbox from your real launcher (or vice versa) by ID and talk
to yourself.

  python3 tools/launch_sandbox.py bot1          # create + launch "bot1"
  python3 tools/launch_sandbox.py --list        # what sandboxes exist, who they are
  python3 tools/launch_sandbox.py bot1 --wipe   # delete bot1's whole state

Game installs (versions/mods) live in ~/.cubeon_minecraft, derived from HOME
too - so by default a sandbox would re-download Minecraft. The tool points
CUBEON_GAME_DIR back at the REAL game dir (shared) unless --isolated-game is
given, so the sandbox can launch the same versions you already have. Sharing
is fine for launcher-chat testing; only two SIMULTANEOUS GAME launches into
the shared dir would clobber each other's mods/ sync.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = Path.home() / ".cubeon_test_sandboxes"
REAL_GAME_DIR = Path.home() / ".cubeon_minecraft"
REAL_HOME = Path.home()


def sandbox_dir(name: str) -> Path:
    return SANDBOX_ROOT / name


def sandbox_env(name: str, *, isolated_game: bool) -> dict:
    env = os.environ.copy()
    home = str(sandbox_dir(name))
    env["HOME"] = home
    env["USERPROFILE"] = home          # Windows-style override, harmless here
    # The user site-packages (~/.local/lib/pythonX.Y/site-packages) is derived
    # from HOME too - and flet lives there. Keep resolving it from the REAL
    # home or the sandbox python dies with ModuleNotFoundError: flet.
    env["PYTHONUSERBASE"] = str(REAL_HOME / ".local")
    if isolated_game:
        env.pop("CUBEON_GAME_DIR", None)   # HOME override already isolates it
    else:
        env["CUBEON_GAME_DIR"] = str(REAL_GAME_DIR)
    return env


def mint_identity(env: dict) -> dict:
    """Pre-mint the sandbox account (auth_key + identity.json) and return it.

    This is exactly what the launcher does on startup; doing it here just lets
    us PRINT the account so the user knows which handle they're about to have.
    Runs in a child process with the sandbox env so this tool's own process
    never touches cubeon modules (keeps --list instant)."""
    code = (
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from cubeon import friends\n"
        "ident = friends.ensure_identity()\n"
        "print(json.dumps({'name': ident.get('name'), 'uid': friends.current_uid()}))\n"
    ) % str(REPO_ROOT)
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=120)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def read_identity(name: str) -> dict:
    p = sandbox_dir(name) / ".cubeon_launcher" / "identity.json"
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def launch(name: str, *, isolated_game: bool) -> int:
    d = sandbox_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    env = sandbox_env(name, isolated_game=isolated_game)

    ident = mint_identity(env)
    print(f"booting sandbox '{name}'")
    if ident.get("name"):
        uid = ident.get("uid") or "(assigned when the Chat tab first connects)"
        print(f"  account: {ident['name']}   ID: {uid}")
        print("  open the Chat tab in this window to get its ID, then add")
        print("  it from your main launcher (or add your main ID from here).")
    else:
        print("  account: could not pre-mint (launcher will mint on startup)")

    log_path = d / "launcher.log"
    log = open(log_path, "ab")
    import time
    log.write(f"\n===== sandbox '{name}' launch at "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')} ====\n".encode())
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "main.py")],
        cwd=str(REPO_ROOT), env=env,
        stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,       # survives the terminal, own process group
    )
    print(f"  pid {proc.pid} - log: {log_path}")
    try:
        Path(d / "pid").write_text(str(proc.pid))
    except OSError:
        pass
    return 0


def cmd_list() -> int:
    if not SANDBOX_ROOT.is_dir():
        print("no sandboxes yet - create one with: "
              "python3 tools/launch_sandbox.py <name>")
        return 0
    any_shown = False
    for d in sorted(SANDBOX_ROOT.iterdir()):
        if not d.is_dir():
            continue
        any_shown = True
        ident = read_identity(d.name)
        name = ident.get("name") or "(never launched)"
        uid = ident.get("uid") or "-"
        print(f"  {d.name:<12} {name:<20} ID {uid}")
    if not any_shown:
        print("no sandboxes yet - create one with: "
              "python3 tools/launch_sandbox.py <name>")
    return 0


def cmd_wipe(name: str) -> int:
    d = sandbox_dir(name)
    if not d.is_dir():
        print(f"no sandbox named '{name}'")
        return 1
    # A still-running instance would keep writing into a wiped dir.
    pid_file = d / "pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"  stopped running instance (pid {pid})")
        except (ValueError, OSError):
            pass
    import shutil
    shutil.rmtree(d)
    print(f"wiped sandbox '{name}'")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Launch an isolated second Cubeon launcher (its own "
                    "account) so you can test friends with yourself.")
    ap.add_argument("name", nargs="?", default=None,
                    help="sandbox instance name (e.g. bot1)")
    ap.add_argument("--list", action="store_true",
                    help="list sandbox instances and their accounts")
    ap.add_argument("--wipe", metavar="NAME",
                    help="stop and delete a sandbox instance")
    ap.add_argument("--isolated-game", action="store_true",
                    help="give the sandbox its OWN game dir (it will have to "
                         "re-download Minecraft; default shares "
                         "~/.cubeon_minecraft)")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.wipe:
        return cmd_wipe(args.wipe)
    if not args.name:
        ap.print_help()
        return 1
    if not (REPO_ROOT / "main.py").is_file():
        print(f"main.py not found at {REPO_ROOT} - run this from the repo "
              f"checkout", file=sys.stderr)
        return 1
    return launch(args.name, isolated_game=args.isolated_game)


if __name__ == "__main__":
    raise SystemExit(main())


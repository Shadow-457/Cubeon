"""Real 26.3 native world create/save/reopen with an isolated local identity.

Requires the built native executable and prepared local resources. No player
data is opened. Runs a small rendered world and exits through the game's frame
limit, testing the same simulation/save path the launcher will use.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import socket
import time

ROOT = Path(__file__).resolve().parents[1]


def check_companion(process, endpoint):
    deadline = time.monotonic() + 180
    while not endpoint.is_file():
        assert process.poll() is None, "Native game exited before its diagnostic socket"
        assert time.monotonic() < deadline, "Native diagnostic socket timed out"
        time.sleep(.1)
    info = json.loads(endpoint.read_text())
    with socket.create_connection(("127.0.0.1", info["port"]), timeout=20) as sock:
        stream = sock.makefile("rwb")

        def command(line):
            stream.write((line + "\n").encode())
            stream.flush()
            value = json.loads(stream.readline())
            assert not value.get("error"), (line, value)
            return value

        command("auth " + info["token"])
        while True:
            status = command("status")
            if status.get("player") is not None and status.get("server", {}).get("loaded"):
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        command("key key.keyboard.right.shift tap")

        def click(label):
            ui = command("ui")
            node = next((n for n in ui["widgets"] if n.get("label") == label), None)
            assert node, (label, ui)
            command("click " + node["id"])

        painted = time.monotonic() + 20
        while True:
            ui = command("ui")
            if any(n.get("label", "").startswith("FPS:") for n in ui["widgets"]):
                break
            assert time.monotonic() < painted, ui
            time.sleep(.05)
        click("Settings")
        click("Auto sprint: Off")
        click("Friends")
        assert any(n.get("label") == "Add ID" for n in command("ui")["widgets"])
        click("HUD")
        click("Edit HUD")
        assert any(n.get("label") == "Done" for n in command("ui")["widgets"])
        click("Done")
        command("key c down")
        time.sleep(.2)
        command("key c up")
        command("key key.keyboard.left.alt down")
        time.sleep(.2)
        command("key key.keyboard.left.alt up")
        command("key b down")
        assert any(n.get("label") == "wave" for n in command("ui")["widgets"])
        command("key b up")
        print("Native companion menus, HUD editor, saved toggle, zoom, freelook and emote wheel exercised without captures.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "native/cubeon-rust/target/fast/cubeon-rust")
    parser.add_argument("--resources", type=Path, default=ROOT / "build/rust-engine-smoke/resources")
    parser.add_argument("--companion", action="store_true")
    args = parser.parse_args()
    output = ROOT / "build/rust-engine-smoke"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-home-", dir=output) as temp:
        home = Path(temp)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HORIZON_")}
        env["HOME"] = env["USERPROFILE"] = str(home)
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            directory = home / key.lower()
            directory.mkdir(mode=0o700)
            env[key] = str(directory)
        env["CUBEON_RUST_PLAYER_UUID"] = "01234567-89ab-cdef-0123-456789abcdef"
        game = home / "game"
        if args.companion:
            config = game / "config"
            config.mkdir(parents=True)
            (config / "cubeon-client-hud.json").write_text(json.dumps({
                "showFps": True, "showKeys": True, "showArmor": True, "showPing": True,
                "showCps": True, "showEnemyHealth": True,
                "extraOverlays": {key: {"enabled": True} for key in
                    ("clock", "system", "potions", "coordinates", "direction", "biome", "daylight", "combo")},
            }))
        for index, name in enumerate(("SmokeBefore", "SmokeAfter"), 1):
            env["CUBEON_RUST_PLAYER_NAME"] = name
            report = output / f"world-{index}.json"
            command = [str(args.binary.resolve()), "--resources", str(args.resources.resolve()),
                       "--game-dir", str(game), "--home", str(home), "--offscreen",
                       "--world", "Cubeon Native Smoke", "--seed", "7", "--world-frames", "3600" if args.companion and index == 1 else "600",
                       "--render-distance", "2", "--width", "960" if args.companion else "640", "--height", "540" if args.companion else "360",
                       "--smoke-report", str(report)]
            if args.companion and index == 1:
                endpoint = home / "control.json"
                command.extend(["--control-socket", str(endpoint)])
            print(f"Native world run {index}: {name}", flush=True)
            with (output / f"world-{index}.log").open("w") as log:
                process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    if args.companion and index == 1:
                        check_companion(process, endpoint)
                    returncode = process.wait(timeout=240)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=30)
            if returncode:
                raise RuntimeError((output / f"world-{index}.log").read_text()[-8000:])
            assert report.is_file(), "The rendered game did not write its smoke report"
            data = json.loads(report.read_text())
            assert data["error"] is None and data["player"] is not None
            assert data["chunks"] > 0 and data["meshed_sections"] > 0, "Terrain was not rendered"
            print(json.dumps(data, indent=2), flush=True)
            world = game / "saves/Cubeon Native Smoke"
            assert (world / "level.dat").is_file(), "World was not saved"
            assert (world / "players/data/01234567-89ab-cdef-0123-456789abcdef.dat").is_file(), "Stable local identity was not saved"
            assert not (game / "servers.dat").exists(), "An upstream server was added"
            if args.companion:
                assert json.loads((game / "config/cubeon-client-hud.json").read_text())["autoSprint"]
        print("Native 26.3 world saved and reopened with the same identity after rename.", flush=True)


if __name__ == "__main__":
    main()

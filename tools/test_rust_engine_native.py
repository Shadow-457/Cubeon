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

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "native/cubeon-rust/target/fast/cubeon-rust")
    parser.add_argument("--resources", type=Path, default=ROOT / "build/rust-engine-smoke/resources")
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
        for index, name in enumerate(("SmokeBefore", "SmokeAfter"), 1):
            env["CUBEON_RUST_PLAYER_NAME"] = name
            report = output / f"world-{index}.json"
            command = [str(args.binary.resolve()), "--resources", str(args.resources.resolve()),
                       "--game-dir", str(game), "--home", str(home), "--offscreen",
                       "--world", "Cubeon Native Smoke", "--seed", "7", "--world-frames", "600",
                       "--render-distance", "2", "--width", "640", "--height", "360",
                       "--smoke-report", str(report)]
            print(f"Native world run {index}: {name}", flush=True)
            with (output / f"world-{index}.log").open("w") as log:
                result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
            if result.returncode:
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
        print("Native 26.3 world saved and reopened with the same identity after rename.", flush=True)


if __name__ == "__main__":
    main()

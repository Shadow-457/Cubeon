"""Run the frozen launcher on a pre-AVX CPU before publishing Linux artifacts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def check(executable, *, require_emulation=False):
    binary = str(Path(executable).resolve(strict=True))
    emulator = shutil.which("qemu-x86_64")
    if require_emulation and not emulator:
        raise RuntimeError("qemu-x86_64 is required for the Linux release CPU check")
    command = ([emulator, "-cpu", "Nehalem", binary] if emulator else [binary])
    command.append("--cubeon-runtime-check")
    with tempfile.TemporaryDirectory(prefix="cubeon-runtime-check-") as folder:
        env = dict(os.environ)
        # Probe has no user-data operations; isolate accidental future imports.
        env.update(HOME=folder, CUBEON_GAME_DIR=str(Path(folder) / "game"),
                   XDG_CONFIG_HOME=str(Path(folder) / "config"),
                   XDG_CACHE_HOME=str(Path(folder) / "cache"))
        for name in list(env):
            if name.startswith(("_PYI_", "PYTHON")):
                env.pop(name)
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Packaged runtime failed the CPU check (exit {result.returncode}):\n"
                           f"{result.stderr[-3000:]}\n{result.stdout[-1000:]}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if payload.get("status") != "ok" or payload.get("frozen") is not True:
        raise RuntimeError("The packaged executable did not complete its runtime check")
    print(f"Packaged runtime passed ({'Nehalem CPU emulation' if emulator else 'host CPU'}; Python {payload['python']})")


if __name__ == "__main__":
    check(sys.argv[1], require_emulation=os.environ.get("CUBEON_REQUIRE_CPU_CHECK") == "1")

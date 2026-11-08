"""Stage launcher assets without the on-demand server-sharing plugin."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


def make_runtime_assets(repo: str | Path) -> Path:
    source = Path(repo).resolve() / "assets"
    target = Path(tempfile.mkdtemp(prefix="cubeon-runtime-assets-"))

    def exclude(directory, names):
        return ["connect-spigot.jar"] if Path(directory) == source / "jars" else []

    try:
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=exclude)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


if __name__ == "__main__":
    print(make_runtime_assets(Path(__file__).resolve().parents[1]))

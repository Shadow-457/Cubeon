"""Create the assets directory used by a public/no-Friends build."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def make_public_assets(repo: str) -> Path:
    root = Path(repo)
    source = root / "assets"
    target = Path(tempfile.mkdtemp(prefix="cubeon-public-assets-"))
    shutil.copytree(source, target, dirs_exist_ok=True)
    shutil.rmtree(target / "jars", ignore_errors=True)
    (target / "cubeon_no_friends").write_text(
        "This is a public Cubeon build without the Friends feature.\n",
        encoding="utf-8",
    )
    return target

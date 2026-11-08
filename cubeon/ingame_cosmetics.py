"""Launcher-owned Back/Shoulder choices for the authenticated game wardrobe."""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from PIL import Image

from . import cosmetics, paths

PAGE_SIZE = 12
NONE = "__none__"
SLOTS = ("back", "shoulder", "aura")


class InGameCosmetics:
    def __init__(self, cfg, state, lock):
        self.cfg, self.state, self._lock = cfg, state, lock
        self._images = {}

    @staticmethod
    def _slot(kind):
        if kind not in SLOTS:
            raise ValueError("Unknown cosmetics library.")
        return kind

    def _entry(self, kind, selected):
        if selected == NONE:
            return None
        item = cosmetics.get(selected)
        if not item or item["slot"] != kind:
            raise ValueError("Choose an item from this cosmetic category.")
        return item

    def _image(self, kind, item):
        key = (kind, item["id"] if item else NONE)
        if key not in self._images:
            image = (cosmetics.render_thumbnail(item, size=(64, 64)) if item else
                     Image.new("RGBA", (64, 64)))
            buf = io.BytesIO()
            image.save(buf, "PNG")
            # Keep only a page plus the equipped item. No unbounded texture cache.
            if len(self._images) >= PAGE_SIZE + 2:
                self._images.clear()
            self._images[key] = {
                "id": key[1], "name": item["name"] if item else "None",
                "model": kind, "slim": False, "hidden": item is None,
                "png": base64.b64encode(buf.getvalue()).decode("ascii"),
            }
        return self._images[key]

    def snapshot(self, offset=0, kind="back"):
        with self._lock:
            self._slot(kind)
            entries = cosmetics.items(kind)
            offset = max(0, min(int(offset), max(0, len(entries) - 1)))
            active = cosmetics.active(self.cfg, kind) or NONE
            return {
                "ok": True, "kind": kind,
                "items": [self._image(kind, None)] +
                         [self._image(kind, item) for item in entries[offset:offset + PAGE_SIZE]],
                "applied": self._image(kind, self._entry(kind, active)),
                "active": active, "offset": offset, "total": len(entries),
                "page_size": PAGE_SIZE, "skin_support": True,
                "cosmetics": cosmetics.selection_payload(self.cfg),
                "username": str(self.cfg.get("username") or "Player")[:16],
            }

    def action(self, body):
        with self._lock:
            kind = self._slot(body.get("kind"))
            operation = body.get("action")
            selected = body.get("id")
            if operation == "apply":
                item = self._entry(kind, selected)
                version = self.state.get("running_version")
                expected = paths.game_dir_for(version, create=False) if version else None
                supplied = body.get("game_dir")
                if (not expected or not isinstance(supplied, str)
                        or os.path.realpath(supplied) != os.path.realpath(expected)):
                    raise ValueError("This game session is no longer active. Open cosmetics from the running game.")
                destination = Path(cosmetics.game_config_path(expected))
                previous = destination.read_bytes() if destination.is_file() else None
                key = f"active_{kind}_item"
                present, old = key in self.cfg, self.cfg.get(key)
                try:
                    cosmetics.set_active(self.cfg, kind, item["id"] if item else None,
                                         game_dir=expected, strict=True)
                except Exception:
                    if present:
                        self.cfg[key] = old
                    else:
                        self.cfg.pop(key, None)
                    current = destination.read_bytes() if destination.is_file() else None
                    if current != previous:
                        if previous is None:
                            destination.unlink(missing_ok=True)
                        else:
                            from .ingame_skins import InGameSkins
                            InGameSkins._write_png(destination, previous)
                    raise
            elif operation != "refresh":
                raise ValueError("Unknown cosmetic action.")
            result = self.snapshot(body.get("offset", 0), kind)
            result["selected"] = selected if operation == "apply" else result["active"]
            return result

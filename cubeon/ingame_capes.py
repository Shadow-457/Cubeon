"""Paged cape actions for the authenticated local Minecraft cosmetics bridge."""
from __future__ import annotations

import base64
import io
import hashlib
import json
import os
from pathlib import Path
import re

from PIL import Image

from . import capes, paths

PAGE_SIZE = 12
NONE = "__none__"


class InGameCapes:
    def __init__(self, cfg, state, lock):
        self.cfg, self.state, self._lock = cfg, state, lock
        self._images = {}

    @staticmethod
    def _safe_id(value):
        return (isinstance(value, str) and value.endswith(".png")
                and not value.startswith(".") and not any(c in value for c in "/\\\x00"))

    def _entries(self):
        return [e for e in capes.list_custom_capes()
                if isinstance(e, dict) and self._safe_id(e.get("filename"))]

    def _entry(self, filename):
        if filename in {"", NONE}:
            return {"filename": filename, "name": "No cape" if filename else "Cubeon Cape"}
        if not self._safe_id(filename):
            raise ValueError("Choose a cape from your library.")
        entry = next((e for e in self._entries() if e["filename"] == filename), None)
        if entry is None:
            raise ValueError("That cape is no longer in your library.")
        return entry

    def _path(self, entry):
        filename = entry.get("filename") or ""
        if filename == NONE:
            return None
        if not filename:
            return Path(capes._DEFAULT_CAPE_PATH).resolve()
        path = Path(capes.get_custom_cape_path(filename))
        if path.is_symlink() or path.resolve().parent != Path(paths.CAPES_DIR).resolve():
            raise ValueError("That cape is not in your cape library.")
        return path

    def _image(self, entry):
        filename = entry.get("filename") or ""
        path = self._path(entry)
        if path is None:
            key = (NONE,)
        else:
            stat = path.stat()
            if stat.st_size > capes.MAX_SOURCE_BYTES:
                raise ValueError("Cape PNG is too large.")
            key = (filename, stat.st_mtime_ns, stat.st_size)
        if key in self._images:
            return self._images[key]
        if path is None:
            image = capes._transparent_cape_sheet()
        else:
            with Image.open(path) as source:
                if (source.format != "PNG" or source.width not in capes._VALID_CAPE_WIDTHS
                        or source.width != source.height * 2):
                    raise ValueError("That cape needs to be imported again.")
                image = source.convert("RGBA").resize((64, 32), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        image.save(buf, "PNG")
        result = {"id": filename, "name": str(entry.get("name") or "Cape")[:80],
                  "model": "cape", "slim": False, "hidden": filename == NONE,
                  "png": base64.b64encode(buf.getvalue()).decode("ascii")}
        if entry.get("animated"):
            gif = Path(capes.get_custom_cape_path(filename) + ".gif")
            if gif.is_symlink() or gif.resolve().parent != Path(paths.CAPES_DIR).resolve():
                raise ValueError("That GIF cape needs to be imported again.")
            result["gif_path"] = str(gif.resolve())
        if len(self._images) >= PAGE_SIZE + 3:
            self._images.clear()
        self._images[key] = result
        return result

    def snapshot(self, offset=0):
        with self._lock:
            entries = self._entries()
            offset = max(0, min(int(offset), max(0, len(entries) - 1)))
            items = [self._image(self._entry("")), self._image(self._entry(NONE))]
            for entry in entries[offset:offset + PAGE_SIZE]:
                try:
                    items.append(self._image(entry))
                except (OSError, ValueError):
                    continue
            active = NONE if self.cfg.get("hide_cubeon_cape") else self.cfg.get("active_cape") or ""
            try:
                entry = self._entry(active)
                applied = dict(self._image(entry))
            except (OSError, ValueError):
                entry = self._entry("")
                applied = dict(self._image(entry))
            # A damaged animation keeps its still fallback available. Explicit
            # Apply validates the animation before changing the saved selection.
            path = self._path(entry)
            if path is not None:
                applied["texture_path"] = str(path.resolve())
                try:
                    animation = self._animation(entry)
                except (OSError, ValueError):
                    animation = None
                if animation:
                    applied["animation"] = animation
            return {"ok": True, "kind": "cape", "items": items, "applied": applied,
                    "active": active, "offset": offset, "total": len(entries),
                    "page_size": PAGE_SIZE, "username": str(self.cfg.get("username") or "Player")[:16],
                    "skin_support": bool(self.cfg.get("csl_enabled", True))}

    def _animation(self, entry):
        filename = entry.get("filename")
        if not filename or filename == NONE:
            return None
        info = capes.animation_info(filename)
        if info is None:
            if entry.get("animated"):
                raise ValueError("That GIF cape needs to be imported again.")
            return None
        path = Path(capes.get_custom_cape_path(filename) + ".frames.png")
        if path.is_symlink() or path.resolve().parent != Path(paths.CAPES_DIR).resolve():
            raise ValueError("That GIF cape needs to be imported again.")
        stat = path.stat()
        if stat.st_size > capes.MAX_SOURCE_BYTES:
            raise ValueError("That GIF cape is too large.")
        with Image.open(path) as atlas:
            if atlas.format != "PNG" or atlas.size != (info["width"], info["height"] * info["count"]):
                raise ValueError("That GIF cape needs to be imported again.")
        key = hashlib.sha256(json.dumps([info, str(path), stat.st_mtime_ns, stat.st_size], sort_keys=True).encode()).hexdigest()
        return {**info, "path": str(path.resolve()), "key": key}

    def live_state(self, game_dir):
        """The worn cape only; the existing mod poller loads changes off-thread."""
        with self._lock:
            version = self.state.get("running_version")
            expected = paths.game_dir_for(version, create=False) if version else None
            if (not expected or not isinstance(game_dir, str)
                    or os.path.realpath(game_dir) != os.path.realpath(expected)
                    or not self.cfg.get("csl_enabled", True)):
                return {"ok": True, "enabled": False, "revision": "disabled"}
            active = NONE if self.cfg.get("hide_cubeon_cape") else self.cfg.get("active_cape") or ""
            # Default LocalSkin files placed by hand retain ownership.
            if not active and (not self.cfg.get("manage_skin_mod", True)
                               or self.cfg.get("csl_synced_cape_name") != self.cfg.get("username")):
                return {"ok": True, "enabled": False, "revision": "unowned"}
            try:
                entry = self._entry(active)
                applied = dict(self._image(entry))
                path = self._path(entry)
                stamp = None
                if path is not None:
                    applied["texture_path"] = str(path.resolve())
                    stat = path.stat()
                    stamp = [stat.st_mtime_ns, stat.st_size]
                    try:
                        animation = self._animation(entry)
                    except (OSError, ValueError):
                        animation = None
                    if animation:
                        applied["animation"] = animation
            except (OSError, ValueError):
                return {"ok": True, "enabled": False, "revision": "missing"}
            key = [expected, active, stamp, applied.get("animation")]
            return {"ok": True, "enabled": True, "applied": applied,
                    "revision": hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()}

    def _apply(self, selected, body):
        entry = self._entry(selected)
        sheet = self._image(entry)
        self._animation(entry)
        if not self.cfg.get("csl_enabled", True):
            raise ValueError("Enable CustomSkinLoader in launcher Settings → Game → In game first.")
        version = self.state.get("running_version")
        expected = paths.game_dir_for(version, create=False) if version else None
        supplied = body.get("game_dir")
        if not expected or not isinstance(supplied, str) or os.path.realpath(supplied) != os.path.realpath(expected):
            raise ValueError("This game session is no longer active. Open cosmetics from the running game.")
        destination = None
        previous = None
        target = Path(expected) / "CustomSkinLoader" / "LocalSkin" / "capes"
        username = str(self.cfg.get("username") or "")
        from .ingame_skins import InGameSkins
        shared_mirrors = {}
        # The normal cape setter mirrors before saving and preserves unowned
        # default files. Snapshot exact bytes rather than trying to undo a
        # failed save by re-running that ownership-sensitive sync.
        for name in {username, str(self.cfg.get("csl_synced_cape_name") or "")}:
            if re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
                mirror = Path(paths.instance_csl_path(paths.CSL_LOCAL_CAPES_DIR)) / (name + ".png")
                shared_mirrors[mirror] = mirror.read_bytes() if mirror.is_file() else None
        if (self.cfg.get("manage_skin_mod", True)
                and re.fullmatch(r"[A-Za-z0-9_]{3,16}", username)
                and os.path.realpath(target) != os.path.realpath(paths.instance_csl_path(paths.CSL_LOCAL_CAPES_DIR))):
            target.mkdir(parents=True, exist_ok=True)
            destination = target / (username + ".png")
            previous = destination.read_bytes() if destination.is_file() else None
            source = self._path(entry)
            data = source.read_bytes() if source is not None else base64.b64decode(sheet["png"])
            InGameSkins._write_png(destination, data)
        old = {key: self.cfg.get(key) for key in ("active_cape", "hide_cubeon_cape", "csl_synced_cape_name")}
        try:
            if selected == NONE:
                capes.set_hide_cubeon_cape(self.cfg, True)
            else:
                capes.set_active_cape(self.cfg, selected or None)
        except Exception:
            self.cfg.update(old)
            for mirror, data in shared_mirrors.items():
                if data is None:
                    mirror.unlink(missing_ok=True)
                else:
                    InGameSkins._write_png(mirror, data)
            if destination is not None:
                if previous is None:
                    destination.unlink(missing_ok=True)
                else:
                    InGameSkins._write_png(destination, previous)
            raise

    def action(self, body):
        with self._lock:
            operation, selected = body.get("action"), str(body.get("id") or "")
            offset = int(body.get("offset", 0))
            if operation == "import":
                path = Path(str(body.get("path") or "")).expanduser()
                if not path.is_file() or path.stat().st_size > capes.MAX_SOURCE_BYTES:
                    raise ValueError("Choose a cape image up to 8 MB.")
                selected = capes.add_custom_cape(str(path), path.stem)["filename"]
                offset = max(0, len(self._entries()) - PAGE_SIZE)
            elif operation == "apply":
                self._apply(selected, body)
            elif operation == "delete":
                self._entry(selected)
                if selected in {"", NONE}:
                    raise ValueError("Built-in cape choices cannot be deleted.")
                if selected == (self.cfg.get("active_cape") or ""):
                    raise ValueError("Confirm another cape before deleting the one you are wearing.")
                capes.delete_custom_cape(selected)
                selected = NONE if self.cfg.get("hide_cubeon_cape") else self.cfg.get("active_cape") or ""
            elif operation != "refresh":
                raise ValueError("Unknown cape action.")
            result = self.snapshot(offset)
            result["selected"] = selected
            return result

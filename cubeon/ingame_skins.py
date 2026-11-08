"""Skin-library actions for the authenticated in-game launcher bridge.

The launcher remains the owner of skin files/configuration. Browsing is paged;
selecting a preview never changes the active skin. Apply targets the running
instance, even when the launcher has selected a different instance meanwhile.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from PIL import Image

from . import paths, skins

PAGE_SIZE = 12
MAX_PNG_BYTES = 2 * 1024 * 1024


class InGameSkins:
    def __init__(self, cfg: dict, state: dict):
        self.cfg = cfg
        self.state = state
        self._lock = threading.RLock()
        self._images = {}  # bounded by the current library page
        from .ingame_capes import InGameCapes
        self.capes = InGameCapes(cfg, state, self._lock)
        from .ingame_cosmetics import InGameCosmetics
        self.cosmetics = InGameCosmetics(cfg, state, self._lock)

    def _entries(self):
        return [entry for entry in skins.list_custom_skins()
                if isinstance(entry, dict) and self._safe_id(entry.get("filename"))]

    @staticmethod
    def _safe_id(value):
        return (isinstance(value, str) and value.endswith(".png")
                and value not in {".", ".."} and not any(c in value for c in "/\\\x00"))

    def _image(self, entry):
        filename = entry.get("filename") or ""
        if filename:
            path = Path(skins.get_custom_skin_path(filename))
            if path.is_symlink() or path.resolve().parent != Path(paths.SKINS_DIR).resolve():
                raise ValueError("That skin is not in your skin library.")
            stat = path.stat()
            if stat.st_size > MAX_PNG_BYTES:
                raise ValueError("Skin PNG is too large.")
            key = (filename, stat.st_mtime_ns, stat.st_size, entry.get("model"))
        else:
            key = ("",)
        cached = self._images.get(key)
        if cached:
            return cached
        if filename:
            with Image.open(path) as image:
                if image.format != "PNG" or image.size not in {(64, 64), (64, 32)}:
                    raise ValueError("That skin needs to be imported again.")
                image = image.convert("RGBA")
                legacy = image.height == 32
                slim = not legacy and (entry.get("model") == "slim" or
                        entry.get("model") not in {"slim", "classic"} and skins._detect_slim_model(image))
                if legacy:
                    image = self._expand_legacy(image)
                buf = io.BytesIO()
                image.save(buf, format="PNG")
        else:
            slim = False
            buf = io.BytesIO()
            skins.default_base_skin().save(buf, format="PNG")
        data = buf.getvalue()
        result = {"id": filename, "name": str(entry.get("name") or "Steve")[:80],
                  "slim": slim, "model": entry.get("model") or "classic",
                  "png": base64.b64encode(data).decode("ascii"),
                  "hash": hashlib.sha256(data).hexdigest()}
        if len(self._images) >= PAGE_SIZE + 2:
            self._images.clear()
        self._images[key] = result
        return result

    @staticmethod
    def _expand_legacy(source):
        """Minecraft's mirrored left-limb conversion, retaining the original head/body."""
        sheet = Image.new("RGBA", (64, 64))
        sheet.paste(source, (0, 0))
        regions = ((4,16,20,48,4,4), (8,16,24,48,4,4),
                   (0,20,24,52,4,12), (4,20,20,52,4,12),
                   (8,20,16,52,4,12), (12,20,28,52,4,12),
                   (44,16,36,48,4,4), (48,16,40,48,4,4),
                   (40,20,40,52,4,12), (44,20,36,52,4,12),
                   (48,20,32,52,4,12), (52,20,44,52,4,12))
        for sx, sy, dx, dy, width, height in regions:
            sheet.paste(source.crop((sx, sy, sx + width, sy + height))
                        .transpose(Image.Transpose.FLIP_LEFT_RIGHT), (dx, dy))
        return sheet

    def snapshot(self, offset=0, kind="skin"):
        with self._lock:
            if kind in {"back", "shoulder", "aura"}:
                result = self.cosmetics.snapshot(offset, kind)
                result["player_skin"] = self.snapshot()["applied"]
                result["player_cape"] = self.capes.snapshot()["applied"]
                return result
            if kind == "cape":
                result = self.capes.snapshot(offset)
                result["player_skin"] = self.snapshot()["applied"]
                return result
            if kind != "skin":
                raise ValueError("Unknown cosmetics library.")
            entries = self._entries()
            offset = max(0, min(int(offset), max(0, len(entries) - 1)))
            items = [self._image({})]
            for entry in entries[offset:offset + PAGE_SIZE]:
                try:
                    items.append(self._image(entry))
                except (OSError, ValueError):
                    # A bad/deleted file must not hide the rest of the library.
                    continue
            active = self.cfg.get("active_skin") or ""
            active_entry = next((e for e in entries if e["filename"] == active), {})
            try:
                applied = self._image(active_entry)
            except (OSError, ValueError):
                applied = self._image({})
            return {"ok": True, "items": items, "active": active,
                    "username": str(self.cfg.get("username") or "Player")[:16],
                    "applied": applied, "offset": offset, "total": len(entries),
                    "page_size": PAGE_SIZE,
                    "skin_support": bool(self.cfg.get("csl_enabled", True))}

    def _entry(self, filename):
        if filename == "":
            return {}
        if not self._safe_id(filename):
            raise ValueError("Choose a skin from your library.")
        entry = next((e for e in self._entries() if e["filename"] == filename), None)
        if entry is None:
            raise ValueError("That skin is no longer in your library.")
        return entry

    def _import(self, path, name=None, model=None):
        src = Path(path).expanduser()
        if src.suffix.lower() != ".png" or not src.is_file() or src.stat().st_size > MAX_PNG_BYTES:
            raise ValueError("Choose a Minecraft skin PNG up to 2 MB.")
        return skins.add_custom_skin(str(src), name or src.stem, model)

    def _lookup(self, username):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", username):
            raise ValueError("Enter a Minecraft username (3–16 letters, numbers or underscores).")
        # Explicitly requested lookup only; no featured-player prefetch or cape download.
        from .net import _do_get
        deadline = time.monotonic() + 24
        def get(url, maximum=128 * 1024):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("Skin lookup timed out. Try again.")
            response = _do_get(url, timeout=min(8, remaining), allow_redirects=False, stream=True)
            try:
                if response.status_code != 200:
                    raise ValueError("Couldn't find that player's skin. Check the name and connection.")
                data = bytearray()
                for chunk in response.iter_content(16384):
                    if len(data) + len(chunk) > maximum or time.monotonic() > deadline:
                        raise ValueError("The skin service returned too much data or timed out.")
                    data.extend(chunk)
                return bytes(data)
            finally:
                response.close()
        import json
        profile = json.loads(get("https://api.mojang.com/users/profiles/minecraft/" + username))
        uuid = profile.get("id", "")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", uuid):
            raise ValueError("The skin service returned an invalid profile.")
        payload = json.loads(get("https://sessionserver.mojang.com/session/minecraft/profile/" + uuid))
        value = next((p.get("value") for p in payload.get("properties", [])
                      if isinstance(p, dict) and p.get("name") == "textures"), "")
        if not isinstance(value, str) or len(value) > 65536:
            raise ValueError("The player has no downloadable skin.")
        texture = json.loads(base64.b64decode(value, validate=True)).get("textures", {}).get("SKIN", {})
        url = texture.get("url", "")
        if not re.fullmatch(r"https?://textures\.minecraft\.net/texture/[0-9a-fA-F]{32,128}", url):
            raise ValueError("The player has no downloadable skin.")
        png = get(url.replace("http://", "https://", 1), MAX_PNG_BYTES)
        fd, temporary = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(png)
            return self._import(temporary, username,
                                "slim" if texture.get("metadata", {}).get("model") == "slim" else "classic")
        finally:
            os.unlink(temporary)

    def action(self, body):
        with self._lock:
            kind = body.get("kind", "skin")
            if kind in {"back", "shoulder", "aura"}:
                result = self.cosmetics.action(body)
                result["player_skin"] = self.snapshot()["applied"]
                result["player_cape"] = self.capes.snapshot()["applied"]
                return result
            if kind == "cape":
                result = self.capes.action(body)
                result["player_skin"] = self.snapshot()["applied"]
                return result
            if kind != "skin":
                raise ValueError("Unknown cosmetics library.")
            operation = body.get("action")
            offset = int(body.get("offset", 0))
            selected = str(body.get("id") or "")
            if operation in {"import", "lookup"}:
                entry = (self._import(str(body.get("path") or "")) if operation == "import"
                         else self._lookup(str(body.get("username") or "").strip()))
                selected = entry["filename"]
                offset = max(0, len(self._entries()) - PAGE_SIZE)
            elif operation == "apply":
                entry = self._entry(selected)
                # Resolve/validate the sheet before changing configuration.
                sheet = self._image(entry)
                if not self.cfg.get("csl_enabled", True):
                    raise ValueError("Enable CustomSkinLoader in launcher Settings → Game → In game first.")
                version = self.state.get("running_version")
                expected = paths.game_dir_for(version, create=False) if version else None
                supplied = body.get("game_dir")
                if not expected or not isinstance(supplied, str) or os.path.realpath(supplied) != os.path.realpath(expected):
                    raise ValueError("This game session is no longer active. Open skins from the running game.")
                # Shared CSL links already receive the normal setter's mirror.
                # A fallback/private CSL folder must be staged before persistence.
                target = Path(expected) / "CustomSkinLoader" / "LocalSkin" / "skins"
                username = str(self.cfg.get("username") or "")
                destination = None
                previous = None
                if (self.cfg.get("manage_skin_mod", True)
                        and re.fullmatch(r"[A-Za-z0-9_]{3,16}", username)
                        and os.path.realpath(target) != os.path.realpath(paths.instance_csl_path(paths.CSL_LOCAL_SKINS_DIR))):
                    target.mkdir(parents=True, exist_ok=True)
                    destination = target / (username + ".png")
                    previous = destination.read_bytes() if destination.is_file() else None
                    self._write_png(destination, base64.b64decode(sheet["png"]))
                # The normal setter persists the same preference as launcher Cosmetics.
                old = self.cfg.get("active_skin")
                try:
                    skins.set_active_skin(self.cfg, selected or None)
                except Exception:
                    self.cfg["active_skin"] = old
                    skins.sync_local_skin_to_csl(self.cfg)
                    if destination is not None:
                        if previous is None:
                            destination.unlink(missing_ok=True)
                        else:
                            self._write_png(destination, previous)
                    raise
            elif operation == "delete":
                self._entry(selected)
                if not selected:
                    raise ValueError("Steve is the default skin and cannot be deleted.")
                if selected == (self.cfg.get("active_skin") or ""):
                    raise ValueError("Confirm another skin before deleting the one you are wearing.")
                skins.delete_custom_skin(selected)
                selected = self.cfg.get("active_skin") or ""
            elif operation == "model":
                self._entry(selected)
                if not selected or not skins.set_skin_model(self.cfg, selected, str(body.get("model") or "auto")):
                    raise ValueError("Choose an uploaded skin to change its arm model.")
            elif operation != "refresh":
                raise ValueError("Unknown skin action.")
            result = self.snapshot(offset)
            result["selected"] = selected
            return result

    @staticmethod
    def _write_png(destination, data):
        fd, temporary = tempfile.mkstemp(prefix=".cubeon-skin-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

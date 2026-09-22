"""
Custom skin uploads - stores user-supplied skin PNGs locally and renders
a real front-view body preview from the actual pixels (no external API).

IMPORTANT: because this launcher uses offline/cracked auth (no Mojang
session), vanilla Minecraft has no server to fetch a custom skin from -
the game always shows the built-in Steve/Alex model for offline players.
Getting an uploaded skin to show up in-game therefore requires the
client-side CustomSkinLoader (CSL) mod, which cubeon/csl.py installs
automatically at launch.

Two separate mechanisms, and the difference matters:

  * LocalSkin (this module) - CSL reads
    .minecraft/CustomSkinLoader/LocalSkin/skins/<USERNAME>.png. Works with
    no network, but per CSL's own docs "LocalSkin won't be seen by others",
    so it only changes what *you* see.
  * The network identity API (this module too) - what makes other Cubeon
    players see each other's *skins*. The Worker
    (worker/cubeon-skins.js) anchors every skin to this machine's persistent
    public_uuid (auth_key.json), while the in-game username is just an
    ephemeral pointer: Username -> UUID -> skin texture. Writes are
    authorized with the machine's private secret_token as a Bearer header -
    the Worker stores only its SHA-256 - so knowing someone's public UUID is
    not enough to hijack their skin. Two calls:
      POST /api/heartbeat  {username, uuid}  -> claims/verifies UUID ownership,
                                              repoints <username> at it
      POST /api/skin       {uuid, model,
                            skin(base64)}    -> publishes the composed sheet
    _publish_skin() below fires both, write-frugally. See
    docs/phase1-skins-capes.md. (That doc now lives under agents/, at
    agents/docs/phase1-skins-capes.md.)

So the LocalSkin sync here still runs - it's what shows a player their OWN
skin instantly and offline, even before any upload lands - and the composed
sheet is ALSO published to the network so friends see it too. The LocalSkin
filename must be exactly <USERNAME>.png or CSL ignores it.

One thing to know if you touch this: writing the file is necessary but not
sufficient. CSL queries Mojang (priority 100) *before* LocalSkin (710), and
Mojang resolves skins by username even for offline players - so without the
ExtraList entry cubeon/csl.py registers, a user whose name matches a real
premium account would silently get that account's skin instead of this file.
"""
import logging

import base64
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import uuid

# `requests` costs ~97ms to import; this module is on the startup path but
# only touches the network when the user browses/downloads. Lazy so the
# window appears sooner - `requests.get(...)` call sites are unchanged.
from .lazy import LazyModule
requests = LazyModule("requests")
from PIL import Image

from .paths import (
    SKINS_DIR, SKINS_META_PATH, CSL_LOCAL_SKINS_DIR, CUBEON_HOME,
)
from .config import save_config, stable_secret, stable_uuid
from . import csl

_VALID_SKIN_SIZES = {(64, 64), (64, 32)}


# --- Base-skin composition ---------------------------------------------------
# The sheet that should currently be in-game: the active custom skin, or a
# built-in Steve-style default so an otherwise-vanilla player still gets the
# shared Cubeon cape via CSL. (This used to live in cubeon/cosmetics.py and
# bake a pixel hat on top; hats were removed - 2026-09-16.)

def _rgba(img, x, y, color):
    img.putpixel((x, y), color)


def _rect(img, x0, y0, x1, y1, color):
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            img.putpixel((xx, yy), color)


def default_base_skin() -> Image.Image:
    """A built-in Steve-style 64x64 skin. Only the head really matters for
    the avatar/face crops, but CSL expects a whole valid sheet, so the body
    is filled in too."""
    s = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    skin = (200, 144, 108, 255)
    skin_shade = (180, 131, 107, 255)
    hair = (59, 42, 26, 255)
    shirt, shirt_shade = (15, 169, 169, 255), (12, 143, 143, 255)
    jeans, shoes = (58, 75, 168, 255), (86, 86, 86, 255)
    white, iris = (255, 255, 255, 255), (82, 61, 137, 255)

    # Head - base faces.
    _rect(s, 8, 8, 16, 16, skin)        # face
    _rect(s, 0, 8, 8, 16, skin)         # right
    _rect(s, 16, 8, 24, 16, skin)       # left
    _rect(s, 24, 8, 32, 16, skin)       # back
    _rect(s, 16, 0, 24, 8, skin_shade)  # chin/underside
    # Hair: top of the head plus a fringe around the upper sides.
    _rect(s, 8, 0, 16, 8, hair)
    for hx in (0, 16, 24):              # right / left / back side faces
        _rect(s, hx, 8, hx + 8, 11, hair)
    _rect(s, 24, 8, 32, 13, hair)       # back of the head is mostly hair
    # Face: eyes with the classic white-outside/purple-inside layout, nose, mouth.
    _rgba(s, 9, 11, white); _rgba(s, 10, 11, iris)
    _rgba(s, 13, 11, iris); _rgba(s, 14, 11, white)
    _rect(s, 11, 12, 13, 13, skin_shade)
    _rect(s, 11, 13, 13, 14, (126, 79, 61, 255))

    # Body: teal shirt, bare arms (classic Steve), jeans with grey shoes.
    _rect(s, 20, 20, 28, 32, shirt)
    _rect(s, 20, 20, 28, 21, shirt_shade)
    for ax, ay in ((44, 20), (36, 52)):
        _rect(s, ax, ay, ax + 4, ay + 12, skin)
        _rect(s, ax, ay + 10, ax + 4, ay + 12, skin_shade)   # hands
    for lx, ly in ((4, 20), (20, 52)):
        _rect(s, lx, ly, lx + 4, ly + 12, jeans)
        _rect(s, lx, ly + 9, lx + 4, ly + 12, shoes)         # shoes
    return s


def _base_skin_for(cfg) -> Image.Image:
    """The active custom skin if there is one on disk, else the built-in
    default."""
    filename = cfg.get("active_skin")
    if filename:
        path = os.path.join(SKINS_DIR, filename)
        if os.path.isfile(path):
            try:
                with Image.open(path) as sheet:
                    return sheet.convert("RGBA")
            except OSError:
                pass
    return default_base_skin()


def compose_skin(cfg) -> Image.Image:
    """The full skin sheet that should currently be in-game: the active
    skin, or the built-in default Steve when none is set."""
    return _base_skin_for(cfg)


# --- Network identity + skin publishing -------------------------------------
# Timeout kept short: publishing runs on a background thread that must never
# outlive interest in it, and a hung upload should die quietly, not linger.
_NET_TIMEOUT = 8.0
_HEARTBEAT_URL = csl.CUBEON_API_BASE + "/api/heartbeat"
_UPLOAD_URL = csl.CUBEON_API_BASE + "/api/skin"
_REPORT_URL = csl.CUBEON_API_BASE + "/report"

# Records the last state we successfully pushed (username + uuid + content
# hash + model + API base). It lives in its OWN file, deliberately NOT in
# config.json: the publish runs on a background thread, and writing config
# from there would race the main thread's save_config(). Its whole job is
# write-frugality - free-tier KV writes are the scarce resource - so this
# marker turns "sync on every launch" into "only push what actually changed":
# a rename costs one heartbeat, a new PNG costs one upload, and an unchanged
# launch costs nothing.
_PUBLISH_STATE_PATH = os.path.join(CUBEON_HOME, "skin_net.json")

# Failure backoff: when the Worker is unreachable or erroring (e.g. free-tier
# KV writes exhausted for the day), don't hammer it on the next sync. The
# cooldown is written into skin_net.json alongside the success state, so it
# survives restarts. One failure = skip for 10 minutes; the state records
# when retrying becomes worthwhile again.
_PUBLISH_FAIL_COOLDOWN = 600.0


def _publish_on_cooldown(state: dict) -> bool:
    """True while a recent publish failure says 'don't try yet'."""
    until = state.get("retry_not_before", 0)
    try:
        return float(until) > time.time()
    except (TypeError, ValueError):
        return False


def _load_skins_meta() -> dict:
    if os.path.exists(SKINS_META_PATH):
        try:
            with open(SKINS_META_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"skins": []}  # list of {"filename", "name", "slim"}


def _save_skins_meta(meta: dict) -> None:
    # Atomic: a crash mid-write used to corrupt skins.json and lose every
    # registered custom skin (the loader falls back to {"skins": []}).
    from .atomicio import write_json
    write_json(SKINS_META_PATH, meta)


def validate_skin_file(path: str) -> tuple[bool, str]:
    """Checks the file is a real PNG with a valid Minecraft skin size."""
    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                return False, "Skin must be a PNG file"
            if img.size not in _VALID_SKIN_SIZES:
                return False, f"Invalid skin size {img.size}, must be 64x64 (or legacy 64x32)"
        return True, ""
    except Exception:
        return False, "Couldn't read that file as an image"


def list_custom_skins() -> list[dict]:
    return _load_skins_meta()["skins"]


def add_custom_skin(src_path: str, display_name: str,
                    model: str | None = None) -> dict:
    """Copies a validated skin PNG and registers its arm model.

    ``model`` is ``"slim"`` for Alex/3px arms, ``"classic"`` for
    Steve/4px arms, or ``None``/``"auto"`` to use the PNG heuristic. The
    explicit values exist because the PNG format itself does not carry the
    player's model choice; edited skins can therefore be impossible to infer
    from transparency alone.
    """
    ok, err = validate_skin_file(src_path)
    if not ok:
        raise ValueError(err)

    requested_model = (model or "auto").strip().lower()
    if requested_model not in {"auto", "slim", "classic"}:
        raise ValueError("Skin arm model must be auto, slim, or classic")
    with Image.open(src_path) as img:
        slim = (requested_model == "slim" or
                (requested_model == "auto" and
                 img.size == (64, 64) and _detect_slim_model(img)))
        normalized = _repair_transparent_base(img, slim=slim)

    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", display_name.strip()) or "skin"
    filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    dest = os.path.join(SKINS_DIR, filename)
    # Copy through the launcher cache directory atomically. CSL and the
    # preview worker can inspect this folder while an upload is finishing; a
    # direct copy exposed half-written PNGs and produced intermittent broken
    # previews/skins.
    tmp = dest + ".uploading"
    try:
        normalized.save(tmp, format="PNG")
        os.replace(tmp, dest)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

    meta = _load_skins_meta()
    entry = {
        "filename": filename,
        "name": display_name.strip() or safe_name,
        "slim": slim,
        # Keep the explicit choice: an edited Alex PNG can have opaque spare
        # arm columns, so re-detecting it later would wrongly turn it classic.
        "model": requested_model,
    }
    meta["skins"].append(entry)
    _save_skins_meta(meta)
    return entry


def _repair_transparent_base(img: Image.Image, *, slim: bool = False) -> Image.Image:
    """Return a valid RGBA sheet with holes removed from base geometry.

    Minecraft permits transparent pixels in the outer hat/jacket layer and in
    the unused fourth columns of slim arms, but not in the required base
    faces. Passing those holes through makes the game render large black gaps
    (especially down the back and outer arm). Fill only the required base
    rectangles from the built-in Steve sheet; preserve every outer-layer and
    slim-reserved pixel exactly. This is a repair, not a crop or resize, so
    uploaded coordinates and model proportions remain intact.
    """
    sheet = img.convert("RGBA")
    if sheet.size not in _VALID_SKIN_SIZES:
        return sheet
    fallback = default_base_skin()
    legacy = sheet.size == (64, 32)
    regions = [
        (0, 0, 32, 16),       # head base faces
        (20, 20, 28, 32),     # torso
        (4, 20, 8, 32),       # right leg
        (44, 20, 47 if slim else 48, 32),  # right arm; slim spare x=47
    ]
    if legacy:
        regions.append((44, 20, 48, 32))
    else:
        regions.extend([
            (20, 52, 24, 64),  # left leg
            (36, 52, 39 if slim else 40, 64),  # left arm; slim spare x=39
        ])
    for x0, y0, x1, y1 in regions:
        for y in range(y0, min(y1, sheet.height)):
            for x in range(x0, min(x1, sheet.width)):
                if sheet.getpixel((x, y))[3] == 0:
                    sheet.putpixel((x, y), fallback.getpixel((x, y)))
    return sheet


def _detect_slim_model(img: Image.Image) -> bool:
    """Detect the Alex/slim model from the reserved fourth arm columns.

    A single probe pixel is not reliable: a classic skin may have a
    transparent elbow, while a malformed/edited slim skin may have one stray
    opaque pixel. The official 64x64 layout reserves the fourth base column
    at x=47 and the fourth left-arm column at x=39; slim skins leave both
    columns transparent for the full 12-pixel arm height. Requiring both
    columns to be clear prevents assigning a 4px/classic skin to a 3px model,
    which is what causes the back/outer arm edge to be clipped in-game.
    """
    try:
        rgba = img.convert("RGBA")
        if rgba.size != (64, 64):
            return False
        reserved = (
            [(47, y) for y in range(20, 32)]
            + [(39, y) for y in range(52, 64)]
        )
        return all(rgba.getpixel(pos)[3] == 0 for pos in reserved)
    except Exception:
        return False


def delete_custom_skin(filename: str) -> None:
    meta = _load_skins_meta()
    meta["skins"] = [s for s in meta["skins"] if s["filename"] != filename]
    _save_skins_meta(meta)
    path = os.path.join(SKINS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)


def get_custom_skin_path(filename: str) -> str:
    return os.path.join(SKINS_DIR, filename)


def set_active_skin(cfg: dict, filename: str | None) -> None:
    cfg["active_skin"] = filename
    # Sync before saving: the sync records which name it wrote under in cfg,
    # and that bookkeeping needs to land in the same save.
    sync_local_skin_to_csl(cfg)
    save_config(cfg)


def set_skin_model(cfg: dict, filename: str, model: str) -> bool:
    """Change an already uploaded skin's arm model without re-uploading it."""
    wanted = (model or "auto").strip().lower()
    if wanted not in {"auto", "slim", "classic"}:
        raise ValueError("Skin arm model must be auto, slim, or classic")
    meta = _load_skins_meta()
    entry = next((s for s in meta.get("skins", [])
                  if s.get("filename") == filename), None)
    if entry is None:
        return False
    entry["model"] = wanted
    if wanted == "slim":
        entry["slim"] = True
    elif wanted == "classic":
        entry["slim"] = False
    else:
        try:
            with Image.open(get_custom_skin_path(filename)) as image:
                entry["slim"] = image.size == (64, 64) and _detect_slim_model(image)
        except OSError:
            entry["slim"] = False
    _save_skins_meta(meta)
    if cfg.get("active_skin") == filename:
        sync_local_skin_to_csl(cfg)
        save_config(cfg)
    return True


def sync_local_skin_to_csl(cfg: dict) -> None:
    """Mirrors the active skin into CustomSkinLoader's LocalSkin folder as
    <USERNAME>.png - the exact path and filename CSL looks for.

    Call this whenever the active skin *or* the username changes: offline
    accounts are keyed entirely off the username, so a rename means CSL is
    looking up a different file.

    Only the local player sees a LocalSkin texture (see this module's
    docstring). Best-effort throughout - a failure here must never block the
    upload flow.
    """
    username = (cfg.get("username") or "").strip()
    filename = cfg.get("active_skin")
    previous = cfg.get("csl_synced_name")
    if not username:
        return

    # Clean up the file we last wrote if the name changed (otherwise a rename
    # leaves <OLDNAME>.png behind) or there's nothing left to show (no skin). Only ever delete a name this launcher recorded writing, so
    # a skin the user dropped into LocalSkin by hand is never clobbered.
    if previous and (previous != username or not filename):
        _remove_local_skin(previous)
        cfg["csl_synced_name"] = None

    # --- LocalSkin mirror: only when there IS custom content to mirror -------
    # With no skin we deliberately write nothing: vanilla Steve
    # stays vanilla locally. The network half below still runs, though -
    # that's what puts the shared Cubeon cape on an otherwise-vanilla player.
    if filename:
        src = get_custom_skin_path(filename) if filename else None
        if src is not None and not os.path.isfile(src):
            src = None
        if src is not None:
            try:
                os.makedirs(CSL_LOCAL_SKINS_DIR, exist_ok=True)
                # The composed sheet is what lands in CSL: the active skin
                # (or the built-in default when none is set).
                sheet = compose_skin(cfg)
                target = os.path.join(CSL_LOCAL_SKINS_DIR, f"{username}.png")
                tmp = target + ".uploading"
                sheet.save(tmp, format="PNG")
                os.replace(tmp, target)
                cfg["csl_synced_name"] = username
            except OSError:
                try:
                    os.remove(os.path.join(CSL_LOCAL_SKINS_DIR,
                                           f"{username}.png.uploading"))
                except OSError:
                    pass

    # CSL's model="auto" is unreliable for edited skins with opaque spare
    # arm columns. Write the active skin's explicit model into Cubeon's own
    # load-list entry before Minecraft starts.
    if filename and cfg.get("manage_skin_mod", True):
        try:
            csl.set_localskin_model(
                "slim" if _active_skin_is_slim(filename) else "default")
        except Exception:
            logging.getLogger(__name__).debug("could not set local skin model", exc_info=True)

    # --- Network identity sync: ALWAYS (with a username) ---------------------
    # Even a vanilla player heartbeats once on first launch and once per
    # rename, because the heartbeat creates pointer:<name> -> <uuid> - and
    # that pointer is what makes serveProfile hand them the shared cape.
    # Without it, default-Steve players would be capeless (and worse,
    # indistinguishable from non-Cubeon players). Gated on the master skin-
    # mod opt-out, best-effort, pushed onto a background thread so a slow
    # request never delays a launch or a click. _publish_skin decides what
    # actually goes over the wire (heartbeat only vs heartbeat + upload).
    if cfg.get("manage_skin_mod", True):
        _publish_skin_async(cfg)


def _remove_local_skin(username: str) -> None:
    try:
        path = os.path.join(CSL_LOCAL_SKINS_DIR, f"{username}.png")
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Network publishing - making OTHER players see this skin
#
# The Worker (worker/cubeon-skins.js) anchors skins to this machine's
# persistent public_uuid, with the username as an ephemeral pointer. Writes
# are Bearer-authorized by stable_secret(); the Worker keeps only its hash,
# so a leaked public UUID alone lets nobody hijack anything.
# ---------------------------------------------------------------------------

def _composed_skin_png(cfg: dict) -> bytes:
    """The current sheet (active skin or default Steve) as PNG bytes - the exact image written to LocalSkin, so friends see what
    the player sees. Always 64x64 or legacy 64x32, which is precisely the
    dimensions the Worker's PNG guard accepts."""
    sheet = compose_skin(cfg)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()


def _compose_face_png(cfg: dict, size: int = 128) -> bytes | None:
    """The head crop of the current sheet (base layer + the sheet's own hat
    layer, alpha-composited) as an upscaled square PNG. This is the avatar the
    Worker serves at /faces/<name>.png (Discord presence, web). Never
    raises; returns None when composition fails so the upload just omits
    the face and the Worker falls back to the full sheet."""
    try:
        sheet = compose_skin(cfg).convert("RGBA")
        legacy = sheet.size == (64, 32)
        face = sheet.crop((8, 8, 16, 16))                     # base head front
        if not legacy:
            face = face.copy()
            face.alpha_composite(sheet.crop((40, 8, 48, 16)))  # hat layer
        face = face.resize((size, size), Image.NEAREST)
        buf = io.BytesIO()
        face.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _active_skin_is_slim(filename: str | None) -> bool:
    """Whether the active skin uses the 3px-arm slim (Alex) model.

    Re-read the PNG instead of trusting only the old metadata. Earlier builds
    could record ``slim=False`` before the model detector was fixed; trusting
    that stale flag made the network upload advertise a classic four-pixel arm
    for an Alex skin even though the image itself was slim.
    """
    if not filename:
        return False
    meta = _load_skins_meta()
    for entry in meta.get("skins", []):
        if entry.get("filename") == filename:
            explicit = entry.get("model")
            if explicit == "slim":
                return True
            if explicit == "classic":
                return False
            try:
                with Image.open(os.path.join(SKINS_DIR, filename)) as img:
                    detected = img.size == (64, 64) and _detect_slim_model(img)
                if bool(entry.get("slim")) != detected:
                    entry["slim"] = detected
                    entry.setdefault("model", "auto")
                    _save_skins_meta(meta)
                return detected
            except (OSError, ValueError):
                return bool(entry.get("slim"))
    return False


def name_contested() -> bool:
    """Whether the last successful heartbeat reported this username is
    ALSO claimed by a different Cubeon identity (name collision). Read by
    the UI to show a warning instead of a silent last-writer-wins mess."""
    return bool(_load_publish_state().get("name_contested"))


def _load_publish_state() -> dict:
    try:
        with open(_PUBLISH_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _save_publish_state(state: dict) -> None:
    # Atomic: losing skin_net.json used to make the next launch re-upload the
    # skin (wasting scarce free-tier KV writes) or, worse, half-write the
    # retry cooldown and the identity half on different passes.
    try:
        from .atomicio import write_json
        write_json(_PUBLISH_STATE_PATH, state)
    except OSError:
        pass


def _record_publish_failure(state: dict) -> None:
    """Note 'don't retry for _PUBLISH_FAIL_COOLDOWN' without touching the
    last-known-good identity fields, then persist. Never raises."""
    state["retry_not_before"] = time.time() + _PUBLISH_FAIL_COOLDOWN
    _save_publish_state(state)


def _publish_skin(cfg: dict) -> None:
    """Pushes identity + skin to the Worker so other players see them.

    Runs on a background thread (see _publish_skin_async), so it owns all its
    own failure handling: it must never raise out of the thread and never block
    longer than _NET_TIMEOUT. Every outcome that isn't a clean success is
    swallowed - the player still sees their own skin locally regardless, so
    there's nothing actionable to surface from here.

    Two calls, each fired only when its inputs changed:
      heartbeat  POST /api/heartbeat - repoints <username> at public_uuid.
                 Needed when the name or uuid differs from the last push.
                 Fires even for a vanilla player: the pointer it creates is
                 what makes serveProfile hand them the shared cape.
      upload     POST /api/skin - publishes the composed sheet against
                 public_uuid. Only ever fired for REAL content (a custom
                 skin or a hat). A default-Steve-no-hat player uploads
                 nothing - that would burn KV writes re-shipping Steve and
                 make serveProfile serve Steve-as-a-skin instead of a clean
                 cape-only profile.

    Both carry Authorization: Bearer <secret_token>. A 403 means this UUID is
    owned by another install's secret - swallowed; LocalSkin still shows this
    user their own skin.
    """
    try:
        username = (cfg.get("username") or "").strip()
        if not username:
            return

        state = _load_publish_state()

        # A recent failure (worker down, KV quota exhausted) means "don't
        # retry for a while" - syncs fire on every launch AND on every
        # username change, so without this a persistent outage turns into
        # a request storm against a Worker that can't serve us anyway.
        if _publish_on_cooldown(state):
            return

        machine_uuid = stable_uuid()
        secret = stable_secret()
        headers = {"Authorization": f"Bearer {secret}"}

        identity_changed = (
            state.get("username") != username
            or state.get("uuid") != machine_uuid
            or state.get("base") != csl.CUBEON_API_BASE
        )

        # Real content only. The sheet is composed (and hashed) lazily, so a
        # vanilla sync costs zero PIL work as well as zero upload bytes.
        has_custom = bool(cfg.get("active_skin"))
        if has_custom:
            png = _composed_skin_png(cfg)
            digest = hashlib.sha256(png).hexdigest()
            model = "slim" if _active_skin_is_slim(cfg.get("active_skin")) else "default"
            skin_changed = (
                state.get("hash") != digest
                or state.get("model") != model
            )
        else:
            skin_changed = False

        if not identity_changed and not skin_changed:
            return

        # 1. Heartbeat first: it claims ownership of the UUID (TOFU) and
        # points the current name at it. The upload route enforces the same
        # ownership check, so on a rename-only sync this one call is all the
        # backend needs.
        if identity_changed:
            try:
                resp = requests.post(
                    _HEARTBEAT_URL,
                    json={"username": username, "uuid": machine_uuid},
                    headers=headers,
                    timeout=_NET_TIMEOUT,
                )
            except requests.RequestException:
                _record_publish_failure(state)  # offline - cool off, retry later
                return
            if resp.status_code != 200:
                # 403 = UUID owned by another secret: retrying can't help
                # either, so it gets the same cooldown. 429/5xx = transient
                # server trouble (429 name_move_cooldown = this identity
                # moved names too recently - honest renames are >1h apart,
                # so spamming or a hijacker gets throttled). Record nothing
                # BUT the cooldown so the next sync (post-cooldown) retries.
                _record_publish_failure(state)
                return
            # The Worker flags when a DIFFERENT identity held this name
            # recently (name collision). Persist it so the UI can warn; it
            # clears on the next uncontested success.
            try:
                contested = bool(resp.json().get("name_contested"))
            except Exception:
                contested = False
            state.update({"username": username, "uuid": machine_uuid,
                          "base": csl.CUBEON_API_BASE,
                          "name_contested": contested})
            state.pop("retry_not_before", None)  # success clears cooldown
            _save_publish_state(state)

        # 2. Then the sheet itself, if it moved. Skipped entirely when only
        # the name changed (the texture under the UUID didn't) and when
        # there's no custom content to ship (never upload default Steve).
        if skin_changed:
            payload = {
                "uuid": machine_uuid,
                "model": model,
                "skin": base64.b64encode(png).decode("ascii"),
            }
            # Companion face avatar: the 8x8 head crop (hat layer included)
            # scaled to 128. The Worker can't crop PNGs, so it's rendered
            # here and rides in the same upload - one request, and the face
            # is content-addressed server-side (same face -> zero extra
            # writes on re-publish).
            face = _compose_face_png(cfg)
            if face:
                payload["face"] = base64.b64encode(face).decode("ascii")
            try:
                resp = requests.post(
                    _UPLOAD_URL, json=payload, headers=headers,
                    timeout=_NET_TIMEOUT,
                )
            except requests.RequestException:
                return  # retried next time the sheet syncs

            if resp.status_code == 200:
                state.update({"hash": digest, "model": model})
                state.pop("retry_not_before", None)  # success clears cooldown
                _save_publish_state(state)
            # A non-200 leaves hash/model unrecorded so the next sync retries;
            # the identity half already saved above stays accurate as-is.
    except Exception:
        # Backstop only. A daemon thread that raised would dump a traceback to
        # the console over a purely cosmetic, best-effort feature - but the
        # failure must not be invisible: log it (file log; console at WARNING).
        logging.getLogger(__name__).warning(
            "skin publish failed (best-effort, will retry on next sync)",
            exc_info=True)


def _publish_skin_async(cfg: dict) -> None:
    """Fire-and-forget _publish_skin on a daemon thread.

    Snapshots cfg first: a shallow copy is a safe point-in-time view here (every
    field the upload reads is an immutable str/None), so the background upload
    can't observe a half-mutated config while the caller goes on to
    save_config()."""
    snapshot = dict(cfg)
    threading.Thread(
        target=_publish_skin, args=(snapshot,),
        name="cubeon-skin-publish", daemon=True,
    ).start()


def report_skin(username: str, reason: str = "") -> bool:
    """Flags another player's published skin for moderation review.

    Synchronous (a deliberate user action with a yes/no outcome to show) but
    still best-effort - returns True only on a confirmed 200. The Worker just
    records the report for a human to review; it never auto-blocks, so this
    can't be weaponized as a remote censor button. See the Worker's
    handleReport()."""
    username = (username or "").strip()
    if not username:
        return False
    payload = {"username": username}
    if reason:
        payload["reason"] = reason
    try:
        resp = requests.post(_REPORT_URL, json=payload, timeout=_NET_TIMEOUT)
    except requests.RequestException:
        return False
    return resp.status_code == 200


def skin_mod_installed(mc_version: str | None, loader: str | None) -> bool:
    """Whether CustomSkinLoader is present in the active mod profile - used so
    the Skin section can tell the user the truth about whether their uploaded
    skin will actually show up in-game, instead of a generic disclaimer every
    time.

    Only CSL counts. SkinLayers3D is deliberately not treated as equivalent:
    it renders the 3D outer layer of a skin that's already loaded, it does not
    load custom skins at all, so accepting it would promise something that
    doesn't happen.
    """
    return csl.is_installed(mc_version, loader)


def render_local_skin_preview(filename: str, out_path: str, scale: int = 8,
                              src_path: str | None = None) -> str:
    """Composites a Minecraft-style full body preview from the uploaded skin.

    Front view, built from the real pixels: head, torso, arms, and legs at
    their actual Minecraft body-part proportions, each with its outer
    ("hat"/jacket/sleeve/pants) layer composited on top - that outer layer is
    what makes a skin with a hood, jacket, or baggy pants read correctly
    instead of showing the bare base layer underneath.

    `src_path` overrides where the sheet is read from (used by the gallery,
    whose skins live outside SKINS_DIR); `filename` is then only a name.
    """
    src = src_path or get_custom_skin_path(filename)
    with Image.open(src) as sheet:
        sheet = sheet.convert("RGBA")
        legacy = sheet.size == (64, 32)
        slim = (not legacy) and _detect_slim_model(sheet)
        arm_w = 3 if slim else 4

        def region(x, y, w, h):
            return sheet.crop((x, y, x + w, y + h))

        def grow(img, factor):
            w, h = img.size
            return img.resize((w * factor, h * factor), Image.NEAREST)

        def stack(base, overlay):
            """Base layer with its outer layer alpha-composited on top."""
            out = base.convert("RGBA")
            out.alpha_composite(overlay.convert("RGBA"))
            return out

        # --- Base layer regions -------------------------------------------------
        head = region(8, 8, 8, 8)
        torso = region(20, 20, 8, 12)
        r_leg = region(4, 20, 4, 12)
        r_arm = region(44, 20, arm_w, 12)
        if legacy:
            l_leg = region(4, 20, 4, 12)
            l_arm = region(44, 20, arm_w, 12)
        else:
            l_leg = region(20, 52, 4, 12)
            # The slim layout keeps the left-arm origin at x=36; its unused
            # fourth column is on the right, just like the right arm's unused
            # column at x=47. Shifting the crop for slim skins drops the real
            # outer edge and was the source of clipped/misaligned arms in the
            # launcher preview.
            l_arm = region(36, 52, arm_w, 12)

        # --- Outer ("hat"/jacket/sleeve/pants) layer regions --------------------
        # On the legacy 64x32 layout there is no second skin layer at all.
        head_o = region(40, 8, 8, 8)
        torso_o = region(20, 36, 8, 12) if not legacy else None
        r_leg_o = region(4, 36, 4, 12) if not legacy else None
        r_arm_o = region(44, 36, arm_w, 12) if not legacy else None
        l_leg_o = region(4, 52, 4, 12) if not legacy else None
        # Same rule for the left sleeve layer: its origin is x=52 for both
        # classic and slim sheets; slim's spare column is at the right edge.
        l_arm_o = region(52, 52, arm_w, 12) if not legacy else None

        # Combine each part with its outer layer before scaling, so the
        # jacket/sleeve/pants pixels aren't lost to nearest-neighbor resize
        # doing it separately per layer.
        head = stack(head, head_o)
        if torso_o is not None:
            torso = stack(torso, torso_o)
        if r_leg_o is not None:
            r_leg = stack(r_leg, r_leg_o)
        if l_leg_o is not None:
            l_leg = stack(l_leg, l_leg_o)
        if r_arm_o is not None:
            r_arm = stack(r_arm, r_arm_o)
        if l_arm_o is not None:
            l_arm = stack(l_arm, l_arm_o)

        # --- Scale each part up at a shared pixel-art factor ---------------
        factor = 3
        head = grow(head, factor)          # 24x24
        torso = grow(torso, factor)        # 24x36
        r_leg = grow(r_leg, factor)        # 12x36
        l_leg = grow(l_leg, factor)        # 12x36
        r_arm = grow(r_arm, factor)        # arm_w*3 x36
        l_arm = grow(l_arm, factor)        # arm_w*3 x36

        arm_px = arm_w * factor
        canvas_w = arm_px * 2 + 24
        canvas_h = 24 + 36 + 36  # head + torso + legs, each already scaled
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        head_x = (canvas_w - 24) // 2
        torso_x = head_x
        torso_y = 24
        canvas.paste(head, (head_x, 0), head)
        canvas.paste(l_arm, (torso_x - arm_px, torso_y), l_arm)
        canvas.paste(r_arm, (torso_x + 24, torso_y), r_arm)
        canvas.paste(torso, (torso_x, torso_y), torso)

        # Legs sit centered under the torso, side by side.
        leg_y = torso_y + 36
        canvas.paste(l_leg, (torso_x, leg_y), l_leg)
        canvas.paste(r_leg, (torso_x + 12, leg_y), r_leg)

        final = canvas.resize(
            (canvas.width * scale // factor, canvas.height * scale // factor),
            Image.NEAREST,
        )
        final.save(out_path)
    return out_path


def get_skin_face_url(username: str) -> str:
    return f"https://crafatar.com/avatars/{username}?size=128&overlay"

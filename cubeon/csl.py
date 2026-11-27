"""
CustomSkinLoader (CSL) setup - the mod that makes skins and Cubeon capes
actually appear in-game.

Cubeon uses offline/cracked auth, so vanilla Minecraft has no session server
to fetch a skin from and always renders Steve/Alex. CSL is a client-side mod
that replaces that lookup with a list of skin sources it tries in order. This
module owns two jobs during managed skin setup:

  1. Download a missing CSL jar in ordinary profiles; modpacks use their
     existing copy or an explicit install from Mods.
  2. Register Cubeon's sources and configure launcher skins before Mojang.

--- WHY WE PREPEND, AND WHY IT IS NOT OPTIONAL ---

CSL merges its sources in `CustomSkinLoader.loadProfile0`:

    for (CompletableFuture<UserProfile> profileGetter : profileGetters) {
        UserProfile profile = profileGetter.join();
        if (profile == null) { continue; }
        profile0.mix(profile);
        if (isSkull && !profile0.hasSkinUrl()) { continue; }
        if (!config.forceLoadAllTextures) { break; }
        if (profile0.isFull()) { break; }
    }

`forceLoadAllTextures` defaults to **true**, so it keeps merging until
`isFull()` (`isNoneBlank(skinUrl, capeUrl)` - skin AND cape both set). And
`mix()` never overwrites: every field is copied only
`if (StringUtils.isEmpty(this.<field>))`. So the merge is
**first-source-wins, per texture slot** - a skin from one source and a cape
from another combine cleanly, which is exactly what Cubeon needs (skin from
the user's own upload, cape from our Worker).

The catch is the default order, which is by ascending `getPriority()`:

    Mojang 100 -> LittleSkin 200 -> BlessingSkin 300 -> ... -> LocalSkin 710
    -> OptiFine 810 -> CloakPlus 840

**Mojang is queried before LocalSkin.** Mojang resolves skins by *username*,
and it does not care that we are offline - so a cracked player who names
themselves `Dream` gets the real Dream's skin, `mix()` fills `skinUrl` from
it, and their own uploaded skin is silently discarded. That is not a corner
case; taken usernames are the norm for the audience Cubeon is aimed at.

CSL's supported fix is `ExtraList/`: entries dropped there are **prepended**
to the load list (`adds.addAll(this.loadlist); this.loadlist = adds;`), which
puts Cubeon ahead of Mojang. Once CSL has seeded its config, managed setup
orders sources as local Cubeon -> Cubeon API -> TLauncher -> ElyBy -> other
existing sources -> GameProfile -> Mojang. Provider fields and custom sources
survive this stable reorder. `forceLoadAllTextures` stays true so a cape-only
response cannot stop the search before a later source supplies the skin.

--- DEDUPE RULES WE HAVE TO DODGE ---

`loadExtraList()` deletes each file after reading it, and drops entries that
`loader.compare()` considers duplicates. Both comparators are traps:

  * `LegacyLoader.compare()` -> `Objects.equals` on skin AND cape AND elytra.
    An entry repeating LocalSkin's three plain paths is a duplicate and is
    dropped, leaving LocalSkin stranded at 710. So CubeonLocalSkin's
    cape/elytra paths carry a "./" ("LocalSkin/./capes/...") - they resolve to
    the exact same files but compare different, so the entry survives dedupe
    while still claiming the local cape for the merge order game described at
    EXTRALIST_ENTRIES.
  * `JsonAPILoader.compare()` -> `!isNoneEmpty(ssp0.root) || equalsIgnoreCase`.
    An existing rootless CustomSkinAPI entry matches *everything*. No shipped
    default is rootless (LittleSkin and BlessingSkin both have real roots), so
    this only bites if the user hand-added a blank one.

Being deleted after consumption is what makes rewriting these files on every
launch safe *and* self-healing: if CSL has not run yet the file just waits, and
once consumed our entries are in the load list where is_registered() sees them.

--- PROTOCOL FACTS THE WORKER DEPENDS ON ---

`CustomSkinAPI.toJsonUrl` is bare `root + username + ".json"` with no
normalization, and textures resolve as `root + "textures/" + id`. So
CUBEON_SKIN_API_ROOT **must** keep its trailing slash. Only the first
skin-type key in a profile is honored, which is why the Worker emits the skin
key before the cape key.
"""
import json
import os
from .atomicio import write_json

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

from .paths import CSL_CONFIG_PATH, CSL_EXTRALIST_DIR
from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import (list_mods, get_mod_download, download_mod,
                   LAUNCH_LOOKUP_ATTEMPTS, LAUNCH_LOOKUP_TIMEOUT)

# Cubeon's identity/skin Worker. Two forms on purpose:
#
#   CUBEON_API_BASE      machine endpoints (heartbeat pointer updates, skin
#                        uploads) - no trailing slash, paths appended to it.
#   CUBEON_SKIN_API_ROOT the CustomSkinAPI root CSL is handed in its ExtraList
#                        entry. The trailing slash is load-bearing: CSL builds
#                        lookups as bare `root + username + ".json"`, so
#                        ".../skins/" + "Alex" + ".json" -> /skins/Alex.json.
# Overridable via CUBEON_SKIN_API so it can point at `wrangler dev` without
# editing shipped code - and so a fork can keep its own users off the upstream
# Worker. The deployed URL is public (it is in this file, in friends.py and in
# invites.py, and it has to be: a client-side launcher has nowhere to hide it),
# so the Workers themselves carry the abuse protection. See worker/README.md.
CUBEON_API_BASE = (os.environ.get("CUBEON_SKIN_API")
                   or "https://cubeon-skins.hamza-457-shahbaz.workers.dev").rstrip("/")
CUBEON_SKIN_API_ROOT = CUBEON_API_BASE + "/skins/"

CSL_MODRINTH_SLUG = "customskinloader"

# CSL resolves a non-http Legacy path against its own data dir
# (.minecraft/CustomSkinLoader), so this is the same folder the built-in
# LocalSkin entry reads - and the same one skins.sync_local_skin_to_csl writes.
LOCAL_SKIN_TEMPLATE = "LocalSkin/skins/{USERNAME}.png"

# The two sources Cubeon registers, keyed by the ExtraList filename they are
# written to. `name` is what identifies them in the user's load list
# afterwards, so these strings are effectively a stable on-disk contract.
#
# ORDER CONTRACT (why the localskin entry looks the way it does):
# CSL merges sources strictly in loadlist order and `mix()` is first-wins per
# texture slot. The Worker API serves the shared cape for EVERY username, so
# if it ever sits ahead of the local source, a user's uploaded cape can never
# show. ExtraList entries are PREPENDED in the order CSL reads the files
# (java File.listFiles() - filesystem order, not alphabetical, not
# controllable), so "just add a second file" is a coin flip. Instead:
#
#   1. The localskin entry carries skin AND cape AND elytra. Once it is first
#      in the persistent load list, it wins every available local slot while
#      leaving gaps for the Worker to fill.
#   2. A missing/malformed config queues ONLY CubeonLocalSkin. One ExtraList
#      file has no enumeration race, so the player's own selected PNG wins on
#      the first game start even when network publication is slow or stale.
#   3. Once CSL has created a valid config, configure_source_order() atomically
#      adds the Worker entry and writes the deterministic local -> Worker order
#      before the next game starts. Older/partial installs are upgraded through
#      the same path. Nothing that isn't ours is removed.
#
# The "./" in the cape/elytra paths is load-bearing: LegacyLoader.compare()
# drops an ExtraList entry whose skin+cape+elytra strings all equal an
# existing entry's, and the built-in LocalSkin already claims the plain
# "LocalSkin/capes/..." paths. "LocalSkin/./capes/..." resolves to the same
# file (java.io.File normalizes it) while comparing different, so the entry
# survives dedupe.
EXTRALIST_ENTRIES = {
    "cubeon-api.json": {
        "name": "Cubeon",
        "type": "CustomSkinAPI",
        "root": CUBEON_SKIN_API_ROOT,
    },
    "cubeon-localskin.json": {
        "name": "CubeonLocalSkin",
        "type": "Legacy",
        "skin": LOCAL_SKIN_TEMPLATE,
        "cape": "LocalSkin/./capes/{USERNAME}.png",
        "elytra": "LocalSkin/./elytras/{USERNAME}.png",
        # CSL defaults these for its own entries but not for ours, and a null
        # model means "no model", not "guess". "auto" reads the arm width from
        # the PNG, which is what makes a slim (Alex) upload render correctly.
        "model": "auto",
        # CSL's own source comments call checkPNG "Not suitable for local
        # skin" - it is an HTTP content-type guard.
        "checkPNG": False,
    },
}

ENTRY_NAMES = frozenset(e["name"] for e in EXTRALIST_ENTRIES.values())
WORKER_ENTRY_NAME = EXTRALIST_ENTRIES["cubeon-api.json"]["name"]
LOCAL_ENTRY_NAME = EXTRALIST_ENTRIES["cubeon-localskin.json"]["name"]

# Existing CSL loaders, with their public, username-based lookup formats.
FALLBACK_ENTRIES = (
    {"name": "TLauncher", "type": "ElyByAPI",
     "root": "https://auth.tlauncher.org/skin/profile/texture/login/"},
    {"name": "ElyBy", "type": "ElyByAPI",
     "root": "https://skinsystem.ely.by/textures/"},
    {"name": "Mojang", "type": "MojangAPI",
     "apiRoot": "https://api.mojang.com/",
     "sessionRoot": "https://sessionserver.mojang.com/"},
)


def _source_priority(entry) -> int:
    """Stable groups; a custom MojangAPI server remains a third-party source."""
    if not isinstance(entry, dict):
        return 4
    name = str(entry.get("name") or "").casefold()
    kind = str(entry.get("type") or "").casefold()
    root = (str(entry.get("root") or "").lower().removeprefix("http://")
            .removeprefix("https://").rstrip("/"))
    if name == LOCAL_ENTRY_NAME.casefold():
        return 0
    if name == WORKER_ENTRY_NAME.casefold():
        return 1
    if kind == "elybyapi":
        if name == "tlauncher" or root == "auth.tlauncher.org/skin/profile/texture/login":
            return 2
        if name == "elyby" or root == "skinsystem.ely.by/textures":
            return 3
    if kind == "gameprofile":
        return 5
    if kind == "mojangapi" and all(
        str(entry.get(key) or default).lower().rstrip("/") == default.rstrip("/")
        for key, default in (("apiRoot", "https://api.mojang.com/"),
                             ("sessionRoot", "https://sessionserver.mojang.com/"))
    ):
        return 6
    return 4


def _drop_registered_queue_files(entries: list[dict]) -> None:
    """Remove only Cubeon-owned queue files already present in ``entries``."""
    names = {entry.get("name") for entry in entries if isinstance(entry, dict)}
    for filename, owned in EXTRALIST_ENTRIES.items():
        if owned["name"] not in names:
            continue
        path = os.path.join(instance_csl_path(CSL_EXTRALIST_DIR), filename)
        queued = _queued_content(path)
        if queued and queued.get("name") == owned["name"]:
            try:
                os.remove(path)
            except OSError:
                pass


def configure_source_order() -> bool:
    """Apply managed skin priority to an existing, readable CSL config.

    Repair Cubeon's known fields and add missing sources and fallbacks
    without duplicating renamed providers. Preserve extra fields, other
    providers, cache preferences and arm models. Missing/malformed configs are left for CSL to
    initialize itself with the deterministic LocalSkin-only bootstrap.
    """
    cfg = read_csl_config()
    if cfg is None:
        return False
    original = cfg["loadlist"]
    entries = list(original)
    for filename, owned in EXTRALIST_ENTRIES.items():
        index = next((i for i, entry in enumerate(entries)
                      if isinstance(entry, dict) and entry.get("name") == owned["name"]), None)
        existing = entries[index] if index is not None else {}
        candidate = {**existing, **owned}
        if owned["name"] == LOCAL_ENTRY_NAME:
            previous = existing if index is not None else _queued_content(os.path.join(
                instance_csl_path(CSL_EXTRALIST_DIR), filename))
            if (previous and previous.get("name") == LOCAL_ENTRY_NAME
                    and previous.get("model") in ("slim", "default")):
                candidate["model"] = previous["model"]
        if index is None:
            entries.append(candidate)
        else:
            entries[index] = candidate
    for fallback in FALLBACK_ENTRIES:
        priority = _source_priority(fallback)
        if not any(_source_priority(entry) == priority for entry in entries):
            entries.append(dict(fallback))
    ordered = sorted(entries, key=_source_priority)
    if ordered == original and cfg.get("forceLoadAllTextures", True) is True:
        _drop_registered_queue_files(ordered)
        return False
    cfg["loadlist"] = ordered
    cfg["forceLoadAllTextures"] = True
    try:
        from .atomicio import write_json
        write_json(instance_csl_path(CSL_CONFIG_PATH), cfg)
    except OSError:
        return False
    _drop_registered_queue_files(ordered)
    return True


# ---------------------------------------------------------------------------
# Reading CSL's own state
# ---------------------------------------------------------------------------

from .paths import instance_csl_path

def read_csl_config() -> dict | None:
    """Read a CSL config with a usable load list.

    CSL initializes missing or malformed configs on its next start.
    """
    try:
        with open(instance_csl_path(CSL_CONFIG_PATH), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("loadlist"), list) else None


def registered_names() -> set[str]:
    """Names of Cubeon's sources that are already in CSL's load list."""
    return {entry["name"] for entry in _loadlist() if entry.get("name") in ENTRY_NAMES}


def pending_names() -> set[str]:
    """Names whose ExtraList file is written but not yet consumed by CSL.

    Counts as registered for status purposes: the file is on disk and CSL will
    merge it on its next start.
    """
    pending = set()
    for filename, entry in EXTRALIST_ENTRIES.items():
        if os.path.isfile(os.path.join(instance_csl_path(CSL_EXTRALIST_DIR), filename)):
            pending.add(entry["name"])
    return pending


def is_registered() -> bool:
    """Whether both Cubeon sources are registered or queued to be."""
    return ENTRY_NAMES <= (registered_names() | pending_names())


def is_installed(mc_version: str | None, loader: str | None,
                 version_id: str | None = None) -> bool:
    """Whether an enabled CSL jar is in this instance's mod profile.

    Matches on the recorded Modrinth slug, filename or descriptor, so a jar the user
    dropped in by hand still counts - re-downloading over someone's manual
    install would be rude and would double-load the mod.
    """
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return False
    from .mods import resolve_profile_dir
    directory = resolve_profile_dir(mc_version, loader, version_id)
    for mod in list_mods(mc_version, loader, version_id=version_id):
        if not mod.get("enabled", True):
            continue
        if _is_csl(mod, directory, loader):
            return True
    return False


def _is_csl(mod, directory, loader):
    """Recognize managed, hand-installed and renamed CSL JARs."""
    slug = (mod.get("slug") or "").lower()
    name = (mod.get("display_name") or mod.get("filename") or "").lower()
    if CSL_MODRINTH_SLUG in slug or CSL_MODRINTH_SLUG in name:
        return True
    from .mods import read_mod_metadata
    metadata = read_mod_metadata(os.path.join(directory, mod["filename"]), loader) or {}
    return str(metadata.get("id") or "").lower().replace("-", "").replace("_", "") == CSL_MODRINTH_SLUG


def disabled_by_setting(directory: str) -> bool:
    """Whether all disabled CSL files are backups owned by our Settings switch."""
    from .file_safety import entry_name
    try:
        with open(os.path.join(directory, ".cubeon-csl-disabled.json"), encoding="utf-8") as source:
            entries = json.load(source)["jars"]
        backups = {entry_name(entry["disabled"], extensions=(".jar.disabled",))
                   for entry in entries}
        disabled = {name for name in os.listdir(directory)
                    if name.lower().startswith("customskinloader")
                    and name.endswith(".jar.disabled")}
        return bool(disabled) and disabled.issubset(backups)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def set_enabled(mc_version: str | None, loader: str | None, enabled: bool, *,
                version_id: str | None = None) -> int:
    """Keep CSL opt-out JARs as backups and restore only those backups on opt-in."""
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return 0
    from .mods import get_profile_dir, set_managed_mod_enabled
    directory = get_profile_dir(mc_version, loader, version_id)

    def active_names():
        return (mod["filename"] for mod in list_mods(mc_version, loader, version_id=version_id)
                if mod.get("enabled", True) and _is_csl(mod, directory, loader))

    return set_managed_mod_enabled(
        directory, ".cubeon-csl-disabled.json", enabled, active_names,
        lambda name: _is_csl({"filename": name}, directory, loader))


# ---------------------------------------------------------------------------
# Making it so
# ---------------------------------------------------------------------------

def _loadlist() -> list[dict]:
    """The user's loadlist entries (empty if no config / not a list)."""
    cfg = read_csl_config() or {}
    return [entry for entry in cfg.get("loadlist", []) if isinstance(entry, dict)]


def set_localskin_model(model: str) -> bool:
    """Set Cubeon's own LocalSkin entry to the exact Minecraft arm model.

    CSL's ``auto`` mode guesses from transparent arm columns. Skin editors
    frequently flatten those columns, so a real Alex skin is then rendered as
    wide Steve arms. Cubeon owns this one entry, therefore it can safely write
    the user's explicit choice (``slim`` or ``default``) without touching any
    other CSL provider.

    The entry may be registered already or still waiting in ExtraList for the
    next game start; update either representation so the choice survives both
    cases.
    """
    wanted = "slim" if model == "slim" else "default"
    changed = False
    cfg = read_csl_config()
    if cfg:
        for entry in cfg["loadlist"]:
            if isinstance(entry, dict) and entry.get("name") == LOCAL_ENTRY_NAME:
                if entry.get("model") != wanted:
                    entry["model"] = wanted
                    changed = True
                break
        if changed:
            try:
                write_json(instance_csl_path(CSL_CONFIG_PATH), cfg)
            except OSError:
                return False

    # A first-time install has not merged the entry yet. If it is queued,
    # patch the queued file too, rather than allowing one wrong-model launch.
    path = os.path.join(instance_csl_path(CSL_EXTRALIST_DIR), "cubeon-localskin.json")
    queued = _queued_content(path)
    if queued and queued.get("name") == LOCAL_ENTRY_NAME and queued.get("model") != wanted:
        queued["model"] = wanted
        try:
            write_json(path, queued)
            changed = True
        except OSError:
            pass
    return changed


def configure_request_cache() -> bool:
    """Raise CSL's untouched 30-second default to five minutes before launch.

    Preserve custom cache values, provider order, local settings and all other
    fields. Do not create a partial config before CSL seeds its own defaults.
    Called only through managed registration, so the opt-out stays hands-off.
    """
    cfg = read_csl_config()
    if not cfg or cfg.get("cacheExpiry", 30) != 30:
        return False
    cfg["cacheExpiry"] = 300
    try:
        from .atomicio import write_json
        write_json(instance_csl_path(CSL_CONFIG_PATH), cfg)
    except OSError:
        return False
    return True


def write_extralist_entries() -> list[str]:
    """Repair registered sources or queue only LocalSkin for CSL's first start.

    Returns the names of newly written queue entries. Persistent setup adds the
    Worker after LocalSkin once CSL has initialized a usable config.
    """
    configure_source_order()
    configure_request_cache()
    if LOCAL_ENTRY_NAME in registered_names():
        return []

    directory = instance_csl_path(CSL_EXTRALIST_DIR)
    # Interrupted older builds may have queued the Worker. Withdraw that owned
    # file so first launch cannot depend on the filesystem's iteration order.
    worker_path = os.path.join(directory, "cubeon-api.json")
    queued_worker = _queued_content(worker_path)
    if queued_worker and queued_worker.get("name") == WORKER_ENTRY_NAME:
        try:
            os.remove(worker_path)
        except OSError:
            pass

    path = os.path.join(directory, "cubeon-localskin.json")
    entry = EXTRALIST_ENTRIES["cubeon-localskin.json"]
    queued = _queued_content(path)
    if (queued and queued.get("name") == LOCAL_ENTRY_NAME
            and queued.get("model") in ("slim", "default")):
        entry = {**entry, "model": queued["model"]}
    if queued == entry:
        return []
    try:
        write_json(path, entry)
    except OSError:
        return []
    return [LOCAL_ENTRY_NAME]


def _queued_content(path: str) -> dict | None:
    """The entry already queued at `path`, or None if absent/unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def remove_pending_entries() -> list[str]:
    """Deletes ExtraList files CSL hasn't consumed yet.

    This is the honest half of the opt-out. An entry CSL already merged lives
    in the user's CustomSkinLoader.json, and Cubeon does not rewrite that file
    - so turning the setting off stops all future registration and withdraws
    anything still queued, but an already-merged source stays until it's
    removed from that file. Deleting entries out of a config the user may have
    tuned by hand is not a call this launcher should make silently.
    """
    removed = []
    for filename, entry in EXTRALIST_ENTRIES.items():
        path = os.path.join(instance_csl_path(CSL_EXTRALIST_DIR), filename)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed.append(entry["name"])
    return removed


def install(mc_version: str, loader: str, progress_cb=None,
            version_id: str | None = None) -> str:
    """Downloads the CSL jar into this instance's mod profile.

    Returns a short status string. Raises nothing the caller has to handle -
    a missing build or a dead network is reported, not thrown, because this
    runs inside the launch path and must never stop the game from starting.
    """
    try:
        file_info = get_mod_download(
            CSL_MODRINTH_SLUG, mc_version=mc_version, loader=loader,
            timeout=LAUNCH_LOOKUP_TIMEOUT, attempts=LAUNCH_LOOKUP_ATTEMPTS,
        )
    except Exception as ex:
        return f"couldn't reach Modrinth ({ex.__class__.__name__})"

    if not file_info:
        return f"no CustomSkinLoader build for {loader} {mc_version}"

    try:
        download_mod(
            file_info["url"], file_info["filename"], progress_cb=progress_cb,
            slug=CSL_MODRINTH_SLUG, mc_version=mc_version, loader=loader,
            hashes=file_info.get("hashes"), version_id=version_id,
        )
    except Exception as ex:
        return f"download failed ({ex.__class__.__name__})"

    return f"installed CustomSkinLoader {file_info['version_number']}"


def ensure_ready(mc_version: str | None, loader: str | None,
                  *, manage: bool = True, status_cb=None,
                  version_id: str | None = None) -> dict:
    """Everything needed for skins and capes to work on the next launch.

    Called from launch_game() before mods are synced into the game folder, so
    a freshly downloaded jar makes it into that same launch. Modpacks keep
    their selected JARs; missing CSL requires an explicit install from Mods.

    `manage` is the user's cfg["manage_skin_mod"] setting: False means hands
    off entirely - no download, no registration, and anything we queued but
    CSL hasn't picked up yet gets withdrawn.

    Best-effort by design: every failure path returns a status instead of
    raising. A player with no internet must still be able to start the game.

    Returns {"installed", "registered", "detail"} for the caller to log/show.
    """
    result = {"installed": False, "registered": False, "detail": ""}

    if not manage:
        withdrawn = remove_pending_entries()
        result["registered"] = bool(registered_names())
        result["installed"] = is_installed(mc_version, loader, version_id)
        result["detail"] = "skin-mod management is off"
        if withdrawn:
            result["detail"] += f"; withdrew queued {', '.join(sorted(withdrawn))}"
        return result

    # Registering is free and offline, so do it regardless of loader - if the
    # user switches from vanilla to Fabric later, CSL finds it already set up.
    written = write_extralist_entries()
    result["registered"] = is_registered()

    if loader not in MOD_CAPABLE_LOADERS or not mc_version:
        # Vanilla can't load mods at all. Not a failure, just nothing to do.
        result["detail"] = "no mod loader selected - skins and capes need one"
        return result

    if is_installed(mc_version, loader, version_id):
        result["installed"] = True
        result["detail"] = "CustomSkinLoader already installed"
    else:
        from .mods import is_modpack_profile
        if is_modpack_profile(mc_version, loader, version_id):
            result["detail"] = "CustomSkinLoader is not included in this modpack; install it in Mods to enable skins"
            return result
        if status_cb:
            status_cb("Installing CustomSkinLoader")
        detail = install(mc_version, loader, version_id=version_id)
        result["installed"] = is_installed(mc_version, loader, version_id)
        result["detail"] = detail

    if written:
        result["detail"] += f"; registered {', '.join(sorted(written))}"
    return result

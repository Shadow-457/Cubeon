"""
CustomSkinLoader (CSL) setup - the mod that makes skins and Cubeon capes
actually appear in-game.

Cubeon uses offline/cracked auth, so vanilla Minecraft has no session server
to fetch a skin from and always renders Steve/Alex. CSL is a client-side mod
that replaces that lookup with a list of skin sources it tries in order. This
module owns two jobs, both of which must happen without the user doing
anything (the whole pitch is "click host, send a link, they're in, with their
own skin"):

  1. Download the CSL jar into the active mod profile.
  2. Register Cubeon's two skin sources in CSL's load list.

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
puts Cubeon ahead of Mojang. We use that rather than rewriting the user's
`CustomSkinLoader.json`, so a config they have tuned by hand is never
clobbered.

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

import requests

from .paths import CSL_CONFIG_PATH, CSL_EXTRALIST_DIR
from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import list_mods, get_mod_download, download_mod

# Cubeon's identity/skin Worker. Two forms on purpose:
#
#   CUBEON_API_BASE      machine endpoints (heartbeat pointer updates, skin
#                        uploads) - no trailing slash, paths appended to it.
#   CUBEON_SKIN_API_ROOT the CustomSkinAPI root CSL is handed in its ExtraList
#                        entry. The trailing slash is load-bearing: CSL builds
#                        lookups as bare `root + username + ".json"`, so
#                        ".../skins/" + "Alex" + ".json" -> /skins/Alex.json.
CUBEON_API_BASE = "https://cubeon-skins.hamza-457-shahbaz.workers.dev"
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
#   1. The localskin entry carries skin AND cape AND elytra, so whichever of
#      the two sources is merged last is prepended FIRST and wins every local
#      slot while leaving gaps for the Worker to fill.
#   2. write_extralist_entries() therefore STAGGERS the queueing: the Worker
#      entry is written first and the localskin entry only once the Worker is
#      confirmed merged into the loadlist - guaranteeing the localskin entry
#      is always the last (=> first) one prepended.
#   3. Loadlists merged by older builds (or in a bad file order) are healed
#      by refresh_stale_localskin_entry(): if the registered localskin entry
#      is missing the cape field or sits behind the Worker entry, that ONE
#      Cubeon-owned entry is removed from the loadlist so it re-queues and
#      re-prepends ahead. Nothing that isn't ours is ever touched.
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


# ---------------------------------------------------------------------------
# Reading CSL's own state
# ---------------------------------------------------------------------------

def read_csl_config() -> dict | None:
    """CSL's CustomSkinLoader.json, or None if absent/unparseable.

    Absent is the normal state before the mod has ever run once - it writes
    the file itself on first launch, so this is not an error.
    """
    try:
        with open(CSL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def registered_names() -> set[str]:
    """Names of Cubeon's sources that are already in CSL's load list."""
    cfg = read_csl_config()
    if not cfg:
        return set()
    loadlist = cfg.get("loadlist")
    if not isinstance(loadlist, list):
        return set()
    return {
        entry.get("name")
        for entry in loadlist
        if isinstance(entry, dict) and entry.get("name") in ENTRY_NAMES
    }


def pending_names() -> set[str]:
    """Names whose ExtraList file is written but not yet consumed by CSL.

    Counts as registered for status purposes: the file is on disk and CSL will
    merge it on its next start.
    """
    pending = set()
    for filename, entry in EXTRALIST_ENTRIES.items():
        if os.path.isfile(os.path.join(CSL_EXTRALIST_DIR, filename)):
            pending.add(entry["name"])
    return pending


def is_registered() -> bool:
    """Whether both Cubeon sources are registered or queued to be."""
    return ENTRY_NAMES <= (registered_names() | pending_names())


def is_installed(mc_version: str | None, loader: str | None) -> bool:
    """Whether the CSL jar is in the (mc_version, loader) mod profile.

    Matches on the recorded Modrinth slug or the filename, so a jar the user
    dropped in by hand still counts - re-downloading over someone's manual
    install would be rude and would double-load the mod.
    """
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return False
    for mod in list_mods(mc_version, loader):
        slug = (mod.get("slug") or "").lower()
        name = (mod.get("display_name") or "").lower()
        if CSL_MODRINTH_SLUG in slug or CSL_MODRINTH_SLUG in name:
            return True
    return False


# ---------------------------------------------------------------------------
# Making it so
# ---------------------------------------------------------------------------

def _loadlist() -> list[dict]:
    """The user's loadlist entries (empty if no config / not a list)."""
    cfg = read_csl_config() or {}
    loadlist = cfg.get("loadlist")
    return [e for e in loadlist if isinstance(e, dict)] if isinstance(loadlist, list) else []


def _localskin_stale(loadlist: list[dict]) -> bool:
    """Whether a registered CubeonLocalSkin entry can't do its job, so it
    should be removed and re-merged (which re-prepends it to the front):

      - old format: no cape field (merged by a build before cape support), or
      - shadowed: the Worker entry sits ahead of it, so the shared cape wins
        the cape slot before the local one is ever consulted.
    """
    local_idx = next((i for i, e in enumerate(loadlist)
                      if e.get("name") == LOCAL_ENTRY_NAME), None)
    if local_idx is None:
        return False  # not registered - nothing stale (normal flow handles it)
    if not loadlist[local_idx].get("cape"):
        return True
    worker_idx = next((i for i, e in enumerate(loadlist)
                       if e.get("name") == WORKER_ENTRY_NAME), None)
    return worker_idx is not None and worker_idx < local_idx


def refresh_stale_localskin_entry() -> bool:
    """Heals a stale/shadowed CubeonLocalSkin entry by removing that ONE
    Cubeon-owned entry from the user's loadlist, so the normal queueing
    re-merges it at the front of the list on CSL's next start.

    This is a deliberate, narrowly-scoped exception to "never rewrite the
    user's CustomSkinLoader.json": we only ever REMOVE an entry whose name we
    own, only when it provably can't do its job (old format or shadowed by
    the Worker entry), and the very next launch re-adds it in working form.
    Anything the user added themselves is never touched.

    Returns True when a removal happened (config was rewritten).
    """
    loadlist = _loadlist()
    if not _localskin_stale(loadlist):
        return False
    cfg = read_csl_config()
    cfg["loadlist"] = [e for e in loadlist if e.get("name") != LOCAL_ENTRY_NAME]
    try:
        with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        return False
    return True


def _worker_root_stale(loadlist: list[dict]) -> bool:
    """Whether a registered Cubeon (Worker) entry's root has drifted away from
    the current CUBEON_SKIN_API_ROOT.

    The real case this catches: entries merged before the Worker moved its
    CustomSkinAPI route under /skins/ carry the bare base URL as their root, so
    every lookup CSL builds (`root + username + ".json"`) hits a path the Worker
    404s - the shared cape (and any network skin) silently dies, with nothing in
    the load list looking wrong because is_registered() only checks the name.
    """
    entry = next((e for e in loadlist if e.get("name") == WORKER_ENTRY_NAME), None)
    if entry is None:
        return False  # not registered - the normal write flow adds it correctly
    return entry.get("root") != CUBEON_SKIN_API_ROOT


def refresh_stale_worker_entry() -> bool:
    """Corrects a drifted root on the registered Cubeon (Worker) entry, in place.

    Unlike the localskin heal - which REMOVES its entry so the normal queueing
    re-prepends it to fix load ORDER - the Worker entry's only problem is its
    root URL; its position in the list is already correct. So this rewrites just
    that one field and leaves everything else (including load order) untouched,
    rather than removing and re-merging.

    Same narrowly-scoped exception to "never rewrite the user's
    CustomSkinLoader.json" as refresh_stale_localskin_entry: it only ever edits
    an entry whose name Cubeon owns, and only when its root no longer matches
    what this build ships. Anything the user added themselves is never touched.

    Returns True when a correction was written.
    """
    loadlist = _loadlist()
    if not _worker_root_stale(loadlist):
        return False
    cfg = read_csl_config()
    for entry in cfg.get("loadlist", []):
        if isinstance(entry, dict) and entry.get("name") == WORKER_ENTRY_NAME:
            entry["root"] = CUBEON_SKIN_API_ROOT
    try:
        with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        return False
    return True


def write_extralist_entries() -> list[str]:
    """Drops an ExtraList file for each source not already registered or queued.

    Returns the names actually written. A file already sitting in ExtraList/
    with identical content is left alone, so this is a no-op on every launch
    after the first - but one whose content has drifted (say a future Cubeon
    release moves the API root) is rewritten rather than left stale.

    ORDERING: the Worker entry is always queued first, and the localskin
    entry only once the Worker entry is confirmed merged into the loadlist.
    ExtraList entries are prepended in merge order (last merged wins the
    front), so this stagger guarantees the local source - which carries the
    user's skin, hat-composed skin, cape, and elytra - always sits ahead of
    the Worker. See the ORDER CONTRACT above EXTRALIST_ENTRIES.

    Note what this deliberately does NOT do: it cannot tell "the user removed
    the Cubeon entry from CustomSkinLoader.json" apart from "we have never
    registered it" - both look like *absent from the load list*. It re-adds in
    both cases, because a silently-dead cape is a worse failure for this
    launcher than an entry reappearing. The supported way to turn the whole
    thing off is cfg["manage_skin_mod"], which gates this from ensure_ready().
    """
    # Heal a bad/stale merge from an older build first: the removed entry is
    # unregistered by this very removal, so the flow below re-queues it.
    refresh_stale_localskin_entry()
    # And correct a drifted Worker root in place (the /skins/ migration left
    # older installs pointing at a bare URL that 404s, killing the cape).
    refresh_stale_worker_entry()

    have = registered_names()
    written = []
    for filename, entry in EXTRALIST_ENTRIES.items():
        if entry["name"] in have:
            continue
        # Stagger (see ORDER CONTRACT): the localskin entry waits until the
        # Worker entry is confirmed merged, so it is always prepended after
        # (=> ahead of) it. On a genuinely fresh install this costs one
        # launch: the Worker registers on launch 1, the local source on 2.
        #
        # That one-launch gap does NOT delay a player seeing their OWN skin
        # online: the Worker entry (launch 1, already ahead of Mojang) now
        # serves this player's own uploaded skin too (skins._publish_skin),
        # so a taken-name player - the case Mojang would hijack - gets their
        # real skin from the first launch. The launch-2 local entry is what
        # then wins the CAPE slot (for a custom local cape) and covers the
        # fully-offline case where the Worker is unreachable.
        if entry["name"] == LOCAL_ENTRY_NAME and WORKER_ENTRY_NAME not in have:
            continue
        path = os.path.join(CSL_EXTRALIST_DIR, filename)
        if _queued_content(path) == entry:
            continue  # already waiting for CSL, and still correct
        try:
            os.makedirs(CSL_EXTRALIST_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
        except OSError:
            continue
        written.append(entry["name"])
    return written


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
        path = os.path.join(CSL_EXTRALIST_DIR, filename)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed.append(entry["name"])
    return removed


def install(mc_version: str, loader: str, progress_cb=None) -> str:
    """Downloads the CSL jar into the (mc_version, loader) profile.

    Returns a short status string. Raises nothing the caller has to handle -
    a missing build or a dead network is reported, not thrown, because this
    runs inside the launch path and must never stop the game from starting.
    """
    try:
        file_info = get_mod_download(CSL_MODRINTH_SLUG, mc_version=mc_version, loader=loader)
    except requests.RequestException as ex:
        return f"couldn't reach Modrinth ({ex.__class__.__name__})"

    if not file_info:
        return f"no CustomSkinLoader build for {loader} {mc_version}"

    try:
        download_mod(
            file_info["url"], file_info["filename"], progress_cb=progress_cb,
            slug=CSL_MODRINTH_SLUG, mc_version=mc_version, loader=loader,
        )
    except (OSError, requests.RequestException) as ex:
        return f"download failed ({ex.__class__.__name__})"

    return f"installed CustomSkinLoader {file_info['version_number']}"


def ensure_ready(mc_version: str | None, loader: str | None,
                  *, manage: bool = True, status_cb=None) -> dict:
    """Everything needed for skins and capes to work on the next launch.

    Called from launch_game() before mods are synced into the game folder, so
    a freshly downloaded jar makes it into that same launch.

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
        result["installed"] = is_installed(mc_version, loader)
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

    if is_installed(mc_version, loader):
        result["installed"] = True
        result["detail"] = "CustomSkinLoader already installed"
    else:
        if status_cb:
            status_cb("Installing CustomSkinLoader")
        detail = install(mc_version, loader)
        result["installed"] = is_installed(mc_version, loader)
        result["detail"] = detail

    if written:
        result["detail"] += f"; registered {', '.join(sorted(written))}"
    return result

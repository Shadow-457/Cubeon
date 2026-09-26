"""
Minekube Connect - the replacement for playit.gg (removed 2026-08-26).

WHAT CONNECT IS

Minekube Connect (https://connect.minekube.com) gives any Minecraft server
a free public address - `<endpoint>.play.minekube.net` - that friends can
join from anywhere, with DDoS protection at their edge. It replaces
port forwarding exactly like playit did, but the integration model is
completely different and much simpler:

playit was a separate daemon process Cubeon had to download, spawn,
self-manage over a socket, drive through a claim/sign-in CLI flow, and
parse ANSI-coloured logs from. Connect is **just another Paper plugin**:
one .jar dropped into the server's plugins/ folder. The server process
Cubeon already starts and owns IS the tunnel client. There is nothing
extra to download at runtime beyond the plugin itself, no account sign-in
flow, no socket, no second binary.

HOW AN ADDRESS HAPPENS

1. connect-spigot.jar sits in <server_dir>/plugins/.
2. plugins/connect/config.yml optionally names the endpoint
   (`endpoint: my-server`). Empty/missing means Minekube assigns a
   temporary random name.
3. The Paper server boots, the plugin connects out to the Connect
   network, and prints lines like:

       [connect] Endpoint name: live-beru
       [connect] Your public address: live-beru.play.minekube.net

4. read_public_address() picks that out of logs/latest.log - the same log
   the Server tab console streams from - so the invite code flow needs no
   parsing of live subprocess output at all.

OFFLINE / CRACKED FRIENDS

Connect by default only lets Mojang-authenticated players through.
Cubeon's servers run online-mode=false (that's DEFAULT_SERVER_PROPERTIES
in server.py - its users play on offline accounts), so an offline endpoint
is what these servers actually are, and the endpoint must say so
explicitly or authenticated friends get in and everyone else bounces:

    allow-offline-mode-players: true

That's set together with the endpoint name by ensure_config(). Users who
want a fully-authenticated server can turn it off in the config file;
the UI toggle writes through to the same key.

CUSTOM ENDPOINTS

The endpoint name is user-enterable (validated, lowercased) - that's the
"custom endpoint" option in the Play With Friends panel. Leaving it blank
uses Minekube's random-name service. A custom domain CNAME'd to Minekube
can be typed directly into the field too; anything ending in a real TLD
that isn't a bare endpoint name is stored verbatim and handed to friends
as-typed.
"""
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
import zlib

from .paths import APP_NAME, SERVERS_DIR, user_agent
from .server import (
    CONNECT_PLUGIN_NAME as PLUGIN_NAME,
    SERVER_TYPE_PAPER,
    get_plugins_dir,
    get_server_dir,
    get_server_type,
)

log = logging.getLogger(__name__)

# The plugin jar lives in the server's plugins folder under this exact name
# (imported from server.py, which also protects it from deletion there).

# The project publishes a permanent "latest" release tag specifically so
# integrators don't have to resolve versions - verified against the
# Connect Java Plugin guide (connect.minekube.com/guide/connectors/plugin).
PLUGIN_URL = ("https://github.com/minekube/connect-java/releases/"
              "download/latest/" + PLUGIN_NAME)

# Where the plugin keeps its own config, relative to the server folder.
CONFIG_REL = os.path.join("plugins", "connect", "config.yml")

HTTP_TIMEOUT = (5, 30)

# A truncated/corrupt plugin jar is worse than a missing one: Paper fails
# to enable it at boot and the user has no idea why there's no address.
MIN_PLUGIN_BYTES = 100_000


class MinekubeError(Exception):
    """A Connect problem with a message meant for the user."""


# ---------------------------------------------------------------------------
# Endpoint names.
#
# A generated/random endpoint looks like "live-beru": lowercase letters and
# dashes. User-chosen names on *.play.minekube.net follow DNS rules. The
# validator accepts either that shape OR a full hostname (custom domains),
# because both are legal things to put in the `endpoint:` key.
# ---------------------------------------------------------------------------

_ENDPOINT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\Z)"
    r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\Z")


def validate_endpoint(raw: str | None) -> str:
    """Normalizes a user-entered endpoint, raising ValueError with a
    sentence the UI can show verbatim. Returns "" for blank input, which
    everywhere below means "let Minekube pick a random name"."""
    value = (raw or "").strip().lower()
    if not value:
        return ""
    # Tolerate a friend pasting the full public address back in.
    value = re.sub(r"\.play\.minekube\.net$", "", value)
    value = value.rstrip(".")
    if _ENDPOINT_RE.match(value) or _HOSTNAME_RE.match(value):
        return value
    raise ValueError(
        "Endpoint names are lowercase letters, numbers and dashes "
        "(like my-server). Or type a full domain you've pointed at "
        "Minekube.")


def public_address(endpoint: str | None) -> str | None:
    """What friends type into Minecraft's Direct Connect box. None when
    the endpoint is blank (random-name mode) - in that mode the actual
    name only exists once the server has booted with the plugin, and is
    then read out of the log by read_public_address()."""
    clean = validate_endpoint(endpoint)
    if not clean:
        return None
    if "." in clean:
        return clean  # already a full custom domain
    return f"{clean}.play.minekube.net"


def config_path(version_id: str) -> str:
    return os.path.join(get_server_dir(version_id), CONFIG_REL)


# ---------------------------------------------------------------------------
# Config file handling.
#
# plugins/connect/config.yml is YAML, written by hand here rather than with
# a YAML library so no new dependency ships. Only ever touched surgically:
# the plugin generates the full file on first boot (bedrock-identity blocks
# and all), and "existing configuration files are not silently rewritten"
# is the plugin's own documented behaviour - so ours must not be either.
# Two keys are managed: `endpoint:` and `allow-offline-mode-players:`.
# ---------------------------------------------------------------------------

_ENDPOINT_LINE_RE = re.compile(r"^endpoint\s*:.*$", re.MULTILINE)
_ALLOW_OFFLINE_LINE_RE = re.compile(r"^allow-offline-mode-players\s*:.*$", re.MULTILINE)


def _set_yaml_key(text: str, key_re: re.Pattern, line: str) -> str:
    if key_re.search(text):
        return key_re.sub(line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


def _read_config(version_id: str) -> str:
    try:
        with open(config_path(version_id), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_config(version_id: str, text: str) -> None:
    path = config_path(version_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as ex:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise MinekubeError(f"Couldn't save the Connect settings: {ex}") from ex


def ensure_config(version_id: str, endpoint: str | None = None,
                  allow_offline: bool = True) -> None:
    """Makes sure the plugin's config carries the endpoint name (blank =
    random) and the offline-player opt-in. Creates a minimal config when
    the plugin hasn't generated one yet; otherwise edits only those keys,
    preserving everything else the plugin or user wrote.

    Safe to call before the plugin is installed or the server has ever
    run: first boot reads whatever is here and fills in its defaults
    around it."""
    clean = validate_endpoint(endpoint)
    text = _read_config(version_id)
    if not text:
        text = ("# Minekube Connect, managed by Cubeon\n"
                "# Docs: https://connect.minekube.com\n")
    text = _set_yaml_key(text, _ENDPOINT_LINE_RE, f"endpoint: {clean}" if clean else "endpoint:")
    text = _set_yaml_key(text, _ALLOW_OFFLINE_LINE_RE,
                         f"allow-offline-mode-players: {'true' if allow_offline else 'false'}")
    _write_config(version_id, text)


def get_endpoint(version_id: str) -> str:
    """The configured endpoint name, "" for random-name mode."""
    match = _ENDPOINT_LINE_RE.search(_read_config(version_id))
    if not match:
        return ""
    value = match.group(0).split(":", 1)[1].strip().strip('"').strip("'")
    return value


def get_allow_offline(version_id: str) -> bool:
    """Whether the endpoint allows offline/cracked Java players.

    Defaults to True when the key isn't in the config at all - NOT the
    plugin's own default (false), on purpose: every Cubeon server runs
    online-mode=false (DEFAULT_SERVER_PROPERTIES), so an endpoint without
    this flag would silently reject exactly the players Cubeon exists
    for. The switch in the UI reads this, so "missing" must read as the
    state ensure_config() actually writes, or a first save flips it off."""
    match = _ALLOW_OFFLINE_LINE_RE.search(_read_config(version_id))
    if not match:
        return True
    return match.group(0).split(":", 1)[1].strip().lower() == "true"


# ---------------------------------------------------------------------------
# The plugin jar itself.
# ---------------------------------------------------------------------------

def plugin_jar_path(version_id: str) -> str:
    return os.path.join(get_plugins_dir(version_id), PLUGIN_NAME)


def _plugin_jar_valid(path: str) -> bool:
    try:
        if os.path.getsize(path) < MIN_PLUGIN_BYTES:
            return False
        with zipfile.ZipFile(path) as archive:
            meta = archive.read("plugin.yml").decode("utf-8")
            if not re.search(r"^\s*name\s*:\s*['\"]?connect['\"]?\s*(?:#.*)?$",
                             meta, re.MULTILINE | re.IGNORECASE):
                return False
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile, zlib.error, KeyError, UnicodeError, RuntimeError, EOFError):
        return False


def is_plugin_installed(version_id: str) -> bool:
    return _plugin_jar_valid(plugin_jar_path(version_id))


def find_local_plugin(search_dirs: list[str] | None = None) -> str | None:
    """A Connect plugin jar the user already has on disk, or None.

    The shipped assets/jars folder is searched first (that's where the jar
    Cubeon distributes lives, next to the Friends mod jars), then the app
    dir, cwd, and the servers dir - for users who were handed the jar to
    drop somewhere. Verified by opening the zip and reading its plugin.yml
    rather than by filename alone: "I downloaded a jar" and "this is the
    right jar" are different claims, and the wrong jar fails at server boot
    with nothing pointing back here."""
    if search_dirs is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        search_dirs = [os.path.join(app_dir, "assets", "jars"), app_dir,
                       os.getcwd(), SERVERS_DIR]

    candidates = []
    for directory in search_dirs:
        if not directory or not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            low = name.lower()
            if not low.endswith(".jar") or low.startswith("."):
                continue
            if "connect" not in low:
                continue
            path = os.path.join(directory, name)
            if _plugin_jar_valid(path):
                try:
                    candidates.append((os.path.getmtime(path), path))
                except OSError:
                    pass

    if not candidates:
        return None
    return max(candidates)[1]


def install_plugin(version_id: str, *, progress_cb=None, status_cb=None,
                   force: bool = False) -> str:
    """Puts connect-spigot.jar into the server's plugins folder.

    Uses a local copy when find_local_plugin() can verify one (no download
    at all), otherwise fetches the latest release. Atomic (.part then
    rename), size-floored and archive-validated either way: a captive
    portal returning HTML with status 200 must surface as "download
    failed", not as a plugin that mysteriously never loads. Skipped
    entirely when a healthy copy is already present unless force=True.

    Returns the installed plugin jar path."""
    if get_server_type(version_id) != SERVER_TYPE_PAPER:
        raise MinekubeError("Connect needs a Paper server. It's a Paper plugin.")

    dest = plugin_jar_path(version_id)
    if not force and is_plugin_installed(version_id):
        return dest

    from . import net
    local = find_local_plugin()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".connect-", suffix=".part")
    os.close(fd)
    try:
        if local:
            if status_cb:
                status_cb(f"Using your Connect plugin ({os.path.basename(local)})")
            shutil.copyfile(local, tmp)
        else:
            if status_cb:
                status_cb("Downloading the Minekube Connect plugin...")
            net.download_to(tmp, PLUGIN_URL, timeout=HTTP_TIMEOUT,
                            headers={"User-Agent": user_agent("minekube connect")},
                            progress_cb=progress_cb)
        if not _plugin_jar_valid(tmp):
            raise MinekubeError("The Connect plugin is incomplete or invalid. Try again.")
        os.replace(tmp, dest)
    except net.DownloadError as ex:
        raise MinekubeError(
            "Couldn't download the Minekube Connect plugin. Check your "
            "internet and try again.") from ex
    except OSError as ex:
        raise MinekubeError("Couldn't install the Connect plugin. Try again.") from ex
    finally:
        for path in (tmp, tmp + ".part"):
            try:
                os.unlink(path)
            except OSError:
                pass

    log.info("minekube: installed %s (%d bytes)", dest, os.path.getsize(dest))
    return dest


def uninstall_plugin(version_id: str) -> bool:
    try:
        os.unlink(plugin_jar_path(version_id))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Reading the public address back.
# ---------------------------------------------------------------------------

# Matches the address wherever the plugin prints it - console lines, the
# latest.log copy of them, or startup banners:
#   [connect] Your public address: live-beru.play.minekube.net
_ADDRESS_RE = re.compile(
    r"(?<![a-z0-9_.-])((?:[a-z0-9-]+\.)+minekube\.(?:net|com)"
    r"(?::[^\s,;)\]}>\"']*)?)(?![a-z0-9_:-]|\.[a-z0-9])",
    re.IGNORECASE)

# Log words that shouldn't be mistaken for the tunnel address even though
# they're hostnames on minekube domains.
_ADDRESS_EXCLUDE = ("watch-connect", "randomname.minekube.net",
                    "connect.minekube.com", "gate.minekube.com")


def read_public_address(version_id: str, *, log_lines: str | None = None) -> str | None:
    """The endpoint address the plugin announced, or None.

    Reads the tail of the server's own logs/latest.log (the plugin only
    announces the address at startup, so old sessions' lines are stale -
    the tail keeps this cheap and mostly correct). Pass log_lines to scan
    provided console text instead, e.g. lines streamed this session.

    None is a normal answer meaning "not announced (yet)" - the server may
    simply still be booting."""
    if log_lines is None:
        path = os.path.join(get_server_dir(version_id), "logs", "latest.log")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                log_lines = "".join(f.readlines()[-400:])
        except OSError:
            return None

    best = None
    for line in reversed(log_lines.splitlines()):
        low = line.lower()
        if any(bad in low for bad in _ADDRESS_EXCLUDE):
            continue
        for match in _ADDRESS_RE.finditer(line):
            candidate = match.group(1).lower().rstrip(".")
            host, separator, port = candidate.partition(":")
            if not _HOSTNAME_RE.fullmatch(host):
                continue
            if separator and (not re.fullmatch(r"[0-9]{1,5}", port)
                              or not 1 <= int(port) <= 65535):
                continue
            if any(bad in candidate for bad in _ADDRESS_EXCLUDE):
                continue
            return candidate  # newest line first: freshest announcement wins
    return best


def wait_for_address(version_id: str, *, timeout: float = 90.0,
                     progress_cb=None) -> str | None:
    """Polls until the plugin announces the address or the timeout ends.

    The plugin connects out to Minekube's network during server startup,
    which takes a few seconds on a good day and noticeably longer on a
    cold JVM. Returns None rather than raising - "not up yet" is normal,
    and the UI explains how to check the console."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = read_public_address(version_id)
        if found:
            return found
        if progress_cb:
            try:
                progress_cb(max(0.0, deadline - time.monotonic()))
            except Exception:
                pass
        time.sleep(2.0)
    return None


def share_status(version_id: str) -> dict:
    """Everything the Play With Friends panel renders, in one call:
    {"paper": bool, "plugin": bool, "endpoint": str, "address": str|None,
     "allow_offline": bool}"""
    paper = get_server_type(version_id) == SERVER_TYPE_PAPER
    return {
        "paper": paper,
        "plugin": paper and is_plugin_installed(version_id),
        "endpoint": get_endpoint(version_id) if paper else "",
        "address": read_public_address(version_id) if paper else None,
        "allow_offline": get_allow_offline(version_id) if paper else True,
    }

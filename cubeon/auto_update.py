"""Verified GitHub release updates, with a detached, two-phase OS handoff.

Only installed Windows copies and user-owned x86_64 AppImages are eligible.
The UI supplies an idle/close gate; this module never imports Flet or exits the
launcher. Helpers acquire the same target lock, acknowledge readiness, and wait
for BOTH a commit token and the original process to exit before installing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote, urlsplit
import uuid

from .updater import APP_VERSION

log = logging.getLogger(__name__)
REPOSITORY = "Shadow-457/Cubeon"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSETS = {"windows": "Cubeon-Windows-x64-Setup.exe", "linux": "Cubeon-x86_64.AppImage"}
MAX_METADATA = 1024 * 1024
MAX_ASSET = 1024 * 1024 * 1024
ATTEMPTS = 3
DOWNLOAD_SECONDS = 15 * 60
FAILED_COOLDOWN = 24 * 60 * 60
PARENT_WAIT_SECONDS = 90
HEALTH_WAIT_SECONDS = 120
_VERSION = re.compile(r"v?(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class UpdateError(RuntimeError):
    """The existing installation must remain in use."""


class Cancelled(UpdateError):
    """The launcher session ended before the update was handed off."""


@dataclass(frozen=True)
class Target:
    kind: str
    path: Path

    @property
    def key(self) -> str:
        return hashlib.sha256(os.path.normcase(str(self.path)).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    name: str
    url: str
    size: int
    sha256: str


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise UpdateError("Invalid release version.")
    return tuple(int(part) for part in match.groups())


def parse_release(data, kind: str, current: str = APP_VERSION) -> Release | None:
    """Pin one fully published, newer numeric release to one exact asset."""
    if not isinstance(data, dict):
        raise UpdateError("Invalid GitHub release metadata.")
    if data.get("draft") is not False or data.get("prerelease") is not False:
        return None
    tag = data.get("tag_name")
    latest = version_tuple(tag)
    if latest <= version_tuple(current):
        return None
    name = ASSETS.get(kind)
    if name is None:
        raise UpdateError("Unsupported update platform.")
    assets = data.get("assets")
    if not isinstance(assets, list) or len(assets) > 1000:
        raise UpdateError("Invalid GitHub release assets.")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise UpdateError("The release is missing a unique platform installer.")
    asset = matches[0]
    size = asset.get("size")
    digest = asset.get("digest")
    if (asset.get("state") != "uploaded" or type(size) is not int
            or not 1024 <= size <= MAX_ASSET):
        raise UpdateError("The release file is incomplete or has an invalid size.")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise UpdateError("GitHub did not supply a SHA-256 checksum. Update skipped.")
    sha256 = digest[7:].lower()
    if not _HASH.fullmatch(sha256):
        raise UpdateError("GitHub supplied an invalid SHA-256 checksum. Update skipped.")
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/{quote(tag, safe='')}/{name}"
    if asset.get("browser_download_url") != expected_url:
        raise UpdateError("The release download does not belong to Cubeon.")
    return Release(".".join(map(str, latest)), tag, name, expected_url, size, sha256)


def trusted_url(url: str, *, metadata=False) -> bool:
    """Validate each redirect BEFORE opening it, including GitHub's asset CDN."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment
                or any(ord(c) < 32 or c == "\\" for c in url)):
            return False
        if metadata:
            return url == LATEST_URL
        if parsed.hostname == "github.com":
            return parsed.path.startswith(f"/{REPOSITORY}/releases/download/") and not parsed.query
        return parsed.hostname in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
    except (ValueError, TypeError):
        return False


def _check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled("Update cancelled because Cubeon is closing.")


def _get(url, cancel, *, metadata=False):
    # Use Cubeon's pooled TLS transport, but keep this update's retry and size
    # bounds here. In particular, an unbounded Retry-After must not hang exit.
    from . import net
    from .paths import user_agent
    _check_cancel(cancel)
    return net.get_with_retry(
        url, attempts=1, timeout=(5, 15),
        headers={"User-Agent": user_agent("auto-update"), "Accept-Encoding": "identity",
                 "Accept": "application/vnd.github+json" if metadata else "application/octet-stream",
                 "X-GitHub-Api-Version": "2022-11-28"},
        url_validator=lambda value: trusted_url(value, metadata=metadata),
        cancel_check=lambda: _check_cancel(cancel),
    )


def fetch_release(kind, current=APP_VERSION, *, cancel=None) -> Release | None:
    cancel = cancel or threading.Event()
    deadline = time.monotonic() + 60
    for attempt in range(ATTEMPTS):
        _check_cancel(cancel)
        try:
            with _get(LATEST_URL, cancel, metadata=True) as response:
                if response.status_code != 200:
                    raise UpdateError("GitHub did not return release metadata.")
                body = bytearray()
                for block in response.iter_content(32 * 1024):
                    _check_cancel(cancel)
                    if time.monotonic() > deadline:
                        raise UpdateError("The release check timed out.")
                    body.extend(block)
                    if len(body) > MAX_METADATA:
                        raise UpdateError("GitHub release metadata is too large.")
            return parse_release(json.loads(body), kind, current)
        except Cancelled:
            raise
        except (UpdateError, ValueError):
            raise  # invalid metadata is not a transient network error
        except Exception as error:
            from .net import HTTPStatusError
            if isinstance(error, HTTPStatusError) or attempt == ATTEMPTS - 1 or time.monotonic() > deadline:
                raise UpdateError("Could not check GitHub Releases.") from error
            if cancel.wait(1.5 * (2 ** attempt)):
                _check_cancel(cancel)
    return None


def _regular(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise UpdateError("An update path is not a regular file.")
    if os.name != "nt" and info.st_uid != os.getuid():
        raise UpdateError("An update file belongs to another user.")
    return info


def file_hash(path: Path, *, cancel=None) -> str:
    _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel is not None:
                _check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest()


def _executable_header(path: Path, kind: str):
    with path.open("rb") as stream:
        header = stream.read(64)
        if kind == "linux":
            if (len(header) != 64 or header[:6] != b"\x7fELF\x02\x01"
                    or header[8:11] != b"AI\x02" or header[18:20] != b"\x3e\x00"):
                raise UpdateError("The download is not an x86_64 type-2 AppImage.")
        elif kind == "windows":
            if len(header) != 64 or header[:2] != b"MZ":
                raise UpdateError("The download is not a Windows installer.")
            offset = int.from_bytes(header[60:64], "little")
            if not 64 <= offset <= min(path.stat().st_size - 6, 1024 * 1024):
                raise UpdateError("The Windows installer header is invalid.")
            stream.seek(offset)
            # NSIS is a 32-bit bootstrapper for Cubeon's 64-bit payload.
            if stream.read(6) not in (b"PE\x00\x00\x4c\x01", b"PE\x00\x00\x64\x86"):
                raise UpdateError("The Windows installer header is invalid.")
        else:
            raise UpdateError("Unsupported update platform.")


def verify_download(path: Path, release: Release, kind: str, *, cancel=None):
    if _regular(path).st_size != release.size:
        raise UpdateError("The update download is incomplete.")
    if file_hash(path, cancel=cancel) != release.sha256:
        raise UpdateError("The update's SHA-256 checksum does not match.")
    _executable_header(path, kind)


def _space(directory: Path, required: int):
    if shutil.disk_usage(directory).free < required + 32 * 1024 * 1024:
        raise UpdateError("Not enough free space to safely install the Cubeon update.")


def download_release(release: Release, target: Target, cache: Path, *, cancel=None, progress=None) -> Path:
    """Publish only complete, verified bytes; a failed attempt cannot replace them."""
    cancel = cancel or threading.Event()
    final = cache / f"{release.sha256}-{release.name}"
    if final.exists() or final.is_symlink():
        try:
            verify_download(final, release, target.kind, cancel=cancel)
            return final
        except Cancelled:
            raise
        except (OSError, UpdateError):
            if not final.is_symlink():
                final.unlink(missing_ok=True)
            else:
                raise UpdateError("The update cache contains a redirected file.")
    _space(cache, release.size)
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    last_error = None
    for attempt in range(ATTEMPTS):
        _check_cancel(cancel)
        fd, temp_name = tempfile.mkstemp(prefix="download-", suffix=".part", dir=cache)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as stream, _get(release.url, cancel) as response:
                if response.status_code != 200:
                    raise UpdateError("The download server did not return a complete file.")
                length = response.headers.get("Content-Length")
                if length is not None and (not str(length).isdigit() or int(length) != release.size):
                    raise UpdateError("The download size does not match GitHub's release.")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise UpdateError("The update server returned unexpected compression.")
                received = 0
                for block in response.iter_content(128 * 1024):
                    _check_cancel(cancel)
                    if time.monotonic() > deadline:
                        raise UpdateError("The update download timed out.")
                    received += len(block)
                    if received > release.size:
                        raise UpdateError("The update download is larger than GitHub's release.")
                    stream.write(block)
                    if progress:
                        progress(received, release.size)
                stream.flush()
                os.fsync(stream.fileno())
            verify_download(temp, release, target.kind, cancel=cancel)
            _check_cancel(cancel)
            os.replace(temp, final)
            return final
        except Cancelled:
            raise
        except Exception as error:
            last_error = error
            from .net import HTTPStatusError
            if isinstance(error, (UpdateError, HTTPStatusError)) or attempt == ATTEMPTS - 1:
                break
            if time.monotonic() > deadline or cancel.wait(1.5 * (2 ** attempt)):
                _check_cancel(cancel)
                break
        finally:
            temp.unlink(missing_ok=True)
    raise UpdateError("Could not download a verified Cubeon update.") from last_error


def _registered_windows_dir() -> Path | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Cubeon") as key:
            value, kind = winreg.QueryValueEx(key, "InstallDir")
        if kind != winreg.REG_SZ or not isinstance(value, str) or not value:
            return None
        return Path(value).resolve()
    except OSError:
        return None


def detect_target() -> Target | None:
    """No network or self-replacement for source, .deb, macOS or other CPUs."""
    if not getattr(sys, "frozen", False) or platform.machine().lower() not in {"amd64", "x86_64"}:
        return None
    if sys.platform == "win32":
        exe = Path(sys.executable)
        if exe.is_symlink() or exe.name.lower() != "cubeon.exe":
            return None
        exe = exe.resolve()
        if (_registered_windows_dir() != exe.parent or not (exe.parent / "_internal").is_dir()
                or not (exe.parent / "Uninstall Cubeon.exe").is_file()):
            return None
        if not powershell_path():
            return None
        target = Target("windows", exe)
    elif sys.platform.startswith("linux"):
        value = os.environ.get("CUBEON_APPIMAGE_PATH") or os.environ.get("APPIMAGE")
        if not value or not os.path.isabs(value):
            return None
        image = Path(value)
        if image.is_symlink():
            return None
        target = Target("linux", image.resolve())
        needed = ("bash", "flock", "sha256sum", "stat", "cp", "mv", "chmod", "sync", "readlink", "setsid", "od", "tr", "rm")
        if not all(shutil.which(command) for command in needed):
            return None
    else:
        return None
    try:
        info = _regular(target.path)
        if target.kind == "linux":
            _executable_header(target.path, "linux")
            if (not info.st_mode & stat.S_IXUSR or info.st_mode & (stat.S_ISUID | stat.S_ISGID)
                    or target.path.parent.stat().st_uid != os.getuid()):
                return None
        # Test directory replacement, not file writability: a 0555 AppImage
        # can be replaced safely in its owner's writable directory.
        fd, name = tempfile.mkstemp(prefix=".cubeon-update-probe-", dir=target.path.parent)
        os.close(fd)
        os.unlink(name)
    except (OSError, UpdateError):
        return None
    return target


def powershell_path() -> str | None:
    # The built-in Windows PowerShell 5.1 is sufficient. Avoid PATH lookalikes.
    root = os.environ.get("SystemRoot", r"C:\Windows")
    path = Path(root) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return str(path) if path.is_file() else None


def cache_root() -> Path:
    from .paths import CUBEON_HOME
    return Path(CUBEON_HOME) / "updates" / "v1"


def _private_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
        raise UpdateError("The update cache is not a private directory.")
    if os.name != "nt":
        path.chmod(0o700)


class TargetLock:
    """Nonblocking cross-process lock shared with both detached helpers."""
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        if self.path.is_symlink():
            raise UpdateError("The update lock is redirected.")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            handle = create(str(self.path), 0xC0000000, 0, None, 4, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                code = ctypes.get_last_error()
                if code in (32, 33):
                    return False
                raise ctypes.WinError(code)
            self.handle = handle
        else:
            import fcntl
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
            self.handle = fd
        return True

    def release(self):
        if self.handle is not None:
            if os.name == "nt":
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(self.handle))
            else:
                os.close(self.handle)
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise UpdateError("Another Cubeon update is already in progress.")
        return self

    def __exit__(self, *_):
        self.release()


def helper_environment() -> dict:
    from .incident import client_environment
    env = client_environment(os.environ)
    for key in tuple(env):
        if key.startswith("_PYI_") or key in {"APPIMAGE", "APPDIR", "OWD", "CUBEON_UPDATE_JOB", "CUBEON_UPDATE_TOKEN"}:
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def other_launcher_running(target: Target) -> bool:
    """Conservative ownership check; never terminate another launcher copy."""
    import psutil
    for process in psutil.process_iter(["pid", "name", "exe"]):
        if process.pid == os.getpid():
            continue
        try:
            if target.kind == "windows":
                if (process.info.get("name") or "").lower() != "cubeon.exe":
                    continue
                exe = process.info.get("exe")
                if not exe or Path(exe).resolve() == target.path:
                    return True
            else:
                name = (process.info.get("name") or "").lower()
                if "cubeon" not in name and "appimage" not in name:
                    continue
                env = process.environ()
                value = env.get("CUBEON_APPIMAGE_PATH") or env.get("APPIMAGE")
                if value and Path(value).resolve() == target.path:
                    return True
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError):
            return True
    return False


def _atomic_text(path: Path, text: str):
    fd, name = tempfile.mkstemp(prefix=".signal-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Handoff:
    def __init__(self, directory: Path, token: str, process):
        self.directory = directory
        self.token = token
        self.process = process
        self.committed = False
        self._mutex = threading.Lock()

    def commit(self):
        with self._mutex:
            if (self.directory / "cancel").exists():
                raise Cancelled("The update handoff was cancelled.")
            _atomic_text(self.directory / "go", self.token)
            self.committed = True

    def cancel(self):
        # Cancel before restoring the UI: even a later ordinary close must
        # not allow a previously rejected close request to install anything.
        with self._mutex:
            _atomic_text(self.directory / "cancel", self.token)
            self.committed = False


def create_job(target: Target, release: Release, download: Path, cache: Path, *, cancel=None,
               args=None, parent_pid=None, parent_wait=PARENT_WAIT_SECONDS, health_wait=HEALTH_WAIT_SECONDS) -> tuple[Path, dict]:
    """Capture the target's bytes before the UI closes; no script interpolation."""
    import psutil
    from .atomicio import write_json
    info = _regular(target.path)
    original_sha256 = file_hash(target.path, cancel=cancel)
    after = target.path.lstat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise UpdateError("Cubeon's installed file changed while preparing the update.")
    _space(target.path.parent, release.size + 2 * info.st_size if target.kind == "linux" else release.size * 6)
    directory = cache / f"job-{uuid.uuid4().hex}"
    _private_directory(directory)
    parent_pid = os.getpid() if parent_pid is None else parent_pid
    token = uuid.uuid4().hex
    job = {
        "schema": 1, "kind": target.kind, "target": str(target.path), "download": str(download),
        "size": release.size, "sha256": release.sha256, "old_sha256": original_sha256,
        "old_identity": f"{info.st_dev}:{info.st_ino}:{info.st_size}",
        "parent_identity": f"{target.path.parent.stat().st_dev}:{target.path.parent.stat().st_ino}",
        "mode": format(stat.S_IMODE(info.st_mode) | stat.S_IXUSR, "o"),
        "version": release.version, "token": token, "parent_pid": parent_pid,
        "parent_started_ms": int(psutil.Process(parent_pid).create_time() * 1000),
        "parent_wait": parent_wait, "health_wait": health_wait,
        "lock": str(cache / "update.lock"), "failed": str(cache / f"failed-{release.sha256}"),
        "args": list(sys.argv[1:] if args is None else args),
    }
    if target.kind == "linux":
        # /proc start ticks survive PID reuse and exec, including AppImage's
        # wrapper. Read the field after the LAST ')' (comm may contain spaces).
        job["parent_ticks"] = Path(f"/proc/{parent_pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    if any(not isinstance(arg, str) or "\x00" in arg for arg in job["args"]):
        raise UpdateError("Cannot preserve the launcher's arguments safely.")
    if target.kind == "windows" and any(c in str(target.path.parent) for c in '\r\n"'):
        raise UpdateError("The installation directory cannot be passed safely to NSIS.")
    write_json(str(directory / "job.json"), job)
    if target.kind == "linux":
        # NUL-separated values are data, even when paths contain quotes,
        # dollars, newlines, or shell syntax. Bash reads them with read -d ''.
        fields = ["target", "download", "sha256", "size", "old_sha256", "old_identity", "parent_identity",
                  "mode", "parent_pid", "parent_ticks", "parent_wait", "health_wait", "token", "lock", "failed"]
        (directory / "job.bin").write_bytes(b"".join(str(job[key]).encode() + b"\0" for key in fields)
                                             + b"".join(arg.encode() + b"\0" for arg in job["args"]))
    return directory, job


def spawn_helper(directory: Path, job: dict) -> Handoff:
    from ._update_helpers import LINUX_HELPER, WINDOWS_HELPER
    env = helper_environment()
    if job["kind"] == "linux":
        script = directory / "install.sh"
        script.write_text(LINUX_HELPER, encoding="utf-8", newline="\n")
        command = ["/bin/bash", str(script), str(directory)]
        options = {"start_new_session": True}
    else:
        executable = powershell_path()
        if not executable:
            raise UpdateError("Windows PowerShell is unavailable.")
        script = directory / "install.ps1"
        # PowerShell 5.1 needs a BOM to read non-ASCII source consistently.
        script.write_text(WINDOWS_HELPER, encoding="utf-8-sig", newline="\r\n")
        command = [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(script), "-JobPath", str(directory / "job.json")]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
    with (directory / "helper.log").open("ab", buffering=0) as output:
        process = subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=output, close_fds=True, **options)
    return Handoff(directory, job["token"], process)


def wait_ready(handoff: Handoff, cancel, *, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_cancel(cancel)
        ready = handoff.directory / "ready"
        if ready.is_file() and ready.read_text(encoding="utf-8") == handoff.token:
            return
        if handoff.process.poll() is not None:
            raise UpdateError(f"The update helper could not prepare. See {handoff.directory / 'helper.log'}")
        cancel.wait(0.1)
    raise UpdateError("The update helper did not acknowledge readiness.")


def acknowledge_startup() -> bool:
    """Acknowledge the replacement's first UI paint, only for its own job."""
    raw = os.environ.pop("CUBEON_UPDATE_JOB", None)
    token = os.environ.pop("CUBEON_UPDATE_TOKEN", None)
    if not raw or not token or not getattr(sys, "frozen", False):
        return False
    try:
        path = Path(raw)
        if path.name != "job.json" or not path.parent.name.startswith("job-") or path.is_symlink():
            return False
        if not path.resolve().is_relative_to(cache_root().resolve()) or path.stat().st_size > 32 * 1024:
            return False
        job = json.loads(path.read_text(encoding="utf-8"))
        image = os.environ.get("CUBEON_APPIMAGE_PATH") or os.environ.get("APPIMAGE")
        if (job.get("schema") != 1 or job.get("kind") != "linux" or job.get("token") != token
                or job.get("version") != APP_VERSION or not image
                or Path(image).resolve() != Path(job["target"])):
            return False
        _atomic_text(path.parent / "health.ok", token)
        return True
    except (OSError, ValueError, KeyError):
        log.warning("Could not acknowledge update startup", exc_info=True)
        return False


def _clean_cache(cache: Path, keep: Path):
    """Prune only our known file shapes, under the target lock."""
    for path in cache.iterdir():
        if path == keep or path.is_symlink():
            continue
        age = time.time() - path.stat().st_mtime
        if path.is_file() and (re.fullmatch(r"[0-9a-f]{64}-(Cubeon-x86_64\.AppImage|Cubeon-Windows-x64-Setup\.exe)", path.name)
                               or (path.name.startswith("download-") and path.suffix == ".part")):
            path.unlink()
        elif path.is_dir() and re.fullmatch(r"job-[0-9a-f]{32}", path.name) and age > 7 * 24 * 60 * 60:
            shutil.rmtree(path)
        elif path.is_file() and re.fullmatch(r"failed-[0-9a-f]{64}", path.name) and age > FAILED_COOLDOWN:
            path.unlink()


class AutoUpdater:
    """One background startup attempt; busy applications defer to next launch."""
    def __init__(self, *, prepare, request_exit, resume, notice=None, current=APP_VERSION):
        self.prepare = prepare
        self.request_exit = request_exit
        self.resume = resume
        self.notice = notice
        self.current = current
        self.cancel_event = threading.Event()
        self._thread = None
        self._start_lock = threading.Lock()
        self.handoff = None

    def _notice(self, phase, release=None):
        log.info("auto-update: %s%s", phase, f" {release.version}" if release else "")
        if self.notice:
            try:
                self.notice(phase, release)
            except Exception:
                log.debug("Update notice could not be displayed", exc_info=True)

    def start(self):
        with self._start_lock:
            if self._thread is not None or self.cancel_event.is_set():
                return
            self._thread = threading.Thread(target=self.run, daemon=True, name="cubeon-auto-update")
            self._thread.start()

    def stop(self):
        self.cancel_event.set()

    def run(self):
        lock = None
        prepared = False
        handed_off = False
        release = None
        try:
            _check_cancel(self.cancel_event)
            target = detect_target()
            if target is None:
                return
            root = cache_root()
            _private_directory(root.parent)
            _private_directory(root)
            cache = root / target.key
            _private_directory(cache)
            lock = TargetLock(cache / "update.lock")
            if not lock.acquire():
                self._notice("already-running")
                return
            release = fetch_release(target.kind, self.current, cancel=self.cancel_event)
            if release is None:
                return
            failed = cache / f"failed-{release.sha256}"
            if failed.exists() and time.time() - failed.stat().st_mtime < FAILED_COOLDOWN:
                self._notice("previous-failure", release)
                return
            final = cache / f"{release.sha256}-{release.name}"
            _clean_cache(cache, final)
            self._notice("downloading", release)
            download = download_release(release, target, cache, cancel=self.cancel_event)
            self._notice("verified", release)
            _check_cancel(self.cancel_event)
            if other_launcher_running(target):
                self._notice("deferred", release)
                return
            # Hashing/space/identity probes happen BEFORE the UI claim, outside
            # TREE_LOCK. The detached helper repeats the hash after shutdown.
            directory, job = create_job(target, release, download, cache, cancel=self.cancel_event)
            _check_cancel(self.cancel_event)
            if not self.prepare():
                self._notice("deferred", release)
                return
            prepared = True
            _check_cancel(self.cancel_event)
            # No installer starts in this gap: the helper must win the same
            # lock AND acknowledge readiness before Cubeon may close.
            lock.release()
            self.handoff = spawn_helper(directory, job)
            wait_ready(self.handoff, self.cancel_event)
            _check_cancel(self.cancel_event)
            handed_off = bool(self.request_exit(self.handoff, release))
            if not handed_off:
                raise UpdateError("Cubeon could not schedule closing for the update.")
        except Cancelled:
            log.info("auto-update: session ended before handoff")
        except Exception:
            log.warning("Auto-update stopped; existing Cubeon installation retained", exc_info=True)
            self._notice("failed" if release is not None else "check-unavailable")
        finally:
            if lock is not None:
                lock.release()
            if not handed_off:
                if self.handoff is not None:
                    try:
                        self.handoff.cancel()
                    except OSError:
                        log.warning("Could not cancel the update helper", exc_info=True)
                if prepared:
                    try:
                        self.resume()
                    except Exception:
                        log.warning("Could not restore the updater UI gate", exc_info=True)

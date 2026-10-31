"""User-requested, verified launcher downloads and detached installer handoff."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import updater


class UpdateCancelled(Exception):
    pass


class UpdateReleaseChanged(ValueError):
    pass


def application_busy(state: dict) -> bool:
    if any(state.get(key) for key in ("running_version", "installing_version",
                                     "launching_version", "ending_session")):
        return True
    try:
        from . import watchdog, server
        if watchdog.stale_session() is not None:
            return True
        root = Path(server.SERVERS_DIR)
        return root.is_dir() and any(server.is_server_running(folder.name)
                                    for folder in root.iterdir() if folder.is_dir())
    except Exception:
        return True


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class InstallTarget:
    asset: str
    path: Path | None = None
    reason: str = ""

    @property
    def can_install(self):
        return self.path is not None


def installation_target() -> InstallTarget:
    """Use an installer for registered builds; never replace a source checkout."""
    if sys.platform == "win32":
        exe = Path(sys.executable).resolve()
        packaged = (getattr(sys, "frozen", False) and exe.name.lower() == "cubeon.exe"
                    and (exe.parent / "_internal").is_dir())
        if packaged and (exe.parent / "Uninstall Cubeon.exe").is_file():
            # A copied installation must not update a different registered copy.
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Cubeon") as key:
                    registered = Path(winreg.QueryValueEx(key, "InstallDir")[0]).resolve()
                if registered == exe.parent:
                    return InstallTarget("windows", exe.parent)
            except (OSError, ImportError):
                pass
            return InstallTarget("windows", reason="Run Cubeon from its installed folder, or reinstall it to repair its registration.")
        return InstallTarget("windows", reason="Install Cubeon using the Windows setup to enable automatic updates.")
    if sys.platform == "darwin":
        return InstallTarget("macos")
    image = os.environ.get("APPIMAGE") or os.environ.get("CUBEON_APPIMAGE_PATH")
    if image and getattr(sys, "frozen", False) and platform.machine().lower() in {"x86_64", "amd64"}:
        path = Path(image).resolve()
        # Atomic replacement needs write/search permission on the directory,
        # not write permission on the existing executable (often mode 0555).
        if path.is_file() and os.access(path.parent, os.W_OK | os.X_OK):
            return InstallTarget("linux", path)
        return InstallTarget("linux", reason="Move the Cubeon AppImage to a writable folder, reopen it, and try Update again.")
    exe = Path(sys.executable).resolve()
    if (getattr(sys, "frozen", False) and exe == Path("/opt/cubeon/Cubeon")
            and all(shutil.which(command) for command in ("dpkg-query", "apt-get", "pkexec"))):
        try:
            owner = subprocess.run(["dpkg-query", "-S", str(exe)], capture_output=True,
                                   text=True, timeout=5)
            if owner.returncode == 0 and owner.stdout.strip() == "cubeon: /opt/cubeon/Cubeon":
                return InstallTarget("linux-deb", exe)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return InstallTarget("linux" if not getattr(sys, "frozen", False) else "linux-deb")


def release_asset(info: dict, target: InstallTarget) -> dict | None:
    asset = info.get("assets", {}).get(target.asset)
    if not isinstance(asset, dict):
        return None
    url = urlparse(str(asset.get("url") or ""))
    origin = urlparse(updater.UPDATE_SERVICE)
    version = str(info.get("version") or "")
    channel = "beta" if info.get("channel") == "beta" else "stable"
    if (url.scheme != "https" or url.netloc != origin.netloc
            or url.path != f"/updates/{channel}/{target.asset}"
            or parse_qs(url.query) != {"version": [version]} or url.fragment):
        return None
    return asset


def download_update(info: dict, target: InstallTarget, cancel: threading.Event,
                    progress=lambda done, total: None, directory=None) -> Path:
    """Download after a click; reject incomplete or mismatched releases."""
    asset = release_asset(info, target)
    if not asset:
        raise ValueError("This release does not have a download for this installation.")
    digest = str(asset.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("This release cannot be verified. Use the download page instead.")
    total = asset.get("size")
    if isinstance(total, bool) or not isinstance(total, int) or not 0 < total <= 1024**3:
        raise ValueError("The update download size is invalid.")
    if cancel.is_set():
        raise UpdateCancelled()
    if directory is None:
        from .paths import CUBEON_HOME
        directory = Path(CUBEON_HOME) / "updates"
    Path(directory).mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="download-", dir=directory))
    destination = folder / {"windows": "Cubeon-Setup.exe", "linux-deb": "Cubeon.deb",
                            "linux": "Cubeon.AppImage"}.get(target.asset, "Cubeon.download")
    received, hasher = 0, hashlib.sha256()
    deadline = time.monotonic() + 1800
    try:
        with updater.requests.get(asset["url"], stream=True, timeout=(8, 15)) as response:
            if response.status_code == 409:
                raise UpdateReleaseChanged("The release changed. Check for updates again in Settings.")
            response.raise_for_status()
            with destination.open("xb") as output:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancel.is_set():
                        raise UpdateCancelled()
                    if time.monotonic() > deadline:
                        raise TimeoutError("The update download timed out. Please try again.")
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > total:
                        raise ValueError("The update download is larger than expected.")
                    output.write(chunk)
                    hasher.update(chunk)
                    progress(received, total)
                output.flush()
                os.fsync(output.fileno())
        if cancel.is_set():
            raise UpdateCancelled()
        if received != total or hasher.hexdigest() != digest:
            raise ValueError("The update download could not be verified. Please try again.")
        return destination
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


# Fixed script text; paths/data are arguments or JSON, never interpolated code.
# Both helpers have a bounded wait and recheck the downloaded bytes after exit.
_APPIMAGE_HELPER = r'''#!/bin/sh
set -eu
parent=$1
target=$2
download=$3
digest=$4
reopen=$5
result=$6
remaining=120
failed() {
  rm -f -- "${replacement:-}" "${backup:-}"
  printf 'failed\nThe update could not be installed. See the update install.log.\n' > "$result"
  if [ "$reopen" = 1 ] && ! kill -0 "$parent" 2>/dev/null && [ -x "$target" ]; then
    unset APPIMAGE APPDIR CUBEON_APPIMAGE_PATH
    export PYINSTALLER_RESET_ENVIRONMENT=1
    "$target" >/dev/null 2>&1 &
  fi
}
trap failed EXIT
while kill -0 "$parent" 2>/dev/null; do
  [ "$remaining" -gt 0 ] || exit 1
  sleep 1
  remaining=$((remaining - 1))
done
actual=$(sha256sum -- "$download")
[ "${actual%% *}" = "$digest" ] || exit 1
replacement=$(mktemp "${target}.update.XXXXXX")
backup=$(mktemp "${target}.previous.XXXXXX")
cp -- "$download" "$replacement"
chmod --reference="$target" "$replacement"
chmod u+x "$replacement"
cp -p -- "$target" "$backup"
mv -f -- "$backup" "${target}.cubeon-previous"
mv -f -- "$replacement" "$target"
printf 'success\n' > "$result"
trap 'rm -f -- "$replacement" "$backup"' EXIT
rm -f -- "$download"
if [ "$reopen" = 1 ]; then
  unset APPIMAGE APPDIR CUBEON_APPIMAGE_PATH
  export PYINSTALLER_RESET_ENVIRONMENT=1
  "$target" >/dev/null 2>&1 &
fi
'''

_WINDOWS_HELPER = r'''param([string]$JobFile)
$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
try {
$deadline = (Get-Date).AddSeconds(120)
while (Get-Process -Id $job.pid -ErrorAction SilentlyContinue) {
  if ((Get-Date) -ge $deadline) { throw 'Cubeon did not close; update cancelled.' }
  Start-Sleep -Seconds 1
}
if ((Get-FileHash -LiteralPath $job.download -Algorithm SHA256).Hash.ToLower() -ne $job.sha256) {
  throw 'The update checksum changed; update cancelled.'
}
# /D must be LAST and unquoted; NSIS consumes the remaining command line.
$arguments = '/S /D=' + $job.target
$installer = Start-Process -FilePath $job.download -ArgumentList $arguments -Wait -PassThru
if ($installer.ExitCode -ne 0) { throw 'The Cubeon installer failed.' }
Set-Content -LiteralPath $job.result -Value 'success' -Encoding UTF8
Remove-Item -LiteralPath $job.download -Force -ErrorAction SilentlyContinue
if ($job.reopen) {
  $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
  Start-Process -FilePath (Join-Path $job.target 'Cubeon.exe')
}
} catch {
  Set-Content -LiteralPath $job.result -Value ("failed`n" + $_.Exception.Message) -Encoding UTF8
  if ($job.reopen -and -not (Get-Process -Id $job.pid -ErrorAction SilentlyContinue)) {
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath (Join-Path $job.target 'Cubeon.exe') -ErrorAction SilentlyContinue
  }
  throw
}
'''

_DEB_HELPER = r'''#!/bin/sh
set -eu
parent=$1
target=$2
download=$3
digest=$4
reopen=$5
result=$6
authorize=$7
apt=$8
failed() {
  printf 'failed\nPackage update was cancelled or failed. Please try again.\n' > "$result"
  if [ "$reopen" = 1 ] && ! kill -0 "$parent" 2>/dev/null && [ -x "$target" ]; then
    export PYINSTALLER_RESET_ENVIRONMENT=1
    "$target" >/dev/null 2>&1 &
  fi
}
trap failed EXIT
remaining=120
while kill -0 "$parent" 2>/dev/null; do
  [ "$remaining" -gt 0 ] || exit 1
  sleep 1
  remaining=$((remaining - 1))
done
actual=$(sha256sum -- "$download")
[ "${actual%% *}" = "$digest" ] || exit 1
# apt resolves required system dependencies; PolicyKit presents the OS prompt.
"$authorize" "$apt" install --assume-yes -- "$download"
printf 'success\n' > "$result"
trap - EXIT
rm -f -- "$download"
if [ "$reopen" = 1 ]; then
  export PYINSTALLER_RESET_ENVIRONMENT=1
  "$target" >/dev/null 2>&1 &
fi
'''


def prepare_install(info: dict, target: InstallTarget, download: Path, *, reopen=True) -> dict:
    """Prepare a helper; preparing alone cannot replace files or run it."""
    if not target.can_install or target.asset not in {"windows", "linux", "linux-deb"}:
        raise ValueError("This installation needs a manual update.")
    asset = release_asset(info, target)
    if (not asset or download.stat().st_size != asset.get("size")
            or file_digest(download) != str(asset.get("sha256") or "").lower()):
        raise ValueError("The update download could not be verified.")
    folder = download.parent
    result = folder.parent / "install-result.txt"
    if target.asset == "windows":
        helper = folder / "install.ps1"
        helper.write_text(_WINDOWS_HELPER, encoding="utf-8")
        job = folder / "install.json"
        job.write_text(json.dumps({"pid": os.getpid(), "download": str(download),
                                  "target": str(target.path), "sha256": asset["sha256"],
                                  "reopen": reopen, "asset": target.asset, "result": str(result),
                                  }), encoding="utf-8")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(helper), str(job)]
    else:
        helper = folder / "install.sh"
        helper.write_text(_DEB_HELPER if target.asset == "linux-deb" else _APPIMAGE_HELPER,
                          encoding="utf-8")
        command = ["sh", str(helper), str(os.getpid()), str(target.path), str(download),
                   asset["sha256"], "1" if reopen else "0", str(result)]
        if target.asset == "linux-deb":
            authorize, apt = shutil.which("pkexec"), shutil.which("apt-get")
            if not authorize or not apt:
                raise ValueError("This system needs a manual package update.")
            command += [authorize, apt]
    return {"command": command, "log": str(folder / "install.log"), "result": str(result)}


def take_install_failure(directory=None) -> str | None:
    if directory is None:
        from .paths import CUBEON_HOME
        directory = Path(CUBEON_HOME) / "updates"
    result = Path(directory) / "install-result.txt"
    try:
        message = result.read_text(encoding="utf-8-sig").strip()
        result.unlink()
        if message.startswith("failed"):
            return message.partition("\n")[2] or "The last update did not finish. Please try Update again."
    except OSError:
        pass
    return None


def launch_install(job: dict):
    """Called by the session exit path, after the Flet client is cleaned up."""
    options = {}
    if os.name == "nt":
        options["creationflags"] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                                    | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        options["start_new_session"] = True
    try:
        if job.get("result"):
            # A helper killed before it can report must leave a retryable
            # failure, rather than making an interrupted update disappear.
            Path(job["result"]).write_text("failed\nThe last update did not finish. Please try Update again.", encoding="utf-8")
        with open(job["log"], "ab") as output:
            return subprocess.Popen(job["command"], stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=output, **options)
    except Exception:
        if job.get("result"):
            Path(job["result"]).write_text("failed\nCouldn't start the update installer. Please try again.", encoding="utf-8")
        raise

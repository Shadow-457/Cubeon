"""
Java runtimes Cubeon downloads and manages itself.

Until now Cubeon shipped no JRE: a user with no JDK installed was told
"Java 17+ wasn't found" and had to go to adoptium.net by hand. That is a
big ask for a launcher whose whole pitch is "it just works", and the Fabric
installer case was worse - it EXECUTES a jar, so it died with a raw
WinError 2 under the download button.

So: when a version is about to be installed and no Java new enough exists,
the launcher OFFERS to download a Temurin JRE (Eclipse Adoptium, the same
build everyone installs by hand) into ~/.cubeon_launcher/runtimes/<major>/.
The user is asked first, and declining leaves everything as it was.

Design notes that matter:
  - **A system Java always wins.** These runtimes are a fallback for a bare
    machine, not a replacement: launch.find_java_for_version only reaches
    them after Settings -> PATH -> JAVA_HOME -> the mll scan have all failed
    to produce something new enough, so installing one never changes what a
    user who already has Java is running.
  - **One per major, and only the ones we use.** 1.18-1.20.4 needs 17,
    1.20.5+ needs 21, 26.1+ needs 25 (see launch.required_java_major), so at
    most three downloads, each the smallest sufficient one - a too-new Java
    can itself break old Minecraft.
  - **Verified and atomic.** The archive is checked against Adoptium's own
    sha256 before anything is unpacked, unpacked into a `.part` folder, and
    only then moved into place, so an interrupted download can never leave a
    half-extracted runtime that later reports itself as usable.
  - **A JRE, not a JDK.** Minecraft only ever runs the game; it never
    compiles. A JRE is roughly a third of the download.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile

from .paths import RUNTIMES_DIR

log = logging.getLogger(__name__)

ADOPTIUM_API = "https://api.adoptium.net/v3"

# Majors we will download. Deliberately NOT every version the Adoptium API
# would happily serve: these are exactly the ones launch.required_java_major
# hands out, so the user can never end up with a runtime Cubeon will not use.
SUPPORTED_MAJORS = (8, 16, 17, 21, 25)


class JreError(RuntimeError):
    """Anything that stops a managed runtime from being installed.

    A dedicated type so the caller can tell "this failed, here's why" apart
    from an unexpected crash and phrase it in the UI accordingly.
    """


def _platform_params() -> dict[str, str]:
    """The Adoptium `os` / `architecture` query values for this machine.

    Adoptium names these differently from Python: `windows` (not win32) and
    `mac`, and it has no separate arm64 macOS target - both Apple silicon and
    Intel macs are served the x64 build, which runs under Rosetta 2 and is
    therefore correct, if not optimal, on every Mac we support.
    """
    if sys.platform.startswith("win"):
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "mac"
    else:
        os_name = "linux"
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        # Adoptium calls Linux arm64 "aarch64"; macOS has no arm64 target at
        # all, so mac always takes the x64 build (Rosetta).
        arch = "aarch64" if os_name == "linux" else "x64"
    else:
        arch = "x64"
    return {"os": os_name, "architecture": arch}


def runtime_dir(major: int) -> str:
    """Where the managed JRE for `major` lives."""
    return os.path.join(RUNTIMES_DIR, str(int(major)))


def _java_binary() -> str:
    return "java.exe" if os.name == "nt" else "java"


def managed_java(major: int) -> str | None:
    """The managed `java` executable for `major`, or None if not installed.

    The path is returned only if the file is really there; a folder left
    behind by an interrupted install has no bin/java and must never be
    reported as a working runtime.
    """
    path = os.path.join(runtime_dir(major), "bin", _java_binary())
    return path if os.path.isfile(path) else None


def installed_runtimes() -> dict[int, str]:
    """Every managed runtime on disk: {major: java path}."""
    found = {}
    try:
        entries = os.listdir(RUNTIMES_DIR)
    except OSError:
        return found
    for name in entries:
        if not name.isdigit():
            continue
        java = managed_java(int(name))
        if java:
            found[int(name)] = java
    return found


def _fetch_asset(major: int) -> dict:
    """Ask Adoptium for the latest Temurin JRE build of `major` on this OS.

    Raises JreError with a message meant for the user - a failed lookup is a
    network problem or an unsupported platform, and both need saying in
    plain words rather than as a traceback.
    """
    # Imported lazily: cubeon.net pulls in requests, and this module sits on
    # the import path of the launch flow, which must stay cheap to start.
    from . import net
    params = {"image_type": "jre", "jvm_impl": "hotspot", "vendor": "eclipse"}
    params.update(_platform_params())
    try:
        data = net.get_json(f"{ADOPTIUM_API}/assets/latest/{int(major)}/hotspot",
                            params=params)
    except Exception as ex:
        raise JreError(
            f"Couldn't reach Adoptium to download Java {major} "
            f"({ex.__class__.__name__}). Check your internet connection and "
            f"try again, or install Java yourself.") from ex
    if not data:
        plat = _platform_params()
        raise JreError(
            f"Adoptium has no Java {major} runtime for this system "
            f"({plat['os']}/{plat['architecture']}). Install Java {major} "
            f"manually and point Settings at it.")
    try:
        package = data[0]["binary"]["package"]
    except (KeyError, IndexError, TypeError) as ex:
        raise JreError(
            "Adoptium's reply didn't contain a download. Try again in a "
            "moment, or install Java yourself.") from ex
    link, checksum = package.get("link"), (package.get("checksum") or "")
    if not link:
        raise JreError("Adoptium's reply had no download link for this build.")
    return {"link": link, "name": package.get("name") or "temurin-jre",
            "sha256": checksum.strip().lower(),
            "size": int(package.get("size") or 0)}


def _extract(archive: str, dest: str) -> str:
    """Unpacks the downloaded archive into `dest`; returns the JRE home.

    Temurin ships one top-level folder (jdk-21.0.x+y) inside the archive, so
    the real home is that folder, not `dest` itself.
    """
    os.makedirs(dest, exist_ok=True)

    def _is_inside(path: str) -> bool:
        root = os.path.realpath(dest)
        target = os.path.realpath(path)
        return target == root or target.startswith(root + os.sep)

    if archive.endswith(".zip"):
        # ZipSlip: a crafted entry named "../../x" would escape dest, so
        # every member is resolved and checked before anything is written.
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not _is_inside(os.path.join(dest, member)):
                    raise JreError("The downloaded archive had an unsafe path "
                                   "in it and was not unpacked.")
            zf.extractall(dest)
    else:
        with tarfile.open(archive, "r:*") as tf:
            # Python 3.12+ has the 'data' filter, which rejects absolute
            # paths, escaping links and device files. On older runtimes fall
            # back to checking each member rather than trusting the archive.
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest, filter="data")
            else:
                for member in tf.getmembers():
                    if not _is_inside(os.path.join(dest, member.name)):
                        raise JreError("The downloaded archive had an unsafe "
                                       "path in it and was not unpacked.")
                    if member.issym() or member.islnk():
                        raise JreError("The downloaded archive contained a "
                                       "link and was not unpacked.")
                tf.extractall(dest)
    entries = [e for e in os.listdir(dest)
               if os.path.isdir(os.path.join(dest, e))]
    if not entries:
        raise JreError("The downloaded archive was empty or unexpected.")
    return entries[0] if len(entries) == 1 else dest


def install_jre(major: int, progress_cb=None, status_cb=None) -> str:
    """Downloads and installs a managed Temurin JRE for `major`.

    progress_cb(done, total) / status_cb(text) are the same shapes the
    version installer already uses, so the existing progress row can carry
    "downloading Java" without a second progress UI.

    Returns the path to the new `java` executable. Idempotent: an already
    installed runtime is returned without touching the network.
    """
    from . import net
    major = int(major)
    if major not in SUPPORTED_MAJORS:
        raise JreError(f"Cubeon doesn't ship a Java {major} runtime.")
    existing = managed_java(major)
    if existing:
        return existing

    def _status(text):
        if status_cb:
            status_cb(text)

    _status(f"Looking up Java {major}")
    asset = _fetch_asset(major)

    final_dir = runtime_dir(major)
    os.makedirs(RUNTIMES_DIR, exist_ok=True)
    # Unpack beside the target, then move in, so a folder only ever appears
    # at its final name once it is complete.
    part_dir = final_dir + ".part"
    staged_dir = final_dir + ".part.home"
    shutil.rmtree(part_dir, ignore_errors=True)
    shutil.rmtree(staged_dir, ignore_errors=True)
    try:
        with tempfile.TemporaryDirectory(dir=RUNTIMES_DIR) as tmp:
            archive = os.path.join(tmp, asset["name"])
            megabytes = asset["size"] // (1024 * 1024)
            _status(f"Downloading Java {major}"
                    + (f" ({megabytes} MB)" if megabytes else ""))

            def _on_progress(done, total):
                if progress_cb:
                    progress_cb(done, total or asset["size"] or 1)

            net.download_to(
                archive, asset["link"],
                expected_hash=("sha256", asset["sha256"]) if asset["sha256"] else None,
                progress_cb=_on_progress)

            _status(f"Unpacking Java {major}")
            home = _extract(archive, part_dir)
            java = os.path.join(part_dir, home, "bin", _java_binary())
            if not os.path.isfile(java):
                raise JreError("The downloaded Java didn't contain a java "
                               "executable. Nothing was installed.")
            # Zip payloads can arrive without the exec bit that tar preserves.
            try:
                os.chmod(java, os.stat(java).st_mode
                         | stat.S_IXUSR | stat.S_IXGRP)
            except OSError:
                pass

            # Promote the JRE home itself to the final name. The archive wraps
            # it in a versioned folder ("jdk-17.0.20.1+1-jre"), and
            # managed_java() looks for runtimes/<major>/bin/java - so moving
            # only part_dir would leave the runtime one level too deep and it
            # would read as not installed even though it is. Move the home out
            # first, then drop whatever the archive left around it.
            staged = staged_dir
            shutil.rmtree(staged, ignore_errors=True)
            os.replace(os.path.join(part_dir, home), staged)
            # Replace a leftover from an earlier crashed attempt first;
            # os.replace cannot overwrite a non-empty directory.
            shutil.rmtree(final_dir, ignore_errors=True)
            os.replace(staged, final_dir)
            shutil.rmtree(part_dir, ignore_errors=True)
    except JreError:
        shutil.rmtree(part_dir, ignore_errors=True)
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    except Exception as ex:
        shutil.rmtree(part_dir, ignore_errors=True)
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise JreError(
            f"Installing Java {major} failed ({ex.__class__.__name__}). "
            f"Nothing was changed - try again, or install Java yourself.") from ex

    java = managed_java(major)
    if not java:
        raise JreError(f"Java {major} did not install correctly.")
    _status(f"Java {major} ready")
    return java


def java_status(mc_version: str, java_path: str | None = None) -> dict:
    """Whether this machine can run `mc_version`, and if not, why.

    Returns {"ok": bool, "required": int, "found": int|None}. "ok" is the
    only thing the caller acts on; the rest is for the message.

    The answer is derived from the SAME resolution the launcher will actually
    use (find_java_for_version + the too-old probe mod_loaders.loader_java
    does), not a second guess, so we never prompt for a Java the launcher
    would then refuse to use.
    """
    from .launch import (find_java_for_version, java_major_version,
                         required_java_major)
    required = required_java_major(mc_version)
    result = {"ok": False, "required": required, "found": None}
    try:
        java = find_java_for_version(mc_version, java_path)
    except Exception:
        return result
    if not java or not (os.path.isfile(java) or shutil.which(java)):
        return result
    try:
        probed = java_major_version(java)
    except Exception:
        probed = None
    # An unprobeable binary counts as usable, deliberately: a path we cannot
    # run must not become a new way to fail, and the real check happens when
    # the game starts.
    if probed is None or probed >= required:
        result.update(ok=True, found=probed)
    else:
        result["found"] = probed
    return result




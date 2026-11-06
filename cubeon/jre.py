"""
Java runtimes Cubeon downloads and manages itself.

Install first checks for a runnable, compatible Java. If none is available,
Cubeon prepares a verified Temurin or Azul Zulu JRE through a locally measured
download route into ~/.cubeon_launcher/runtimes/<major>/.

Design notes that matter:
  - **A system Java always wins.** These runtimes are a fallback for a bare
    machine, not a replacement: launch.find_java_for_version only reaches
    them after Settings -> PATH -> JAVA_HOME -> the mll scan have all failed
    to produce something new enough, so installing one never changes what a
    user who already has Java is running.
  - **One per major, and only the ones we use.** We support 8, 16, 17, 21
    and 25 (see launch.required_java_major), each the smallest sufficient one - a too-new Java
    can itself break old Minecraft.
  - **Verified and atomic.** The archive is checked against its vendor's
    sha256 before anything is unpacked, unpacked into a `.part` folder, and
    only then moved into place, so an interrupted download can never leave a
    half-extracted runtime that later reports itself as usable.
  - **A JRE, not a JDK.** Minecraft only runs the game; it never compiles.
  - **Retry without starting over.** java_downloads keeps partial archives
    by checksum; vendor changes cannot append different bytes to them.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import sys
import tarfile
import threading
import zipfile

from .paths import RUNTIMES_DIR

log = logging.getLogger(__name__)

ADOPTIUM_API = "https://api.adoptium.net/v3"

# Majors we will download. Deliberately NOT every version the Adoptium API
# would happily serve: these are exactly the ones launch.required_java_major
# hands out, so the user can never end up with a runtime Cubeon will not use.
SUPPORTED_MAJORS = (8, 16, 17, 21, 25)
_INSTALL_LOCKS = {major: threading.Lock() for major in SUPPORTED_MAJORS}


class JreError(RuntimeError):
    """Anything that stops a managed runtime from being installed.

    A dedicated type so the caller can tell "this failed, here's why" apart
    from an unexpected crash and phrase it in the UI accordingly.
    """


def _platform_params() -> dict[str, str]:
    """Vendor platform names, including native Apple silicon and Windows ARM."""
    if sys.platform.startswith("win"):
        os_name = "windows"
    elif sys.platform == "darwin":
        os_name = "mac"
    else:
        os_name = "linux"
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine in ("x86", "i386", "i486", "i586", "i686"):
        arch = "x86"
    elif machine in ("", "x64", "x86_64", "amd64"):
        arch = "x64"
    else:
        raise JreError(f"Managed Java is unavailable for this processor ({machine}). "
                       "Choose a working Java installation in Settings.")
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
                            params=params, timeout=(3, 5), attempts=1)
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
            "size": int(package.get("size") or 0), "provider": "Eclipse Temurin"}


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
    home = entries[0] if len(entries) == 1 else dest
    mac_home = os.path.join(home, "Contents", "Home")
    return mac_home if os.path.isfile(os.path.join(dest, mac_home, "bin", _java_binary())) else home


def _probe_version(java_path: str) -> int | None:
    """Runs the binary and returns its actual Java major, or None.

    The download is sha256-verified and the archive checked for path escapes,
    but neither can catch a TRUNCATED EXTRACT: an interrupted unpack can leave
    bin/java present while lib/modules is missing, and that binary exists but
    cannot run (this exact failure mode ate a real JDK 25 install on the dev
    box - see the module map). So before a runtime is allowed to call itself
    installed, it must actually execute and report its version.
    """
    try:
        from .launch import java_major_version
    except Exception:
        # A lazy-import failure must not turn a working runtime into an error
        # path; fall back to a minimal direct probe.
        import re
        import subprocess
        from .winproc import hidden
        try:
            result = subprocess.run([java_path, "-version"], capture_output=True,
                                    text=True, timeout=8, **hidden())
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        out = (result.stderr or "") + "\n" + (result.stdout or "")
        m = re.search(r'version "([^"]+)"', out)
        if not m:
            return None
        raw = m.group(1)
        if raw.startswith("1."):
            tail = raw.split(".")[1] if len(raw.split(".")) > 1 else ""
            return int(tail) if tail.isdigit() else None
        head = raw.split(".")[0]
        return int(head) if head.isdigit() else None
    try:
        return java_major_version(java_path, force=True)
    except Exception:
        return None


def install_jre(major: int, progress_cb=None, status_cb=None, *, cancel_check=None) -> str:
    """Coalesce installs of the same verified managed Java major."""
    major = int(major)
    if major not in SUPPORTED_MAJORS:
        raise JreError(f"Cubeon doesn't ship a Java {major} runtime.")
    lock = _INSTALL_LOCKS[major]
    while True:
        if cancel_check:
            cancel_check()
        if lock.acquire(timeout=.25):
            break
    try:
        return _install_jre(major, progress_cb, status_cb, cancel_check=cancel_check)
    finally:
        lock.release()


def _install_jre(major: int, progress_cb=None, status_cb=None, *, cancel_check=None) -> str:
    """Downloads and installs a managed JRE through the best available route.

    progress_cb(done, total) / status_cb(text) are the same shapes the
    version installer already uses, so the existing progress row can carry
    "downloading Java" without a second progress UI.

    Returns the path to the new `java` executable. Idempotent: an already
    installed runtime is returned without touching the network.
    """
    from . import java_downloads
    major = int(major)
    if major not in SUPPORTED_MAJORS:
        raise JreError(f"Cubeon doesn't ship a Java {major} runtime.")
    def _status(text):
        if cancel_check:
            cancel_check()
        if status_cb:
            status_cb(text)

    def _progress(done, total):
        if cancel_check:
            cancel_check()
        if progress_cb:
            progress_cb(done, total)

    if cancel_check:
        cancel_check()
    existing = managed_java(major)
    if existing and _probe_version(existing) == major:
        _status(f"Java {major} ready")
        return existing

    _status(f"Choosing a Java {major} download route")
    try:
        assets = java_downloads.candidates(major, _platform_params(), lambda: _fetch_asset(major))
    except Exception as error:
        if cancel_check:
            cancel_check()
        raise JreError(f"Couldn't find a verified Java {major} download. {error}") from error

    final_dir = runtime_dir(major)
    os.makedirs(RUNTIMES_DIR, exist_ok=True)
    # Unpack beside the target, then move in, so a folder only ever appears
    # at its final name once it is complete.
    part_dir = final_dir + ".part"
    staged_dir = final_dir + ".part.home"
    shutil.rmtree(part_dir, ignore_errors=True)
    shutil.rmtree(staged_dir, ignore_errors=True)
    try:
        archive = java_downloads.download(assets, os.path.join(RUNTIMES_DIR, ".downloads"),
                                         major, _progress, _status, cancel_check=cancel_check)
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

        # The binary must actually RUN before anything is moved into
        # place. A hash-valid download can still unpack short (disk full,
        # antivirus, interrupted move) and leave a bin/java that exists
        # but cannot start; probing here keeps that from ever becoming
        # the installed runtime.
        _status(f"Verifying Java {major}")
        probed = _probe_version(java)
        if probed is None:
            raise JreError(
                f"The downloaded Java {major} could not be started - the "
                f"download or unpack was damaged. Nothing was installed; "
                f"try again, or install Java yourself.")
        if probed != major:
            raise JreError(
                f"The downloaded runtime reports Java {probed}, not "
                f"Java {major}. Nothing was installed.")

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
        # os.replace cannot overwrite a non-empty directory. The old
        # folder is moved aside rather than deleted outright, and only
        # removed once the new runtime is in place - so a failure mid
        # swap can never leave the machine with NO runtime where it had
        # one (the leftover is restored on the error path below).
        had_old = os.path.isdir(final_dir)
        old_dir = final_dir + ".old"
        if had_old:
            shutil.rmtree(old_dir, ignore_errors=True)
            try:
                os.replace(final_dir, old_dir)
            except OSError:
                old_dir = None
        try:
            os.replace(staged, final_dir)
            java = os.path.join(final_dir, "bin", _java_binary())
            final_probe = _probe_version(java)
            if final_probe != major:
                shutil.rmtree(final_dir, ignore_errors=True)
                raise JreError(f"Java {major} did not install correctly (verification failed). "
                               "Retry the installation.")
        except (OSError, JreError):
            if old_dir and not os.path.isdir(final_dir):
                try:
                    os.replace(old_dir, final_dir)
                except OSError:
                    pass
            raise
        shutil.rmtree(part_dir, ignore_errors=True)
        if old_dir:
            shutil.rmtree(old_dir, ignore_errors=True)
    except (JreError, InterruptedError):
        shutil.rmtree(part_dir, ignore_errors=True)
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    except Exception as ex:
        shutil.rmtree(part_dir, ignore_errors=True)
        shutil.rmtree(staged_dir, ignore_errors=True)
        if cancel_check:
            cancel_check()
        raise JreError(
            f"Installing Java {major} failed ({ex.__class__.__name__}). "
            "Try again, or choose a working Java installation in Settings.") from ex

    java = managed_java(major)
    if not java:
        raise JreError(f"Java {major} did not install correctly.")
    # The installed path was verified before the old runtime was retired.
    _status(f"Java {major} ready")
    return java


def java_status(mc_version: str, java_path: str | None = None, *,
                force_probe=False, cancel_check=None) -> dict:
    """Whether this machine can run `mc_version`, and if not, why.

    Returns {"ok": bool, "required": int, "found": int|None}, plus "path"
    on success and "exact" for legacy Forge. Installation and launch share
    the same executable resolution and compatibility check.
    """
    from .launch import (exact_java_major, find_java_for_version, java_major_version,
                         required_java_major)
    required = required_java_major(mc_version)
    exact = exact_java_major(mc_version)
    result = {"ok": False, "required": required, "found": None}
    if exact is not None:
        result["exact"] = True
    try:
        options = {}
        if force_probe:
            options["force_probe"] = True
        if cancel_check:
            options["cancel_check"] = cancel_check
        java = find_java_for_version(mc_version, java_path, **options)
    except InterruptedError:
        raise
    except Exception:
        if cancel_check:
            cancel_check()
        return result
    if not java or not (os.path.isfile(java) or shutil.which(java)):
        return result
    try:
        probed = java_major_version(java)
    except Exception:
        probed = None
    if probed is not None and probed >= required and (exact is None or probed == exact):
        result.update(ok=True, found=probed, path=java)
    else:
        result["found"] = probed
    return result


def ensure_java_for_version(mc_version: str, java_path: str | None = None, *,
                            progress_cb=None, status_cb=None, cancel_check=None) -> str:
    """Use verified installed Java, or automatically prepare the required runtime."""
    from .launch import required_java_major

    def status(text):
        if cancel_check:
            cancel_check()
        if status_cb:
            status_cb(text)

    required = required_java_major(mc_version)
    status(f"Checking Java {required}")
    report = java_status(mc_version, java_path, force_probe=True, cancel_check=cancel_check)
    if report.get("ok") and report.get("path"):
        status(f"Using Java {report['found']}")
        return report["path"]
    status(f"Preparing Java {required}")
    return install_jre(required, progress_cb=progress_cb, status_cb=status,
                       cancel_check=cancel_check)




"""Select shipped desktop clients and follow macOS LaunchServices processes."""
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path

_DISTROS = {
    "debian10": (2, 28), "ubuntu20.04": (2, 31),
    "ubuntu22.04": (2, 35), "debian12": (2, 36), "ubuntu24.04": (2, 39),
}
_ARCHIVE = re.compile(r"^flet-linux-([\w.]+)(-light)?-([\w]+)\.tar\.gz$")


async def wait_window_ready(window, *, platform=None, timeout=5.0):
    """Retain the desktop readiness call except on Flet's affected Mac path.

    window_manager's method resets fullscreen/maximized/minimized state; it
    is not a passive frame handshake. On macOS/Flet 0.86.5 the minimal native
    probe exits before its close request when this method is added. Mac
    reveals use to_front() directly instead, after setting hidden geometry.
    """
    if (sys.platform if platform is None else platform) != "darwin":
        await asyncio.wait_for(window.wait_until_ready_to_show(), timeout=timeout)


def configure():
    if not getattr(sys, "frozen", False) or sys.platform not in {"linux", "win32"}:
        return
    import flet_desktop

    package = Path(flet_desktop.get_package_bin_dir())
    if sys.platform == "win32":
        # The installer already contains the unpacked client. Flet expects a
        # parent of flet/flet.exe here, which avoids touching its shared cache.
        def bundled_client():
            if not (package / "flet" / "flet.exe").is_file():
                raise FileNotFoundError(
                    "Cubeon's bundled Windows desktop client is missing. Reinstall Cubeon.")
            return package

        flet_desktop.ensure_client_cached = bundled_client
        return

    requested = flet_desktop.get_artifact_filename()
    if (package / requested).is_file():
        return
    match = _ARCHIVE.fullmatch(requested)
    if match is None or match[1] not in _DISTROS:
        raise RuntimeError("Cannot select Cubeon's bundled Linux desktop client.")
    # Flet chooses an archive for the HOST glibc. A Jammy release ships the
    # Jammy archive, which also runs on newer hosts; it must stay offline.
    candidates = []
    for file in package.glob("flet-linux-*.tar.gz"):
        item = _ARCHIVE.fullmatch(file.name)
        if (item and item[1] in _DISTROS and item.groups()[1:] == match.groups()[1:]
                and _DISTROS[item[1]] <= _DISTROS[match[1]]):
            candidates.append((_DISTROS[item[1]], file.name))
    if not candidates:
        raise RuntimeError("Cubeon's bundled desktop client is missing or incompatible with this Linux system. Reinstall the Linux release.")
    selected = max(candidates)[1]
    flet_desktop.get_artifact_filename = lambda: selected


async def wait_macos_client(pid_file, launched_at, *, startup_grace=5.0):
    """Wait for Flet itself after its successful ``open -W`` helper exits.

    LaunchServices can finish the helper while its app is still running.
    Flet otherwise interprets that as the app exiting and kills its PID. The
    random, per-session PID file and creation time keep this wait scoped to
    this launch. A non-child's exit code is unavailable; never report the
    helper's zero as the native app's exit status.
    """
    import psutil

    logger = logging.getLogger(__name__)
    deadline = time.monotonic() + startup_grace
    client = None
    reason = "PID file missing or empty"
    while True:
        try:
            pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
            if pid <= 0 or pid == os.getpid():
                reason = f"invalid native PID {pid}"
                break
            candidate = psutil.Process(pid)
            if candidate.create_time() < launched_at - 1.0:
                reason = f"PID {pid} predates launch"
                break  # PID was reused by a process predating this launch.
            if not candidate.is_running() or candidate.status() == psutil.STATUS_ZOMBIE:
                reason = f"PID {pid} is no longer alive"
                break
            client = candidate
            break
        except psutil.NoSuchProcess:
            reason = f"PID {pid} no longer exists"
            break  # a PID was written, but that client already exited
        except (OSError, ValueError):
            # Dart creates the file before writing the PID; both absent and
            # briefly empty files are valid startup races.
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
        except psutil.Error:
            logger.warning("Cannot inspect macOS Flet PID file %s", pid_file,
                           exc_info=True)
            break
    if client is None:
        logger.info("macOS desktop helper exited; %s: %s", reason, pid_file)
        return None
    logger.info("macOS desktop helper exited; waiting for native Flet pid=%s pid_file=%s",
                client.pid, pid_file)
    try:
        code = await asyncio.to_thread(client.wait)
    except psutil.Error:
        logger.warning("Cannot wait for macOS Flet pid=%s", client.pid, exc_info=True)
        return None
    logger.info("macOS native Flet ended: pid=%s exit=%s", client.pid, code)
    return code

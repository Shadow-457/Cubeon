"""Cubeon's offline Rust 26.3 engine, independent of upstream release/services.

Runtime archives contain our MIT-derived executable/exporters, never Minecraft
assets. Minecraft inputs are verified official/local files, prepared locally.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlsplit
import zipfile

from . import atomicio, net, paths, storage

VERSION = "26.3"
INSTANCE_ID = "cubeon-rust-26.3"
BUILD = "26.3-beta.2"
RELEASE_BASE = f"https://github.com/Shadow-457/Cubeon/releases/download/rust-{BUILD}"
_lock = threading.RLock()


class RustEngineError(RuntimeError):
    pass


def is_instance(version_id) -> bool:
    return version_id == INSTANCE_ID


def hosting_available(version_id) -> bool:
    return not is_instance(version_id)


def platform_tag() -> str:
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise RustEngineError("Rust beta currently supports x64 Windows and Linux.")
    if platform.system() == "Windows":
        return "windows-x86_64"
    if platform.system() == "Linux":
        return "linux-x86_64"
    raise RustEngineError("Rust beta currently supports x64 Windows and Linux.")


def root() -> Path:
    return Path(paths.CUBEON_HOME) / "rust"


def _owned(path: Path) -> Path:
    base = root().absolute()
    if base.is_symlink() or any(p.is_symlink() for p in [path, *path.parents] if p != base.parent):
        raise RustEngineError("Rust engine folders must not be symbolic links.")
    if not path.absolute().is_relative_to(base):
        raise RustEngineError("Invalid Rust engine path.")
    return path


def runtime_dir() -> Path:
    return _owned(root() / "builds" / BUILD / platform_tag())


def game_dir(*, create=False) -> str:
    path = _owned(root() / "instances" / VERSION)
    if create:
        path.mkdir(parents=True, exist_ok=True)
        for name in ("saves", "config", "screenshots", "resourcepacks", "crash-reports"):
            _owned(path / name).mkdir(exist_ok=True)
    return str(path)


def resources_dir() -> Path:
    return _owned(root() / "resources" / BUILD)


def _read(path: Path) -> dict:
    try:
        if path.stat().st_size > 1024 * 1024:
            raise RustEngineError("Rust runtime metadata is too large.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def installed_entries() -> list[dict]:
    marker = _read(root() / "instance.json")
    if marker.get("engine") != "rust" or marker.get("minecraft") != VERSION:
        return []
    try:
        complete = _runtime_valid(runtime_dir(), verify=False) and _has_resource_stamp(resources_dir())
    except RustEngineError:
        complete = False
    return [{"id": INSTANCE_ID, "folder": INSTANCE_ID, "engine": "rust",
             "display_name": "26.3 (Rust · Beta)", "type": "release",
             "incomplete": not complete,
             "issue": "Rust resources need repair. Install Rust 26.3 again." if not complete else ""}]


def _has_resource_stamp(directory: Path) -> bool:
    # Earlier verified Cubeon beta bundles kept the preparer's original stamp
    # name. The bundled --check remains authoritative at install and launch;
    # the inexpensive instance scan must recognize both bundle generations.
    return any((directory / name).is_file() and not (directory / name).is_symlink()
               for name in ("cubeon-prepare.json", "horizon-prepare.json"))


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _runtime_valid(directory: Path, *, verify=True) -> bool:
    info = _read(directory / "cubeon-runtime.json")
    if (info.get("engine"), info.get("build"), info.get("minecraft")) != ("rust", BUILD, VERSION):
        return False
    files = info.get("files")
    required = {_exe("cubeon-rust"), _exe("cubeon-rust-prepare"), "research-lock.json", "LICENSE", "exporters/manifest.json"}
    if not isinstance(files, dict) or not required.issubset(files):
        return False
    for name, digest in files.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            return False
        relative = Path(name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or ":" in name or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return False
        target = directory / relative
        if any(p.is_symlink() for p in (target, *target.parents)) or not target.is_file():
            return False
        if verify:
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    return False
    return all((directory / name).is_file() for name in
               (_exe("cubeon-rust"), _exe("cubeon-rust-prepare"), "research-lock.json"))


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise RustEngineError("Install cancelled")


def _find_preparation_java(java_path=None, *, cancel=None) -> str | None:
    """Find an existing exact Java 25 without changing Java game selection.

    The pinned exporters require 25, so the normal minimum-version finder
    cannot substitute a newer JVM. Look in conventional local JDK folders
    too; manually extracted JDKs need not be registered with the OS.
    """
    from . import launch, jre

    def candidates():
        if java_path:
            yield launch._normalize_java_path(java_path)
        yield shutil.which("java")
        yield from launch._java_home_binaries()
        yield jre.managed_java(25)
        home = Path.home()
        folders = [home / "jdks", home / ".jdks", home / ".sdkman/candidates/java"]
        if os.name == "nt":
            for key in ("ProgramFiles", "ProgramFiles(x86)"):
                if os.environ.get(key):
                    base = Path(os.environ[key])
                    folders.extend(base / name for name in ("Java", "Eclipse Adoptium", "Microsoft"))
        else:
            folders.extend((Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java")))
        for folder in folders:
            _check_cancel(cancel)
            try:
                # One level only, with a fixed directory budget per root.
                with os.scandir(folder) as entries:
                    children = []
                    for index, entry in enumerate(entries):
                        if index >= 64:
                            break
                        if entry.is_dir():
                            children.append(Path(entry.path))
                # Names are hints only; every selected executable is probed.
                children.sort(key=lambda p: ("25" not in p.name, p.name))
                for child in children:
                    release = child / "release"
                    try:
                        if release.is_file() and release.stat().st_size < 65536:
                            text = release.read_text(encoding="utf-8", errors="replace")
                            version = re.search(r'^JAVA_VERSION="(\d+)', text, re.MULTILINE)
                            if version and int(version[1]) != 25:
                                continue
                    except OSError:
                        pass  # Unreadable metadata must not hide a usable JVM.
                    yield child / "bin" / _exe("java")
            except OSError:
                continue

    seen = set()
    probes = 0
    deadline = time.monotonic() + 30
    for candidate in candidates():
        _check_cancel(cancel)
        if not candidate:
            continue
        try:
            executable = Path(candidate).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if executable in seen or not executable.is_file():
            continue
        seen.add(executable)
        if probes >= 12 or time.monotonic() >= deadline:
            break
        probes += 1
        if launch.java_major_version(str(executable)) == 25:
            _check_cancel(cancel)
            # Resolve symlinks so --java-home points at the actual JDK home.
            return str(executable)
    return None


def _download_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        secure = parsed.scheme == "https" and parsed.port in (None, 443)
    except ValueError:
        return False
    if not secure or parsed.username or parsed.password:
        return False
    if parsed.hostname == "github.com":
        return url.startswith(RELEASE_BASE + "/")
    return parsed.hostname in ("release-assets.githubusercontent.com", "objects.githubusercontent.com")


def _extract(archive: Path, stage: Path):
    total = 0

    def checked(name, size):
        nonlocal total
        p = Path(name.replace("\\", "/"))
        total += size
        if p.is_absolute() or ".." in p.parts or ":" in name or total > 1024 * 1024 * 1024:
            raise RustEngineError("Invalid Rust runtime archive.")
        return stage / p

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                target = checked(item.filename, item.file_size)
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RustEngineError("Runtime archive contains a symbolic link.")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive, "r:gz") as tar:
            for item in tar:
                target = checked(item.name, item.size)
                if not (item.isfile() or item.isdir()):
                    raise RustEngineError("Runtime archive contains unsupported entries.")
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    for name in ("cubeon-rust", "cubeon-rust-prepare"):
        if (stage / name).is_file():
            (stage / name).chmod(0o755)


def _install_runtime(cancel, status_cb, progress_cb, *, local_only=False):
    target = runtime_dir()
    tag = platform_tag()
    # Development builds use the exact same verified bundle as our releases.
    checkout = Path(__file__).resolve().parents[1]
    local = checkout / "build" / "rust-engine" / tag
    local_valid = _runtime_valid(local)
    # Playing an installed build may refresh verified checkout artifacts, but
    # must never turn a normal launch into a release download.
    if local_only and not local_valid:
        return target
    if _runtime_valid(target):
        # A source checkout may rebuild the same beta while it is developed.
        # Distributed installs still use their immutable release build.
        if not local_valid or _read(local / "cubeon-runtime.json").get("files") == _read(target / "cubeon-runtime.json").get("files"):
            return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=target.parent) as temp:
        stage = Path(temp) / "runtime"
        stage.mkdir()
        if local_valid:
            status_cb("Installing Cubeon Rust build")
            shutil.copytree(local, stage, dirs_exist_ok=True)
        else:
            status_cb("Downloading Cubeon Rust beta")
            try:
                manifest = net.get_json(RELEASE_BASE + "/manifest.json", timeout=20, attempts=1)
            except net.HTTPStatusError as ex:
                if ex.status_code == 404:
                    raise RustEngineError("The Cubeon Rust beta download is not available yet. Retry after the Rust release is published.") from ex
                raise RustEngineError("Couldn't download Cubeon Rust beta metadata. Please retry. " + str(ex)) from ex
            except Exception as ex:
                raise RustEngineError("Couldn't connect to the Cubeon Rust download server. Check your connection and retry.") from ex
            item = (manifest.get("platforms") or {}).get(tag) if isinstance(manifest, dict) else None
            if not isinstance(item, dict):
                raise RustEngineError("No Cubeon Rust beta build is available for this platform.")
            url, digest = item.get("url", ""), item.get("sha256", "")
            size = item.get("size")
            if (not isinstance(size, int) or not 0 < size <= 1024 * 1024 * 1024
                    or manifest.get("build") != BUILD or manifest.get("minecraft") != VERSION
                    or not isinstance(url, str) or not isinstance(digest, str)
                    or not _download_url(url) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise RustEngineError("Invalid Cubeon Rust release metadata.")
            archive = Path(temp) / "runtime.archive"

            def progress(done, total):
                _check_cancel(cancel)
                if done > size:
                    raise RustEngineError("Rust runtime download exceeds its manifest size.")
                progress_cb(done / (total or max(done, 1)))
            net.download_to(str(archive), url, expected_hash=("sha256", digest),
                            progress_cb=progress, url_validator=_download_url)
            if archive.stat().st_size != item.get("size"):
                raise RustEngineError("Cubeon Rust archive size does not match its manifest.")
            _extract(archive, stage)
        _check_cancel(cancel)
        if not _runtime_valid(stage):
            raise RustEngineError("Cubeon Rust runtime failed verification.")
        previous = target.with_name(target.name + ".previous")
        if previous.exists():
            shutil.rmtree(_owned(previous))
        if target.exists():
            target.rename(previous)
        try:
            stage.rename(target)
        except BaseException:
            if previous.exists() and not target.exists():
                previous.rename(target)
            raise
    return target


def child_environment(username: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HORIZON_")}
    from .incident import client_environment
    env = client_environment(env)
    for key in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "LIBGL_DRM_DEVICE", "CUBEON_GPU_RESTARTS", "CUBEON_USER_RENDERING"):
        env.pop(key, None)
    if username is not None:
        env["CUBEON_RUST_PLAYER_NAME"] = username
        from .config import stable_uuid
        env["CUBEON_RUST_PLAYER_UUID"] = stable_uuid()
    return env


def _run(command, *, cancel=None, status_cb=lambda _: None, progress_cb=lambda _: None,
         timeout=1800, allow_failure=False):
    from .winproc import hidden
    _check_cancel(cancel)
    lines = queue.Queue(maxsize=256)
    finished = threading.Event()
    tail = []
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=child_environment(),
                               text=True, encoding="utf-8", errors="replace",
                               start_new_session=os.name != "nt", **hidden())

    def read():
        try:
            for line in process.stdout:
                try:
                    lines.put_nowait(line[-4096:])
                except queue.Full:
                    try:
                        lines.get_nowait()
                    except queue.Empty:
                        pass
                    lines.put_nowait(line[-4096:])
        finally:
            finished.set()
    reader = threading.Thread(target=read, name="rust-prepare-output", daemon=True)
    reader.start()
    end = time.monotonic() + timeout
    try:
        while True:
            _check_cancel(cancel)
            if time.monotonic() > end:
                raise RustEngineError("Rust preparation timed out. Retry installation.")
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if finished.is_set():
                    break
                continue
            tail.append(line.strip())
            tail[:] = tail[-12:]
            try:
                data = json.loads(line)
            except ValueError:
                data = {}
            if isinstance(data, dict) and "fraction" in data:
                try:
                    fraction = float(data["fraction"])
                except (ValueError, TypeError):
                    continue
                progress_cb(max(0, min(1, fraction)))
            if isinstance(data, dict) and data.get("message"):
                status_cb(str(data["message"]))
        code = process.wait(timeout=10)
        if code and not allow_failure:
            raise RustEngineError("Rust preparation failed: " + "\n".join(tail)[-2500:])
        return code
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, **hidden())
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        reader.join(timeout=2)
        process.stdout.close()


def install(*, cfg=None, cancel=None, status_cb=lambda _: None,
            progress_cb=lambda _: None, max_cb=lambda _: None):
    from .versions import _active_install
    with _lock, _active_install(INSTANCE_ID):
        _check_cancel(cancel)
        runtime = _install_runtime(cancel, status_cb, progress_cb)
        preparer = str(runtime / _exe("cubeon-rust-prepare"))
        resources = resources_dir()
        resources.mkdir(parents=True, exist_ok=True)
        max_cb(1)
        if _run([preparer, "--check", "--output", str(resources)], cancel=cancel,
                timeout=30, allow_failure=True):
            _check_cancel(cancel)
            from . import versions, jre
            status_cb("Getting Minecraft 26.3 resource files")
            versions.install_version(VERSION, progress_cb, status_cb, max_cb,
                                     cancel_event=cancel, explicit_java=True)
            version_dir = Path(storage.runtime_dir()) / "versions" / VERSION
            info = _read(version_dir / (VERSION + ".json"))
            server = (info.get("downloads") or {}).get("server") or {}
            server_jar = _owned(root() / "inputs" / "server-26.3.jar")
            server_jar.parent.mkdir(parents=True, exist_ok=True)
            if (not _official_url(server.get("url", ""))
                    or not re.fullmatch(r"[0-9a-f]{40}", server.get("sha1", ""))):
                raise RustEngineError("Minecraft 26.3 server resource metadata is missing.")
            status_cb("Getting the 26.3 world resource input")
            _check_cancel(cancel)
            max_cb(1)
            cached = False
            if server_jar.is_file():
                with server_jar.open("rb") as stream:
                    cached = hashlib.file_digest(stream, "sha1").hexdigest() == server["sha1"]
            if not cached:
                net.download_to(str(server_jar), server["url"], expected_hash=("sha1", server["sha1"]),
                                progress_cb=lambda done, total: (_check_cancel(cancel), progress_cb(done / (total or max(done, 1)))),
                                url_validator=_official_url)
            status_cb("Checking installed Java 25 for Rust resource preparation")
            java = _find_preparation_java((cfg or {}).get("java_path"), cancel=cancel)
            if not java:
                max_cb(1)
                status_cb("Preparing Rust assets · getting Java 25 (one time)")
                def java_status(text):
                    _check_cancel(cancel)
                    if text.startswith(("Looking up", "Unpacking", "Verifying", "Installing")):
                        max_cb(1)
                    status_cb("Rust resource preparation · " + text)
                java = jre.install_jre(25, status_cb=java_status,
                                       progress_cb=lambda done, total: (_check_cancel(cancel),
                                           progress_cb(done / (total or max(done, 1)))))
            status_cb("Preparing Rust world resources")
            max_cb(1)
            with tempfile.TemporaryDirectory(prefix="prepare-", dir=resources.parent) as temp:
                stage = Path(temp) / "resources"
                _run([preparer, "--prepare", "--complete", "--progress", "json",
                      "--minecraft-dir", storage.runtime_dir(), "--server-jar", str(server_jar),
                      "--java-home", str(Path(java).parent.parent), "--output", str(stage)],
                     cancel=cancel, status_cb=status_cb, progress_cb=progress_cb)
                _check_cancel(cancel)
                _run([preparer, "--check", "--output", str(stage)],
                     cancel=cancel, timeout=30)
                if not _has_resource_stamp(stage):
                    raise RustEngineError("Rust resource preparation did not finish. Retry the installation.")
                previous = _owned(resources.with_name(resources.name + ".previous"))
                if previous.exists():
                    shutil.rmtree(previous)
                resources.rename(previous)
                try:
                    stage.rename(resources)
                except BaseException:
                    previous.rename(resources)
                    raise
        _check_cancel(cancel)
        if not _has_resource_stamp(resources):
            raise RustEngineError("Rust resource preparation did not finish. Retry the installation.")
        game_dir(create=True)
        atomicio.write_json(str(_owned(root() / "instance.json")),
                            {"engine": "rust", "minecraft": VERSION, "build": BUILD})


def launch_command(username: str, width: int, height: int) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", username):
        raise RustEngineError("Use a player name with 1–16 letters, numbers or underscores.")
    entries = installed_entries()
    if not entries or entries[0]["incomplete"]:
        raise RustEngineError("Install Rust 26.3 from Instances before playing.")
    directory = _install_runtime(None, lambda _: None, lambda _: None, local_only=True)
    if not _runtime_valid(directory):
        raise RustEngineError("Rust runtime needs repair. Install Rust 26.3 again.")
    _run([str(directory / _exe("cubeon-rust-prepare")), "--check", "--output", str(resources_dir())], timeout=30)
    return [str(directory / _exe("cubeon-rust")), "--resources", str(resources_dir()),
            "--game-dir", game_dir(create=True), "--home", game_dir(),
            "--width", str(int(width)), "--height", str(int(height))]


def uninstall():
    """Forget installation, preserving native worlds/settings and shared inputs."""
    marker = _owned(root() / "instance.json")
    if marker.exists():
        marker.unlink()


def _official_url(url) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == "piston-data.mojang.com"
            and port in (None, 443) and not parsed.username and not parsed.password)

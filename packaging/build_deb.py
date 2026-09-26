"""Build a Debian package from the verified Linux AppDir.

This does not require dpkg-deb or fpm: it writes the standard ar archive and
gzip-compressed control/data tarballs directly, making it usable on Arch and
other Linux build hosts.
"""
from __future__ import annotations

import io
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPDIR = ROOT / "dist" / "AppDir"
DESKTOP = ROOT / "packaging" / "linux" / "cubeon.desktop"


def _app_version() -> str:
    """The launcher's version, read from cubeon/updater.py.

    This used to be a hardcoded "1.0.0" in BOTH the control file and the output
    filename, so every published .deb claimed to be 1.0.0 no matter what
    APP_VERSION said - it silently drifted a full minor version behind
    (packman/apt show the version, and dpkg would refuse a same-version
    upgrade). Read the same literal the Windows installer reads, via regex on
    the SOURCE rather than an import, so building a package never needs
    cubeon.updater's dependencies.
    """
    try:
        src = (ROOT / "cubeon" / "updater.py").read_text(encoding="utf-8")
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
        if m and re.fullmatch(r"\d+(\.\d+)*", m.group(1)):
            return m.group(1)
    except OSError:
        pass
    return "1.0.0"


VERSION = _app_version()
OUTPUT = ROOT / "dist" / f"cubeon_{VERSION}_amd64.deb"


def _tar_bytes(files: dict[str, bytes], directories: list[str] = ()) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", compresslevel=9) as archive:
        for directory in directories:
            info = tarfile.TarInfo(directory.rstrip("/") + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name in {"postinst", "prerm"} else 0o644
            archive.addfile(info, io.BytesIO(content))
    return out.getvalue()


def _ar_header(name: str, size: int) -> bytes:
    if len(name) > 15:
        raise ValueError(f"ar member name too long: {name}")
    header = (
        f"{name + '/':-<16}"
        f"{0:<12}{0:<6}{0:<6}{'100644':<8}{size:<10}`\n"
    ).encode("ascii")
    if len(header) != 60:
        raise AssertionError(len(header))
    return header


def _add_ar_member(out: io.BytesIO, name: str, content: bytes) -> None:
    header = _ar_header(name, len(content))
    out.write(header)
    out.write(content)
    if len(content) % 2:
        out.write(b"\n")


def _add_ar_file(out: io.BytesIO, name: str, path: Path) -> None:
    size = path.stat().st_size
    out.write(_ar_header(name, size))
    with path.open("rb") as source:
        shutil.copyfileobj(source, out, length=1024 * 1024)
    if size % 2:
        out.write(b"\n")


def _copy_appdir(data_root: Path) -> None:
    binary_source = APPDIR / "usr" / "bin"
    if not (binary_source / "Cubeon").is_file():
        raise SystemExit("Missing dist/AppDir/usr/bin/Cubeon. Run build_appimage.sh first.")
    target = data_root / "opt" / "cubeon"
    shutil.copytree(binary_source, target)
    icon_target = data_root / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_target.mkdir(parents=True)
    shutil.copy2(APPDIR / "cubeon.png", icon_target / "cubeon.png")
    desktop_target = data_root / "usr" / "share" / "applications"
    desktop_target.mkdir(parents=True)
    shutil.copy2(DESKTOP, desktop_target / "cubeon.desktop")
    bin_target = data_root / "usr" / "bin"
    bin_target.mkdir(parents=True)
    launcher = bin_target / "cubeon"
    launcher.write_text("#!/bin/sh\nexec /opt/cubeon/Cubeon \"$@\"\n", encoding="utf-8")
    launcher.chmod(0o755)


def main() -> None:
    if platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This artifact is amd64; build on x86_64 or extend the architecture mapping.")
    control = (
        "Package: cubeon\n"
        f"Version: {VERSION}\n"
        "Section: games\n"
        "Priority: optional\n"
        "Architecture: amd64\n"
        "Maintainer: Cubeon\n"
        "Depends: libgtk-3-0, libglib2.0-0, libnss3, libxss1, libasound2, libgbm1\n"
        "Description: Cubeon Minecraft launcher\n"
        " A Minecraft launcher with a friends layer and Cubeon client integration.\n"
    ).encode()
    postinst = b"#!/bin/sh\nset -e\ncommand -v update-desktop-database >/dev/null 2>&1 && update-desktop-database || true\nexit 0\n"
    prerm = b"#!/bin/sh\nexit 0\n"

    with tempfile.TemporaryDirectory(prefix="cubeon-deb-") as tmp:
        root = Path(tmp)
        data_root = root / "data"
        data_root.mkdir()
        _copy_appdir(data_root)
        data_tar_path = root / "data.tar.gz"
        with tarfile.open(data_tar_path, mode="w:gz", compresslevel=6) as archive:
            archive.add(data_root, arcname=".")
        control_tar = _tar_bytes({"control": control, "postinst": postinst, "prerm": prerm})
        # BytesIO starts its cursor at 0, so the first member would OVERWRITE
        # the ar magic in the initial buffer - which is what happened: every
        # deb from this script began with "debian-binary/" instead of
        # "!<arch>\n", and ar/dpkg reject it ("file format not recognized").
        # Append AFTER the magic.
        out = io.BytesIO(b"!<arch>\n")
        out.seek(0, io.SEEK_END)
        _add_ar_member(out, "debian-binary", b"2.0\n")
        _add_ar_member(out, "control.tar.gz", control_tar)
        _add_ar_file(out, "data.tar.gz", data_tar_path)
        OUTPUT.write_bytes(out.getvalue())
    print(f"Built {OUTPUT} ({OUTPUT.stat().st_size // (1024 * 1024)} MB)")


if __name__ == "__main__":
    main()

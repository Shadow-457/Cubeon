"""Keep frozen Linux launches on the compatible desktop client we ship."""
import re
import sys
from pathlib import Path

_DISTROS = {
    "debian10": (2, 28), "ubuntu20.04": (2, 31),
    "ubuntu22.04": (2, 35), "debian12": (2, 36), "ubuntu24.04": (2, 39),
}
_ARCHIVE = re.compile(r"^flet-linux-([\w.]+)(-light)?-([\w]+)\.tar\.gz$")


def configure():
    if not getattr(sys, "frozen", False) or sys.platform != "linux":
        return
    import flet_desktop

    requested = flet_desktop.get_artifact_filename()
    package = Path(flet_desktop.get_package_bin_dir())
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

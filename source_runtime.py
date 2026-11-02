"""Select the pinned desktop runtime before importing Cubeon or Flet.

This module deliberately lives outside cubeon: importing that package resolves
the palette and imports UI code. Source startup must check dependencies first.
Packaged releases already carry their own runtime and skip this check.
"""
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


_PACKAGES = ("flet", "flet-desktop")
_REEXEC = "CUBEON_SOURCE_RUNTIME_REEXEC"
_PROBE = (
    "import importlib.metadata as m,json; "
    "print(json.dumps([m.version(n) for n in ('flet','flet-desktop')]))"
)


def runtime_versions():
    result = []
    for name in _PACKAGES:
        try:
            result.append(importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:
            result.append("missing")
    return result


def compatible(versions):
    """The Python transport and desktop client must be the same 0.86 release."""
    return (isinstance(versions, list) and len(versions) == 2
            and all(isinstance(v, str) for v in versions)
            and versions[0] == versions[1]
            and re.fullmatch(r"0\.86\.\d+", versions[0]) is not None)


def project_runtime(root):
    for name in (".venv", ".venv-build"):
        executable = Path(root) / name / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not executable.is_file():
            continue
        try:
            # Keep the venv symlink path: resolving it to /usr/bin/python
            # would discard the environment we just verified.
            probe = subprocess.run(
                [str(executable), "-I", "-c", _PROBE], capture_output=True,
                text=True, timeout=5, check=True,
            )
            if compatible(json.loads(probe.stdout)):
                return str(executable)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def ensure_source_runtime(entry):
    if getattr(sys, "frozen", False):
        return
    versions = runtime_versions()
    if compatible(versions):
        os.environ.pop(_REEXEC, None)
        return

    root = Path(entry).absolute().parent
    executable = None if os.environ.get(_REEXEC) else project_runtime(root)
    if executable:
        print(f"cubeon: Flet {versions[0]} / desktop {versions[1]} is outside "
              f"the pinned runtime; using {executable}", file=sys.stderr,
              flush=True)
        env = os.environ.copy()
        env[_REEXEC] = "1"
        try:
            os.execve(executable,
                      [executable, str(Path(entry).absolute()), *sys.argv[1:]],
                      env)
        except OSError as ex:
            print(f"cubeon: couldn't start the project runtime: {ex}",
                  file=sys.stderr)

    command = subprocess.list2cmdline if os.name == "nt" else shlex.join
    python = str(root / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"))
    print(
        f"Cubeon needs matching Flet and flet-desktop 0.86.x; found "
        f"{versions[0]} / {versions[1]}.\n"
        "Set up the project environment, then run:\n"
        f"  {command([sys.executable, '-m', 'venv', str(root / '.venv')])}\n"
        f"  {command([python, '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')])}\n"
        f"  {command([python, str(Path(entry).absolute()), *sys.argv[1:]])}",
        file=sys.stderr,
    )
    raise SystemExit(1)

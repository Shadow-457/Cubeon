"""Point HOME at a throwaway directory before importing cubeon.

cubeon.paths derives every on-disk location (the private game dir
~/.cubeon_minecraft AND the ~/.cubeon_launcher home) from HOME at import
time, and imports run paths.ensure_dirs(). A test that imports cubeon
without first redirecting HOME would create - or worse, write mods into -
the developer's real game dir. Call isolate() at the very top of a test,
before any `from cubeon import ...`:
    import _sandbox_home
    _sandbox_home.isolate()
"""
import os
import tempfile


def isolate() -> str:
    home = tempfile.mkdtemp(prefix="cubeon-test-home-")
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    return home

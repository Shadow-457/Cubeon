"""Per-instance resourcepack/shader isolation - the 2026-09-17 bug report:
"if I change my instance, my resource packs and shaders don't change, they
stay the same - only mods do."

The fix gives packs/shaders the same per-instance model mods already had:
a global store, a (version, loader) profile of links, and a launch-time
staging step (sync_content_to_game) that rebuilds the game folder from the
active profile. This test locks all three behaviors in:

  1. installing into instance A is invisible to instance B (list_content)
  2. launching A stages the pack into the game folder
  3. launching B removes it from the game folder (never deleting the store
     copy), and launching A again brings it back
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-content-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import content as c  # noqa: E402  (after the env isolation)

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' - ' + extra) if extra and not ok else ''}")


# A minimal valid resourcepack zip.
zp = os.path.join(_home, "TestPack.zip")
with zipfile.ZipFile(zp, "w") as z:
    z.writestr("pack.mcmeta",
               '{"pack":{"pack_format":15,"description":"isolation test"}}')

A = ("1.20.1", "fabric")     # instance A: version+loader
B = ("1.21.11", "fabric")    # instance B: different version, same loader

linked = c.install_local_content("resourcepack", zp, mc_version=A[0],
                                 loader=A[1])
check("install_local_content returns the linked filename", bool(linked))

la = [i["filename"] for i in c.list_content("resourcepack", A[0], loader=A[1])]
lb = [i["filename"] for i in c.list_content("resourcepack", B[0], loader=B[1])]
check("instance A sees the pack", la == ["TestPack.zip"], str(la))
check("instance B does NOT see it (the reported bug)", lb == [], str(lb))

game = c._cfg("resourcepack")["dir"]


def staged():
    return [f for f in os.listdir(game) if not f.startswith(".")]


c.sync_content_to_game(*A)
s1 = staged()
check("launching A stages the pack into the game folder",
      s1 == ["TestPack.zip"], str(s1))

c.sync_content_to_game(*B)
s2 = staged()
check("launching B clears the game folder of A's pack",
      s2 == [], str(s2))

la2 = [i["filename"] for i in c.list_content("resourcepack", A[0], loader=A[1])]
check("the store copy survived B's launch (nothing deleted)",
      la2 == ["TestPack.zip"], str(la2))

c.sync_content_to_game(*A)
s3 = staged()
check("launching A again brings the pack back", s3 == ["TestPack.zip"], str(s3))

# Delete removes the pack from A's profile only; the store copy is kept by
# design, but the listing for A must now be empty.
c.delete_content("resourcepack", "TestPack.zip", A[0], loader=A[1])
la3 = [i["filename"] for i in c.list_content("resourcepack", A[0], loader=A[1])]
check("delete_content removes it from the instance", la3 == [], str(la3))

c.sync_content_to_game(*A)
check("and the next launch stages nothing", staged() == [])

from pathlib import Path
from unittest.mock import patch
from cubeon import mods

missing_profile = mods.resolve_profile_dir("not-installed", "fabric")
check("mod scan is read-only", mods.list_mods("not-installed", "fabric") == []
      and not os.path.exists(missing_profile))
check("content scan is read-only", c.list_content("resourcepack", "not-installed", loader="fabric") == []
      and not os.path.exists(missing_profile))
for copying in (False, True):
    name = "SameCopy.zip" if copying else "SameLink.zip"
    for profile, data in ((A, b"first"), (B, b"second")):
        Path(c.profile_dir("resourcepack", *profile), name).write_bytes(data)
    with patch.object(c.os, "link", side_effect=OSError("copy fallback")) if copying else patch.object(c.os, "link", wraps=c.os.link):
        c._sync_content_type("resourcepack", *A)
        c._sync_content_type("resourcepack", *B)
        check(f"same filename switches bytes (copy={copying})",
              Path(game, name).read_bytes() == b"second")
        c._sync_content_type("resourcepack", *A)
        check(f"same filename switches back (copy={copying})",
              Path(game, name).read_bytes() == b"first")

source = Path(_home, "Interrupted.zip")
source.write_bytes(b"complete payload")
def partial_copy(src, dst):
    Path(dst).write_bytes(b"partial")
    raise OSError("copy interrupted")
with patch.object(c.shutil, "copyfile", side_effect=partial_copy):
    try:
        c._store_entry("resourcepack", str(source))
    except OSError:
        pass
check("failed store copy never publishes partial final bytes",
      not Path(c.store_dir("resourcepack"), source.name).exists())
check("failed store copy cleans unique temporary sibling",
      not any(n.startswith(".store-") for n in os.listdir(c.store_dir("resourcepack"))))
check("retry stores complete bytes", Path(c._store_entry("resourcepack", str(source))).read_bytes() == source.read_bytes())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
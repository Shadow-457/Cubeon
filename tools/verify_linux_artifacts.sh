#!/usr/bin/env bash
# Verify the freshly built Linux artifacts BEFORE clobbering them to a release:
#
#   PATH="$PWD/.venv-build/bin:$PATH" bash packaging/build_appimage.sh
#   PATH="$PWD/.venv-build/bin:$PATH" python packaging/build_linux_installers.py
#   bash tools/verify_linux_artifacts.sh
#
# Cheap, offline, and reads the ARTIFACTS rather than the source tree, so it
# catches the failure that matters: "I rebuilt it, but the old code is inside".
# It is NOT named test_*.py, so CI's `for t in tools/test_*.py` loop ignores it -
# which is correct, since CI never builds these (the AppImage is a local,
# maintainer-only build).
set -u
cd "$(dirname "$(dirname "$(readlink -f "$0")")")" || exit 1

DIST=dist
# Read the expected version from the release-bump module instead of hardcoding
# it, or this guard rots the moment APP_VERSION moves.
PY="$PWD/.venv-build/bin/python"
if [ -x "$PY" ]; then
  APP_VERSION="$("$PY" -c 'import sys;sys.path.insert(0,".");from cubeon.updater import APP_VERSION;print(APP_VERSION)')"
else
  echo "!! .venv-build/bin/python missing - the build venv is required" >&2
  exit 2
fi

APPIMAGE="$DIST/Cubeon-x86_64.AppImage"
DEB="$DIST/cubeon_${APP_VERSION}_amd64.deb"
SETUP="$DIST/Cubeon-Linux-x86_64-Setup.sh"
fails=0
ok()  { printf '  ok   %s\n' "$1"; }
bad() { printf ' FAIL  %s\n' "$1"; fails=$((fails+1)); }

echo "=== 0. expected version (from cubeon/updater.py): $APP_VERSION ==="

echo
echo "=== 1. artifacts exist and are non-trivial ==="
for f in "$APPIMAGE" "$DEB" "$SETUP"; do
  if [ -s "$f" ]; then ok "$(basename "$f") $(stat -c%s "$f") bytes"; else bad "MISSING/EMPTY $f"; fi
done
[ "$fails" -eq 0 ] || { echo; echo "$fails CHECK(S) FAILED"; exit 1; }

echo
echo "=== 2. the .deb control says the version the release expects ==="
# build_deb.py writes the control from updater.APP_VERSION, so this is the one
# place the version is readable from a built artifact without unpacking python.
# The build script avoids dpkg-deb on purpose (it must work on Arch), so this
# test cannot assume it either - fall back to plain `ar` + tar. The tar member
# is `control`, NOT `./control`.
deb_field() {
  if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb -f "$DEB" "$1" 2>/dev/null
  else
    ar p "$DEB" control.tar.gz 2>/dev/null | tar -xzO control 2>/dev/null \
      | awk -F': ' -v k="$1" '$1==k{print $2}'
  fi
}
ver=$(deb_field Version); pkg=$(deb_field Package)
[ "$ver" = "$APP_VERSION" ] && ok "deb control Version = $ver" \
  || bad "deb Version = '$ver' (want $APP_VERSION)"
[ "$pkg" = "cubeon" ] && ok "deb Package = $pkg" || bad "deb Package = '$pkg'"

echo
echo "=== 3. the AppImage really carries THIS tree's assets ==="
# appimagetool output is squashfs; extract rather than mount (no FUSE needed).
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if (cd "$TMP" && "$OLDPWD/$APPIMAGE" --appimage-extract >/dev/null 2>&1); then
  ROOT="$TMP/squashfs-root"; ok "AppImage extracted"
else
  bad "AppImage failed to extract"; ROOT=""
fi
if [ -n "$ROOT" ]; then
  JARS="$ROOT/usr/bin/_internal/assets/jars"
  n=$(ls "$JARS" 2>/dev/null | wc -l)
  [ "$n" -ge 25 ] && ok "bundled mod jars: $n" || bad "bundled mod jars: $n (want >=25)"
  # Phase 3b renamed the HUD to the Cubeon Client: any keyhud-named jar means the
  # AppImage carries a pre-rename build.
  [ -z "$(ls "$JARS" 2>/dev/null | grep -i keyhud)" ] && ok "no stale keyhud jars" \
    || bad "STALE keyhud jar present"
  cc=$(ls "$JARS" 2>/dev/null | grep -c '^cubeon-client-')
  [ "$cc" -ge 24 ] && ok "renamed cubeon-client jars: $cc" || bad "cubeon-client jars: $cc (want >=24)"
  # Without the pre-downloaded client the frozen app fetches it at first launch
  # and dies before a window opens.
  ls "$ROOT"/usr/bin/_internal/flet_desktop/app/flet-linux-*.tar.gz >/dev/null 2>&1 \
    && ok "flet client tarball bundled (no runtime download)" \
    || bad "flet client tarball NOT bundled"
  # App modules live INSIDE the executable's CArchive, not as files on disk, so
  # `find` cannot see them - the module NAME is in the archive TOC.
  grep -qa 'osnotify' "$ROOT/usr/bin/Cubeon" && ok "osnotify in archive TOC (Phase 7)" \
    || bad "osnotify missing from the archive"
  du -sh "$ROOT" 2>/dev/null | sed 's/^/       extracted size: /'
fi

echo
echo "=== 4. PROOF the build is from THIS tree: read the frozen bytecode ==="
# Jars on disk prove the ASSETS are current; this proves the CODE is. App modules
# live in the CArchive -> PYZ, whose member is "PYZ.pyz" (NOT "PYZ-00.pyz").
# The marker string must be a constant that landed in the CURRENT cycle: a build
# predating it fails here, which is the whole point. Bump it each release.
MARKER="CUBEON_SKIN_API"
if [ -n "$ROOT" ] && [ -x "$PWD/.venv-build/bin/pyi-archive_viewer" ]; then
  mkdir -p "$TMP/pyz"
  # The output path must be absolute: pyi-archive_viewer writes relative to the
  # CWD, which is the repo root here, not the temp dir.
  printf 'O PYZ.pyz\nx cubeon.csl\n%s/pyz/csl.out\nQ\n' "$TMP" | \
    "$PWD/.venv-build/bin/pyi-archive_viewer" "$ROOT/usr/bin/Cubeon" >/dev/null 2>&1
  # The verdict comes from the PYTHON EXIT CODE, not from its output: an earlier
  # version printed FAIL here yet the script still reported ALL PASSED, i.e. a
  # failing check that claimed success - the exact thing this file exists to
  # prevent.
  "$PY" - "$TMP/pyz/csl.out" "$MARKER" <<'PY'
import marshal, sys
path, marker = sys.argv[1], sys.argv[2]
try:
    raw = open(path, "rb").read()
except OSError:
    sys.exit(1)
co = None
for skip in (0, 8, 12, 16):
    try:
        co = marshal.loads(raw[skip:]); break
    except Exception:
        continue
if co is None:
    sys.exit(1)
consts = []
def walk(c):
    for k in c.co_consts:
        if isinstance(k, str): consts.append(k)
        elif hasattr(k, "co_consts"): walk(k)
walk(co)
sys.exit(0 if marker in consts else 1)
PY
  if [ $? -eq 0 ]; then
    ok "frozen cubeon.csl carries $MARKER (the build is not stale)"
  else
    bad "frozen cubeon.csl is STALE (no $MARKER) or unreadable"
  fi
else
  bad "pyi-archive_viewer unavailable - cannot prove the frozen code is current"
fi

echo
echo "=== 5. sha256 (must equal the GitHub API digest after upload) ==="
sha256sum "$APPIMAGE" "$DEB" "$SETUP" | sed 's/^/  /'
echo
echo "  compare with:  gh api repos/<owner>/<repo>/releases/tags/<tag> \\"
echo "                   --jq '.assets[]|\"\\(.name) \\(.digest)\"'"

echo
if [ "$fails" -eq 0 ]; then echo "ALL ARTIFACT CHECKS PASSED"
else echo "$fails CHECK(S) FAILED"; fi
exit $((fails > 0))

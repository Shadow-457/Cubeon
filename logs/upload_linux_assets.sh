#!/usr/bin/env bash
# Re-upload the three Linux v1.1.2 assets in parallel, each with its own log and
# exit status. A clobber DELETES the asset first, so a killed upload leaves a
# hole in the release - that is exactly what happened on the first attempt, and
# why this writes per-asset status lines the caller can check afterwards.
cd "$(dirname "$0")/.." || exit 1

rm -f logs/upload_status.txt
for a in appimage deb setup; do rm -f "logs/up-$a.log"; done

gh release upload v1.1.2 dist/Cubeon-x86_64.AppImage --clobber \
  > logs/up-appimage.log 2>&1 &
p1=$!
gh release upload v1.1.2 dist/cubeon_1.1.2_amd64.deb --clobber \
  > logs/up-deb.log 2>&1 &
p2=$!
gh release upload v1.1.2 dist/Cubeon-Linux-x86_64-Setup.sh --clobber \
  > logs/up-setup.log 2>&1 &
p3=$!

wait $p1; s1=$?
wait $p2; s2=$?
wait $p3; s3=$?

{
  echo "appimage=$s1"
  echo "deb=$s2"
  echo "setup=$s3"
} > logs/upload_status.txt
echo "done"

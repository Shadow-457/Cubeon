# 2026-10-15 — Safer managed Java; first launch runs the full mod doctor

## Ask
"make that cubeon java install much safer and better and also the fps mods
doesn't install correctly: i go to install minecraft, i click install java
too, but when it launched it gave error so i had to go to mods and click fix
problems then it fixed then i press play again."

## Diagnosis
- **Java**: `install_jre` verified the download (sha256) and the archive
  (ZipSlip), but success was declared from `bin/java` EXISTING. A truncated
  unpack leaves exactly that - a binary that cannot start (the module map
  already documents this failure mode eating a real JDK 25 on the dev box).
- **Mods**: the pre-spawn doctor ran `check_online=False` for speed; that
  skips the dependency pass and the loader/version pass. A fresh install's
  first launch is exactly when those matter, and "Fix problems" runs ONLINE -
  which is why it fixed what the launch path missed.

## Changes
- `cubeon/jre.py`: `_probe_version()` executes the binary and reads its
  major. `install_jre` probes the staged binary BEFORE the move (a probe
  failure aborts with a user-worded JreError and installs nothing) and the
  installed binary AFTER (failure removes the runtime and raises). The
  final-dir swap stages the old runtime at `<major>.old` and deletes it only
  after the new one is in place - a failed swap can no longer leave the
  machine with no runtime at all.
- `cubeon/launch.py::launch_game`: before the spawn lock, a per-profile
  first-launch check consults local_cache("first_launch_doctor",
  (mc_version, loader)); when no marker exists it runs run_doctor with
  check_online=True, reports "Fixed N mod problem(s)", and sets the marker
  (30-day max_age). The pre-spawn offline doctor is unchanged and still runs
  every launch.

## Verification
- tools/test_launch_fixes.py 113/113 (new: garbage-binary probes None, real
  java probes its major, probe runs staged+final [source guard], first launch
  online exactly once across 3 launches, later launches offline).
- test_perf_mods 75/75, test_ui_smoke 187/187, test_content_doctor 100 ok,
  test_friends_service 373/373; mega_smoke --suites 37/39 with only the two
  pre-existing FAILs (mutable-default lint, wedge_watchdog GUI suite).
- NOT verified end-to-end on a real bare machine (no box without Java here);
  the probe path is covered by the fake-binary tests.

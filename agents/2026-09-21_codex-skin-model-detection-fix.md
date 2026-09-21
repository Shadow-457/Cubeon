# 2026-09-21 — classic vs slim skin detection

The arm clipping could also come from a model mismatch: detection previously
looked at only pixel `(47, 20)`, so a classic skin with a transparent elbow
could be mislabeled slim. Detection now requires both reserved fourth arm
columns (right x=47 and left x=39, full 12-pixel heights) to be transparent
before selecting Alex/slim. Updated the network regression fixture and added
a classic false-positive guard.

Verification: `tools/test_skin_preview.py` and `tools/test_skins_net.py` pass.

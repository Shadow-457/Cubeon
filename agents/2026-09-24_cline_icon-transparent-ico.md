# assets/icon.ico: white background removed (regenerated from the PNG master) (2026-09-24)

- **Agent:** Cline
- **Date:** 2026-09-24
- **Task:** "assets/icon.ico is this possible i want the white bg of the icon to be
  removed so it becomes better"

## What it actually was
Not just a white background - the checked-in `.ico` was an **older, desaturated
render baked onto an opaque white plate** (all four corners `(255,255,255,255)`,
0 fully-transparent pixels, 32% of the 256px layer pure white). Every PNG
variant (`icon_16/32/64/128/256/512.png`) has always been correct: transparent
corners and the vivid greens. So Linux/web/AppImage showed the good art while
Windows (exe, Start Menu + Desktop shortcuts, taskbar, Flet window icon) showed
a white square around a washed-out cube.

## Fix
Regenerated the `.ico` FROM `assets/icon_512.png` (the source of truth) at
16/24/32/48/64/128/256, which also **added the 24px layer** Explorer uses for
its small-icon slot. File shrank 370 KB -> 31 KB because the old file stored
32-bit uncompressed layers under a solid background.
```
Image.open('assets/icon_512.png').convert('RGBA').save(
    'assets/icon.ico', format='ICO', sizes=[...])
```
Every layer verified: corner alpha = 0. 16/32/48px still legible on a dark
taskbar (checked a rendered strip).

## Windows artifacts rebuilt (only they embed the .ico)
AppImage/deb/desktop entry use `icon_256.png` (already transparent), so the
icon change only affects Windows: `dist/Cubeon/Cubeon.exe` + `Cubeon-Windows-
x64.zip` (11:11) and `Cubeon-Windows-x64-Setup.exe` (114 MB, 11:14) rebuilt.
Proof the new icon is embedded: a 64-byte fingerprint from the ico's
PNG-compressed 256 layer is present in the built `Cubeon.exe`, and the
white-plate bytes are not.
`packaging/Cubeon.nsi` and `build_windows*.py` already point at this one file
(`/DICON_FILE=assets/icon.ico`, `--icon=assets/icon.ico`), so nothing else had
to change. mega --static 15/0.

## Notes for the next agent
- **Never hand-edit `assets/icon.ico`** - regenerate it from
  `assets/icon_512.png` (recipe + rationale in the module map's
  "Windows icon asset" invariant). A future brand refresh that only updates the
  PNGs will leave Windows stale again unless the ico is regenerated.
- The old file is preserved in git history (`git checkout assets/icon.ico`) and
  a copy of the white-plate original was made at /tmp/icon_old_backup.ico during
  the session.

# Windows EXE cross-built under Wine — 2026-09-07

User ask: "make the windows exe and put it in dist folder".

## What I produced
- `dist/Cubeon/Cubeon.exe` (onedir, windowed, 152 MB folder)
- `dist/Cubeon-Windows-x64.zip` (122 MB portable zip, same layout as CI)
- Verified under wine: flutter engine boots, no Python tracebacks, runs
  20+ s without insta-exit. Bundled: assets/jars (2 friends jars +
  connect-spigot), templates, mod/brackets.json, and the critical
  flet-windows.zip client (38 MB) inside `_internal/flet_desktop/app/`.

## The recipe (PyInstaller cannot cross-compile; wine does it)
1. Windows embeddable Python 3.11.9 (python.org embed-amd64.zip) unpacked
   to `~/winpython/py311`.
2. **Enabled site-packages** in `python311._pth` (add `Lib\site-packages`
   + `import site`) — the default blocks pip's installs from importing.
3. `get-pip.py` under wine → pip 26.
4. `pip install -r requirements.txt pyinstaller` (all wheels have
   win_amd64 builds incl. cryptography — no compilation needed).
5. Downloaded flet-windows.zip v0.86.5 into the wine interpreter's
   `flet_desktop/app/` (same trick as packaging/build_windows.py) so
   `--collect-all flet_desktop` bundles it.
6. Ran PyInstaller from the repo root via wine with `Z:` drive paths and
   `--add-data=...;...` (**`=` syntax only — space syntax gets mangled by
   wine cmd**; also `wine cmd /c` swallowed all output, run the exe
   directly instead). `--distpath dist --workpath build/wine-win` (removed
   after).

## Durable facts for the map (next agent: copy these)
- `~/winpython/py311/python.exe` is a working Windows Python under wine —
  reusable for future Windows builds without redoing steps 1–4.
- The full wine build command is in this note; packaging/build_windows.py
  remains the CI (windows-latest) path and produces the identical layout.
- Wine quirks seen: "Problem getting numbers of monitor" (harmless),
  direct_manipulation ERROR line (harmless flutter/wine noise).

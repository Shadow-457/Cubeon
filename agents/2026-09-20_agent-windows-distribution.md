# Windows portable EXE and installer

Built `dist/Cubeon-Windows-x64-single.exe` with the Wine/WinPython
cross-build and verified it is a 64-bit PE that paints the UI in a clean Wine
prefix. Added `packaging/Cubeon.nsi` and
`packaging/build_windows_installer.py`; the resulting
`dist/Cubeon-Windows-x64-Setup.exe` installed Cubeon per-user, created the
Start Menu shortcut, and launched the installed app to the paint marker.

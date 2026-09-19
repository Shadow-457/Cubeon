# Windows and Linux release builds

Built and verified `dist/Cubeon-x86_64.AppImage` and
`dist/Cubeon-Windows-x64.zip` plus the Windows onedir folder. Both artifacts
painted successfully in isolated Linux/Wine startup checks, contain the exact
rebuilt mod jars and bundled Flet desktop client, and passed archive/PE/ELF
inspection. Hardened `packaging/build_windows.py` and the onefile builder to
use clean builds and bundle only `mod/brackets.json`, not Java/Gradle sources.

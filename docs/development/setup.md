[Documentation](../README.md) / Development

# Development setup

## Requirements

- Python 3.11, matching the release and test workflow.
- Git and a desktop session for the launcher.
- Internet access for dependency installation and uncached game downloads.

Optional tools depend on what you are changing:

| Work | Tools |
| --- | --- |
| Worker tests | Node.js 20 or newer |
| Java compile checks | A JDK with `javac`; CI uses Java 21 |
| Building mod jars | JDK 25 or newer and Gradle; see `tools/build_mod_jars.py` |
| Packaged builds | PyInstaller and the platform-specific tools in the [build guide](../release/build.md) |

The Gradle runtime and the mod's bytecode target are different: current jar
builds need a recent JDK, while the mod targets Java 17 bytecode.

## Python environment

Run from the repository root. Keep dependencies in a virtual environment;
`requirements.txt` pins Flet and its desktop client to `0.86.x`.

### Linux and macOS

```bash
git clone https://github.com/Shadow-457/Cubeon.git
cd Cubeon
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

### Windows PowerShell

```powershell
git clone https://github.com/Shadow-457/Cubeon.git
cd Cubeon
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

If activation is unavailable, use `.venv\Scripts\python.exe` directly rather
than changing the machine-wide execution policy.

On Linux, the Flet desktop client also needs the system's GTK and graphics
libraries. An import check alone does not verify that a window can open.

## Check the environment

```bash
python tools/test_mega_smoke.py --static
python tools/test_ui_smoke.py
```

These checks do not launch Minecraft or prove that desktop rendering works.
For test scope and prerequisites, see [Testing](testing.md).

## Local data

| Location | Contents |
| --- | --- |
| `~/.cubeon_launcher/` | Configuration, identity, caches, and local server data |
| `~/.cubeon_launcher/cubeon.log` | Rotating launcher log |
| `~/.cubeon_minecraft/` | Cubeon's game files |

`CUBEON_GAME_DIR` overrides the game directory. It does not isolate all
launcher state. Use `tools/launch_sandbox.py` for a separate test identity:

```bash
python tools/launch_sandbox.py TestUser
python tools/launch_sandbox.py --list
```

Never attach identity files, API tokens, or an unreviewed configuration to
an issue. Check logs for private values before sharing them.

## Debugging

```bash
python tools/debug_run.py
python tools/app_driver.py explore
```

On Linux or macOS, `CUBEON_SEASON=winter python main.py` pins the seasonal
theme for a reproducible UI check. `CUBEON_INSPECT=1 python main.py` enables
the development inspector. See the [tool reference](../../tools/README.md)
for additional helpers.

Restart the source launcher after changing Python files. Running
`python main.py` does not update an independently installed binary.

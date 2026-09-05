# Cubeon — simple owner guide

This guide is for using and maintaining Cubeon without needing to understand
its code. If a command looks scary, you can send it to me and I can help.

## What Cubeon is

Cubeon is a Minecraft launcher. It can:

- install and start Minecraft;
- manage Fabric, Forge, Quilt, and NeoForge profiles;
- install mods and modpacks;
- let Cubeon players find each other, chat, and invite each other to play;
- share skins and the Cubeon cape;
- host a world for friends through a tunnel.

There are two parts:

1. **The launcher** — the desktop app you open.
2. **The online services** — small Cloudflare services that help friends find
   each other and exchange messages. Minecraft itself still runs on your own
   computer.

## What is already online

The friends service is deployed and running at:

```text
https://cubeon-friends.hamza-457-shahbaz.workers.dev
```

The launcher is already configured to use it. You do not need to start a
server on your computer for friends chat or friend requests.

## The launcher files

| File/folder | Plain-English meaning |
|---|---|
| `dist/Cubeon-x86_64.AppImage` | Linux app you can double-click |
| `packaging/build_appimage.sh` | Makes the Linux app |
| `packaging/build_windows.py` | Makes the Windows app/ZIP |
| `packaging/build_macos.sh` | Makes the Mac app/archive |
| `assets/cube.svg` | The original Cubeon cube artwork |
| `assets/icon_*.png` and `assets/icon.ico` | Versions of that artwork for Linux/Windows |
| `assets/jars/` | Friends mod jars and Connect plugin included in builds |
| `cubeon/updater.py` | Checks whether a newer release exists |
| `~/.cubeon_launcher/cubeon.log` | Local launcher error log |

## Running Cubeon on Linux

Double-click:

```text
/home/fuckarch/Downloads/Cubeon/dist/Cubeon-x86_64.AppImage
```

If Linux asks whether to run it, choose **Run** or **Allow executing file**.

If the file is missing, the build has not finished. Build it with:

```bash
cd /home/fuckarch/Downloads/Cubeon
bash packaging/build_appimage.sh
```

Wait until the terminal says:

```text
Built dist/Cubeon-x86_64.AppImage
```

The build can take several minutes. Do not close the terminal during the
build. Keep a few GB free because temporary build files are large.

## Building the Windows app

You normally do this on a Windows computer, because PyInstaller should build
Windows apps on Windows.

1. Download the Cubeon source folder.
2. Install Python 3.11 or newer.
3. Open PowerShell in the Cubeon folder.
4. Run:

```powershell
python -m pip install -r requirements.txt pyinstaller
python packaging/build_windows.py
```

The result will be in `dist/Cubeon/` and
`dist/Cubeon-Windows-x64.zip`.

Windows may show a SmartScreen warning because the app is not code-signed.
Choose **More info**, then **Run anyway** if you trust the file.

## Building the Mac app

On a Mac, open Terminal in the Cubeon folder and run:

```bash
python3 -m pip install -r requirements.txt pyinstaller
bash packaging/build_macos.sh
```

The result will be in `dist/`.

## How updates work right now

Cubeon currently uses a safe, manual update process:

1. A new release is uploaded to GitHub.
2. The launcher checks GitHub in the background.
3. If a newer version exists, Cubeon shows **Get it**.
4. Clicking **Get it** opens the download page in your browser.
5. You download the new app.
6. You close Cubeon and replace the old app with the new one.

Cubeon does **not** secretly replace itself yet. This prevents an update from
breaking the app while it is running.

### Publishing a release

Run these commands from the Cubeon folder after making a change:

```bash
cd /home/fuckarch/Downloads/Cubeon
git add -A
git commit -m "describe the change"
git push
```

Before making a release, change the version in `cubeon/updater.py`:

```python
APP_VERSION = "1.0.1"
```

Then create a tag and release:

```bash
git tag v1.0.1
git push origin v1.0.1
gh release create v1.0.1 --generate-notes
```

The GitHub repository is private:

```text
https://github.com/Shadow-457/Cubeon
```

A private repository is good for storing your source code. It is not ideal for
giving downloads to many people because download permission is required.


## Testing friends with another person

Both people should:

1. Open Cubeon.
2. Start Minecraft.
3. Open **Cubeon Friends** in Minecraft.
4. Choose a different Cubeon name.
5. Add each other.
6. Accept the friend request.
7. Send a chat message.
8. Try **Play**.
9. Try **Sync** with a mod that one person does not have.

If something fails, write down the exact step and message. Also send the log
from each computer:

```text
~/.cubeon_launcher/cubeon.log
```

## If something breaks

### The AppImage opens an error about `icons.json`

Use a newly built AppImage. The packaging script now includes all Flet files.
Do not use an older AppImage from before the packaging fix.

### The colors look green or wrong

Use a newly built AppImage. The build now includes the `templates/` color files.
The app icon and window artwork come from `assets/cube.svg`.

### `dist/` is empty

The build did not finish. Run:

```bash
cd /home/fuckarch/Downloads/Cubeon
bash packaging/build_appimage.sh
```

Wait for `Built dist/Cubeon-x86_64.AppImage`.

### The launcher starts but Minecraft does not

Check that Java is installed, the selected version has finished installing,
the loader matches the profile, and there is enough free disk space. The log
is at `~/.cubeon_launcher/cubeon.log`.

### Friends do not connect

Both people should use the latest launcher and latest Friends mod jar. Check
the internet connection. The online friends service is already deployed; there
is no local server to start.

## Things you do not need to worry about

- You do not need to buy a Windows signing certificate for personal use.
- You do not need to run Cloudflare every time Cubeon starts.
- You do not need to manually copy Friends mod jars into the AppImage.
- You do not need to understand PyInstaller to use the finished app.
- Crash reporting is off unless it is explicitly enabled and configured.

## Technical notes

Developers and agents can read `agents/docs/module-map.md`,
`agents/docs/production-readiness-gaps.md`, `worker/README.md`, and
`agents/docs/guide-worker-backend.md`. Most users only need this file.

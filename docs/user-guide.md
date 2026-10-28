[Documentation](README.md) / User guide

# User guide

## Install and launch

Download the build for your operating system from
[cubeon.ylet.online/download](https://cubeon.ylet.online/download).
Packaged builds do not require a separate Python installation.

- **Windows:** use the setup executable, or extract the portable ZIP before
  running `Cubeon.exe`. Keep the portable folder's files together.
- **Linux:** use the provided installer or package. For an AppImage, grant
  execute permission and launch it from your file manager or terminal.
- **macOS:** extract the release archive and open the app. Unsigned builds
  may require approval through the operating system's security settings.

Only approve a security warning after checking the download's source.
Do not disable system-wide security protections to launch an app.

For a Linux AppImage downloaded to the current directory:

```bash
chmod +x Cubeon-x86_64.AppImage
./Cubeon-x86_64.AppImage
```

If you are running the source rather than a release, follow
[Development setup](development/setup.md).

## First game launch

1. Set a player name in Account. Cubeon uses local/offline profiles rather
   than Microsoft account sign-in.
2. Select a Minecraft version in Play.
3. Choose Vanilla or a loader compatible with that version.
4. Review memory and Java settings if needed, then select Play.

In **Instances**, use the small pencil on a card to choose its icon. The same
panel offers **20 blocks** and **20 mob heads**; your selection is saved per
instance. Clicking the card itself still selects the instance. Play shows the
loader as a compact tag beside the version.

The first launch downloads missing game components and can take longer.
Selecting an existing instance restores its version and loader.

An offline profile does not authenticate you to servers that require a
Microsoft/Mojang account.

## Mods, packs, and cosmetics

- **Mods:** select a compatible modded instance first. A Fabric mod does not
  work just because another loader is installed.
- **Resource packs:** work with Vanilla as well as modded instances, subject
  to Minecraft version compatibility. Enable them in the game's settings.
- **Shaders:** require a compatible loader and shader runtime, such as Iris
  or Oculus. Downloading a shader ZIP alone does not enable shaders.
- **Modpacks:** carry their own Minecraft and loader requirements. Review
  the pack's requirements before installing it.
- **Cosmetics:** manage skins, capes, and shoulder/back items in Cosmetics; drag
  the 3D preview to inspect the model. Shoulder and back items are drawn in
  game by Cubeon Client and are visible to you; skins and capes need compatible
  skin support. A selection is stored in the instance the game plays in, so
  each instance can keep a different item.
- **In-game HUD and zoom:** press K in game to open the Cubeon Client menu.
  Every overlay (FPS, keystrokes, armour, ping, CPS) has its own **Move** and
  **Size** buttons, so making the keystrokes bigger does not enlarge the FPS
  counter. The armour overlay shows only the four worn pieces, not the item in
  your hand. Hold Z and scroll the mouse wheel to zoom smoothly; release to
  return. Z can be rebound under Controls → Key Binds → Cubeon Client. Zoom is
  available on Minecraft 1.20-1.21.11; the 26.x releases use a different FOV
  system and do not have it yet.

Screenshots have a separate section in Settings. Stats shows playtime and
activity comparisons; it does not measure the game's frame rate.

### Finding a mod

Mod search shows the selected Minecraft version, loader, and category. Keep
**Compatible only** enabled to find mods for that instance. If a mod seems
missing, use **Search all Modrinth** from an empty search, or turn off
**Compatible only** and select **All** categories. Mods for other versions
or loaders remain inspectable, but their download button is unavailable.

Use a mod's name or paste its Modrinth project link into the search field.
When a full name has no matches, Cubeon tries shorter name searches and labels
them as related matches. A pasted link resolves the project directly, even
if the current filters would hide it; installation still requires a matching
Minecraft version and loader. Cubeon's built-in catalog uses Modrinth, so a
project published only elsewhere will not appear in these results.

### Fixing installed content

**Check & repair** in **Mods → Installed** runs Cubeon's local Doctor in the
background. The same button checks resource packs and shaders in their installed
views. It checks duplicate jars, required dependencies, loader/version compatibility,
declared Fabric conflicts, and supported pack structure issues. Clicking the button
authorizes reversible repairs, including fetching missing dependencies and renaming
incompatible or duplicate jars to disabled backups. Re-enable those jars in Installed.
The result appears beside the button; hover it for details of unresolved issues.

Automatic checks stay local and quiet: no approval or result windows. They leave
existing mods enabled unless you explicitly request repair. Install-time checks can
fetch missing dependencies without replacing an existing build. The permanent
**Fix crash** button has been removed from Play. Repairs requested from an actual
crash report also continue in the background.

Doctor cannot repair arbitrary bugs inside a mod or make it support an incompatible
Minecraft version. Launch-time checks remain limited to safe launcher configuration
repairs and never wait on a dialog.

### Website crash Doctor

Click **Doctor** in a crash report to open the website with a redacted log excerpt
already filled in. You can also open [Cubeon Doctor](https://cubeon.ylet.online/doctor)
and upload a `.log` or `.txt` file (up to 2 MB), or paste the error. The page shows
the likely cause, supporting log lines, and numbered visual steps pointing to the
relevant launcher controls. These are illustrations; apply each change in Cubeon
and test a fresh launch.

Local diagnosis works without an account. **Analyze with free AI** optionally uses
Kilo’s `kilo-auto/free` router through Cubeon’s server, with one retry for a
temporary failure. No visitor sign-in is needed. Quotas or outages can prevent
AI results, in which case the local guide stays available. Review the preview before sharing: automated redaction cannot catch
every private detail. AI sends the excerpt through Cubeon’s server to Kilo and its selected provider.
Free providers may log prompts and responses or use them for improvement;
remove personal or confidential information before sharing.
Large logs are shortened; your original file stays on disk. **Clear** removes the
log from the page, and **Save this guide** downloads a text copy.

## Friends and servers

Friends-enabled builds include chat and in-game integration. Some public
builds omit these features. You do not need to deploy the backend yourself
to use a build configured for Cubeon's services.

Local server hosting runs on your computer. Shared access depends on the
server and tunnel being available, and may be affected by firewall or
network settings.

## Launcher settings

In **Settings → Display → Launcher**, choose **Language** and restart Cubeon to apply
it. Arabic, English, Russian, and Spanish appear first, followed by Chinese, Hindi,
Portuguese, French, German, Japanese, Turkish, Korean, Italian, Polish, Indonesian,
Ukrainian, Urdu, Bengali, Persian, Malay, Pashto, and Roman Urdu. Core navigation and
controls are translated; detailed messages without a translation fall back to English.
Arabic, Urdu, Persian, and Pashto use a right-to-left layout.

**Custom title bar** defaults on for Windows (including Windows 10) and Linux. An
explicit saved choice to switch it off is preserved. Restart after changing it.

In **Settings → Performance → Java**, expand **Cubeon's default flags** to see the
options derived from your memory setting and hardware, with explanations and skipped
options. This readout updates when you change RAM or custom flags. Custom flags go
after defaults; choosing another garbage collector suppresses Cubeon's G1 options.

**Settings → System → Notifications → Chat messages** controls incoming message
notifications immediately. Open conversations in a focused launcher or the companion
mod suppress their alerts; old history and your own sent messages do not trigger them.

## Updates

When Cubeon offers an update, open the download page, download the new
build, close the running launcher, and install or replace the app.
The update notice does not replace the running binary automatically.

Keep the launcher closed while replacing a portable build. Updating the
app is different from deleting its data folders.

## Data and troubleshooting

| Location | Contents |
| --- | --- |
| `~/.cubeon_launcher/` | Settings, local identity, caches, and server data |
| `~/.cubeon_launcher/cubeon.log` | Launcher log |
| `~/.cubeon_minecraft/` | Cubeon's game files |

`~` means your home folder. The game path can be overridden in a development
environment. Back up worlds before removing game files, and keep identity
files private.

Each installed version plays in its own folder under
`~/.cubeon_minecraft/instances/<instance>/`. Its worlds (`saves/`), mod configs
(`config/`) and `options.txt` live there, so a world or a video setting in one
instance never shows up in another. The mod store, resource packs and shaders
stay shared and are linked into every instance folder, so installed content
still applies everywhere. Deleting an instance does not delete its world
folder; remove that folder yourself once you are sure.

If the app will not start, run it from a terminal and record the error.
For a failed game launch, check the selected version, loader, Java path,
and memory setting. For missing cosmetics, check the instance's skin support
rather than repeatedly reinstalling the launcher.

[Report an issue](https://github.com/Shadow-457/Cubeon/issues) with your
operating system, Cubeon version, steps to reproduce, and relevant log
lines. Remove tokens, identity details, usernames, and private server
addresses before attaching logs.

Building or maintaining a release is covered in the
[build guide](release/build.md), not required for normal use.

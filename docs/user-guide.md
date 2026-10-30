[Documentation](README.md) / User guide

# User guide

## Install and launch

Download the build for your operating system from
[www.ylet.online/download](https://www.ylet.online/download).
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
2. Open **Instances** in Play and select **New instance**.
3. Fabric is selected by default. Choose another loader if needed, then choose
   a compatible Minecraft version and a block or mob icon.
4. Review memory and Java settings if needed, then select **Download & Play**.

In **Instances**, use the small pencil on a card to choose its icon. The same
panel offers **20 blocks** and **20 mob heads**; your selection is saved per
instance. Clicking the card itself still selects the instance. Play shows the
loader as a compact tag beside the version.

The first launch downloads missing game components and can take longer.
Selecting an existing instance restores its version and loader.
With Discord desktop running, Rich Presence shows the Minecraft version and
loader you are playing, for example “Playing Minecraft 1.21.11 (Fabric)”.

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
- **Cosmetics:** manage skins, capes, and shoulder/back items in Cosmetics; use
  the rotation arrows to inspect the 3D model. Shoulder and Back sections are marked **Beta**.
  Shoulder and back items are drawn in
  game by Cubeon Client and are visible to you; skins and capes need compatible
  skin support. A selection is stored in the instance the game plays in, so
  each instance can keep a different item.
  In game, shoulder pets breathe and look around; wings beat slowly at rest,
  speed up smoothly when sprinting and spread during gliding. The five wing themes
  offer the original cute **Small** wings and joined **Giant** wings. Each feather
  flexes and recoils with a slight delay while its root stays attached.
  Press **N** with **Giant** wings equipped to spread them and
  play a short dragon-style wing flare; it settles back automatically. Rebind
  **Dragon Wing Flare** in Minecraft's Controls → Key Binds → Cubeon Client.
  Small wings keep their gentle normal movement and completely ignore N.
  Backpacks sway while you move. The launcher preview shows
  the resting model. Restart Minecraft after changing the companion mod.
- **In-game HUD and zoom:** press K in game to open the Cubeon Client menu.
  Each overlay (FPS, keystrokes, armour, ping, CPS) has a card with a display
  toggle, **Move**, and a clickable size percentage. Sizes are independent,
  so making the keystrokes bigger does not enlarge the FPS
  counter. The armour overlay shows only the four worn pieces, not the item in
  your hand. **Enemy Health** toggles a thin bar beneath nearby enemy names
  (players and hostile mobs). It starts off and remembers your choice; enemies
  behind walls and teammates are hidden. **Cosmetic motion** starts on;
  switch it off to keep pets, wings and packs still, including individual feather
  movement and the N flare. This skips animation calculations.
  The choice is saved. **Reset layout** restores overlay positions and sizes.
  Tab/arrows select controls; Enter activates them. In the drag editor,
  release the mouse to save and choose Done or press Enter to return.
  Hold Z to zoom in; scroll the wheel to adjust it.
  Looking around is slower and lightly smoothed while zoomed; release to return.
  Z can be rebound under Controls → Key Binds → Cubeon Client. Zoom is
  available on Minecraft 1.20-1.21.11; the 26.x releases use a different FOV
  system and do not have it yet.
- **Freelook:** hold Left Alt and move the mouse to orbit your player without
  changing your aim. Scroll up to bring the camera closer, down to move it
  farther (1–12 blocks, with normal wall collision). Release to restore your
  previous perspective. Menus and focus loss also stop freelook; press the key
  again to resume. F5 keeps the perspective you choose. Rebind Left Alt under
  Controls → Key Binds → Cubeon Client. Available in all supported client
  versions; freelook takes priority when held together with zoom.
- **Emotes:** press B, or K → Emotes, to open the circular picker. The library
  includes Wave, Dance, Bow, Salute, Shrug, Point, Clap, Laugh, Sit and Celebrate.
  Move the mouse over a wedge and click, or press 1–8. Arrows/Tab and Enter also
  work. Choose **Edit wheel** (or press E) to add or remove favorites: the wheel
  holds up to eight, saved in the order you add them. Selected entries have an
  green edge; remove one before adding another when full. Click **Done** to
  return. Esc or right click returns from editing, then closes the picker;
  click the center to stop an emote. Move, jump, attack or use an item to
  cancel. **Show Emotes** turns their display on/off and saves your choice.
  Other players running the updated Cubeon Client can see them on ordinary
  servers without a server mod. Both launchers need an online Cubeon connection
  and both players must join using the same server address. The picker shows
  whether sync is available; offline emotes remain visible to you. Unmodified
  Minecraft clients cannot display these animations.
- **Skin arms:** each uploaded skin has an **Auto / Alex / Steve** control.
  Auto detects normal skin sheets; choose **Alex · 3 px** for a slim skin
  whose editor filled its unused pixels, or **Steve · 4 px** for wide arms.
  The choice is saved for that skin. Restart Minecraft after changing it.

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
The result appears beside the button. Named details below it show unresolved
issues and, after an explicit repair, which mods changed and how.

Automatic checks stay local and quiet: no approval or result windows. They leave
existing mods enabled unless you explicitly request repair. Install-time checks can
fetch missing dependencies without replacing an existing build. The **Fix crash** buttons have been removed from Play and crash reports.
Crash reports offer the website Doctor, Copy log, and Discord support.

Doctor cannot repair arbitrary bugs inside a mod or make it support an incompatible
Minecraft version. Launch-time checks remain limited to safe launcher configuration
repairs and never wait on a dialog.

### Website crash Doctor

Click **Doctor** in a crash report to open the website with a redacted log excerpt
already filled in and on-device instructions ready. You can also open
[Cubeon Doctor](https://www.ylet.online/doctor) and upload a `.log` or `.txt`
file (up to 2 MB). Uploading starts AI analysis automatically. To paste a log or
review the uploaded text, expand the log editor and choose **Analyze log**.

The result shows the likely cause and all repair steps as a numbered Markdown
list. Mod names, dependencies and settings are named when the log identifies
them. Apply one change at a time and test a fresh launch. Expand **See the error
lines** for the evidence, or save the instructions as a `.md` file.

AI tries Groq first and falls back to Kilo’s `kilo-auto/free` router through Cubeon’s server. No visitor sign-in
is needed. AI is limited to three analyses per 30-minute window per network
address on each server instance. When the quota is reached, the page shows
how long to wait. On-device checks remain available without using AI quota.
If AI is unavailable, on-device instructions remain available; you
can also choose **Check on this device instead** in the log editor.
That check covers common mod, Java, memory, config, archive, graphics and
connection failures. When the error identifies a mod, the instructions name
it and explain how to disable it for one test and re-enable it if needed.
If ownership is unclear, Doctor asks for the full loading error instead of
guessing from a class or mixin filename. Missing dependencies get installation
instructions, rather than a suggestion to disable them.
Automated redaction cannot catch every private detail. AI shares the excerpt
with Groq and, if its analysis fails, Kilo and its selected free provider. Their
data policies apply; Kilo's free providers may retain or use it. Remove
private information before uploading, or paste and review it in the editor.
Large logs are shortened; the original file stays on disk. **Clear** removes the
log and instructions from the page.

## Friends and servers

Friends-enabled builds include chat and in-game integration. Some public
builds omit these features. You do not need to deploy the backend yourself
to use a build configured for Cubeon's services.

Local server hosting runs on your computer. Shared access depends on the
server and tunnel being available, and may be affected by firewall or
network settings.

## Launcher settings

In **Settings → Display → Launcher**, open **Language** and search by native name,
English name, or language code. Select a language, then click the **Restart** button
that appears below the saved choice to apply it. Arabic, English, Russian, and Spanish appear first, followed by Chinese, Hindi,
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
Turn off **Use Cubeon's default Java flags** to remove all Cubeon-added flags
on the next game launch. This also removes Cubeon's `-Xmx` and `-Xms` values,
so the RAM slider no longer sets the heap. Set your own heap flags in **Custom
Java flags** if needed. Minecraft and loader arguments remain required. The
switch saves immediately; no launcher restart is needed.

**Settings → System → Notifications → Chat messages** controls incoming message
notifications immediately. Open conversations in a focused launcher or the companion
mod suppress their alerts; old history and your own sent messages do not trigger them.

## Updates

Cubeon checks for a newer version when it starts. If one is available, a
prompt offers **Skip** and **Update**. Skip continues this launch; Cubeon can
offer the update again next time. Downloads start only after you choose Update.

Choose **Stable** or **Beta** in **Settings → System → Updates**. Stable is
the default; Beta also includes prereleases. The choice applies on the next launch.

Windows installations made with Cubeon's installer and Linux AppImages in
writable folders download and verify the update inside Cubeon. Cancel stops
the download. The progress bar shows the download. When it is verified,
**Restart** closes Cubeon, installs the update, and opens the new version.
Close Minecraft and stop active installs or hosted servers first. Updating the
AppImage keeps a `.cubeon-previous` copy beside it.

Portable Windows builds, macOS, source checkouts and package-managed Linux
installations offer an explicit **Download manually** action. Update never
opens a browser automatically. A missing checksum stays an error inside
Cubeon; restart the launcher to check for a verified release again.

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

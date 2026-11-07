[Documentation](README.md) / User guide

# User guide

## Install and launch

Download the build for your operating system from
[www.ylet.online/download](https://www.ylet.online/download).
Packaged builds do not require a separate Python installation.

- **Windows:** open the setup executable. It installs Cubeon and adds a Start
  menu entry without needing administrator rights.
- **Linux:** run `bash Cubeon-Linux-x86_64-Setup.sh` to install Cubeon and its
  app menu entry. The setup includes everything and supports systems without
  FUSE. Alternatively use the Debian/Ubuntu package. For an AppImage, grant
  execute permission and launch it from your file manager or terminal.
- **macOS:** untested; downloads and updates are currently unavailable.

Only approve a security warning after checking the download's source.
Do not disable system-wide security protections to launch an app.

For a Linux AppImage downloaded to the current directory:

```bash
chmod +x Cubeon-x86_64.AppImage
./Cubeon-x86_64.AppImage
```

On Wayland, a native Flet display crash can sometimes be avoided by choosing
XWayland explicitly, if your desktop provides it:

```bash
GDK_BACKEND=x11 ./Cubeon-x86_64.AppImage
```

Cubeon preserves explicit GTK/EGL/renderer environment choices through crash
recovery, including when an old software-rendering fallback marker exists.
Automatic recovery still has a two-restart limit. An `eglGetPlatformDisplayEXT`
provider error can also indicate unavailable or mismatched EGL libraries in a
container; a backend override does not repair missing system libraries.

If you are running the source rather than a release, follow
[Development setup](development/setup.md).

## First game launch

1. Set a player name in Account. Cubeon uses local/offline profiles rather
   than Microsoft account sign-in.
2. Open **Instances** in Play and select **New instance**.
3. Fabric is selected by default. Choose another loader if needed, then choose
   a compatible Minecraft version and a block or mob icon.
4. Review memory and Java settings if needed, then select **Download & Play**.

On the **Install** version step, use **Snapshots** and **Legacy** beside search
to include preview builds and older versions. You can enable both together;
the selected loader still determines which versions it supports.

In **Instances**, use the small pencil on a card to choose its icon. The same
panel offers **20 blocks** and **20 mob heads**. The small upload icon beside
those choices adds your own PNG, JPG, WebP or animated GIF. Your selection is saved per
instance, including during New Instance setup. Clicking the card itself still selects the instance. Play shows the
loader as a compact tag beside the version.

The first launch downloads missing game components and can take longer.
Selecting an existing instance restores its version and loader. Your render and
simulation distances stay saved for that instance. FPS boost applies performance
defaults once, then preserves later video changes. Turning it off restores previous
graphics settings where you have not changed the boosted values yourself.
Enable **Sync game settings** beside FPS boost to reapply its video preset before
every launch, including after in-game edits. It uses 4-chunk render distance,
5-chunk simulation distance where supported, VSync off, unlimited FPS, minimal
particles, disabled clouds/shadows/smooth lighting, and reduced entity distance.
It also restores supported renderer culling, deferred chunk building and fast
batching options, uses two chunk-builder threads, and disables Iris/Oculus
shaders and Cubeon motion-blur effects. Shader-pack selections are retained.
The shorter view and reduced effects trade visual detail for less rendering work.
Driver and rendering-compatibility workarounds stay preserved.
New instances receive version-appropriate settings on their first launch.
Turning sync off stops enforcement; turning FPS boost off restores eligible
original video and mod settings from per-instance backups. FPS gains depend on the machine
and scene; the preset does not guarantee a particular frame rate.
Boost works independently of the Cubeon Client switch on Fabric, Quilt, Forge
and NeoForge. It installs compatible performance mods when builds exist for
that Minecraft version: Sodium, Lithium, ImmediatelyFast, Entity Culling,
FerriteCore, ModernFix and BadOptimizations. Forge uses Embeddium and
Canary/Radium, while NeoForge prefers Sodium and Lithium. The small options
button beside FPS boost lets you select More Culling, Enhanced Block Entities
and Exordium individually. These are off by default and may change visual/HUD
behavior; a missing compatible build is skipped. Unchecking stops automatic
additions; disable already installed copies in Mods → Installed.
Existing alternatives and disabled/removed mods
are respected. Turning Boost off stops new additions and restores eligible
graphics settings; installed mods remain manageable under Mods → Installed.
With Discord desktop running, Rich Presence shows the Minecraft version and
loader you are playing, for example “Playing Minecraft 1.21.11 (Fabric)”.

An offline profile does not authenticate you to servers that require a
Microsoft/Mojang account.

## Mods, packs, and cosmetics

- **Mods:** select a compatible modded instance first. A Fabric mod does not
  work just because another loader is installed. Disable or remove optional
  performance mods such as More Culling in **Mods → Installed**; Play respects
  that choice for this instance. You can install them again from the Mods browser.
  More Culling requires an explicit choice in the FPS boost options. On first
  Play after updating, old launcher-managed copies in ordinary profiles are
  disabled once and remain recoverable in Installed. Manual jars, modpack
  content, and mods requiring More Culling are preserved. An old browser install
  may also be disabled because its saved metadata matches automatic installs;
  deliberately installing or re-enabling it is respected.
- **Resource packs:** work with Vanilla as well as modded instances, subject
  to Minecraft version compatibility. Enable them in the game's settings.
- **Shaders:** require a compatible loader and shader runtime, such as Iris
  or Oculus. Downloading a shader ZIP alone does not enable shaders.
- **Modpacks:** carry their own Minecraft and loader requirements. Review
  the pack's requirements before installing it.
- **Cosmetics:** manage skins, capes, and shoulder/back items in Cosmetics; use
  the rotation arrows to inspect the 3D model. Shoulder and Back sections are marked **Beta**.
  Shoulder and back items are drawn in
  game by Cubeon Client; skins and capes need compatible
  skin support. A selection is stored in the instance the game plays in, so
  each instance can keep a different item.
  In game, shoulder pets breathe and look around; wings beat slowly at rest,
  speed up smoothly when sprinting and spread with lifting strokes during gliding.
  With an elytra equipped, your selected wings replace its appearance. You still
  need the elytra item to fly; durability and flight controls work as usual.
  The five wing themes
  offer the original cute **Small** wings and layered **Giant** wings. Each Giant feather
  flexes and recoils with a slight delay while its root stays attached.
  Press **N** with **Giant** wings equipped to spread them and
  play a short dragon-style wing flare; it settles back automatically. Rebind
  **Dragon Wing Flare** in Minecraft's Controls → Key Binds → Cubeon Client.
  Small wings keep their gentle normal movement and completely ignore N.
  Giant feathers have separate curved surfaces and depth. In client settings (**K**),
  turn **3D wings** off for a simpler flat mesh that keeps the overall flapping and N
  flare. This saves rendering work on weaker GPUs; Small wings are unaffected.
  **Other cosmetics** starts off. Turn it on to see other Cubeon players' selected
  wings, backpacks and shoulder pets within 64 blocks. Your own items stay visible
  either way. Viewers who leave **Other cosmetics** off see your normal elytra.
  Missing wing artwork or an unknown selection also keeps the normal elytra.
  Shared selections use the skin service; players need the updated
  Cubeon Client and managed skin support in the launcher to publish their choices.
  Changes may take about a minute to appear for others. The N flare stays local.
  Backpacks sway while you move. The launcher preview shows
  the resting model. Restart Minecraft after changing the companion mod.
- **In-game HUD and zoom:** press K in game to open the Cubeon Client menu.
  The HUD stays visible when using F3 debug information or F3+B hitboxes;
  F1 still hides it along with Minecraft's HUD.
  Search the categorized feature cards, use their switches to toggle a feature,
  and choose **Configure** for Move, size and feature-specific options.
  K and in-game Friends open in compact centered charcoal panels with clear
  controls and the Cubeon logo. Cubeon players in the Tab list show the logo beside their name.
  **Own name tag** under Player shows your name in third person (off by default).
  **Menu animations** under Render turns opening, hover and
  page motion off for the K menu, Friends and emote picker.
  Drag the size slider from 0.50× to 2.00×; Left/Right makes fine adjustments
  when the slider is selected. The new size appears immediately and saves on release.
  Clock (system/world time), system usage, potion effects, coordinates, compass,
  biome, day/light, combo counter and auto sprint all start **disabled**.
  Readouts use the original HUD's white shadowed text and a small black backing
  that fits their content. Empty potion lists and an idle combo counter stay
  hidden during gameplay; potion timers remain visible beside long effect names.
  The combo counter counts confirmed melee damage to one opponent; incoming
  damage, changing targets or a three-second gap resets it.
  Auto sprint follows vanilla hunger and movement restrictions.
  System usage shows Java heap RAM and Minecraft's **GPU frame load**, with a
  dash when unavailable; it does not measure total hardware GPU/VRAM usage. Sizes are independent,
  so making the keystrokes bigger does not enlarge the FPS
  counter. The armour overlay shows only the four worn pieces, not the item in
  your hand. **Enemy Health** toggles a thin bar beneath nearby enemy names
  (players and hostile mobs). It starts off and remembers your choice; enemies
  behind walls and teammates are hidden. **Cosmetic motion** starts on;
  switch it off to keep pets, wings and packs still, including individual feather
  movement and the N flare. This skips animation calculations.
  **Camera motion blur** starts off and is available in every supported client
  version. It softens the scene while turning the camera using a fixed 8 ms
  exposure, so its strength does not scale with FPS or VSync. The HUD and menus
  stay sharp. Turning it off frees its scene buffer and skips blur rendering.
  **Blur intensity** adjusts the strength from 25% to 200% in 25% steps;
  click it to advance, with 100% preserving the original effect. After 200% it
  returns to 25%. Both choices are saved.
  **Motion blur+** under Render blends recent world frames for smooth motion,
  including moving players and entities. Its strength slider ranges from 25% to 200%;
  the effect uses elapsed time so exposure remains consistent at different FPS.
  It starts off, keeps HUDs and menus sharp, and replaces Camera motion blur when enabled.
  **Reset layout** restores overlay positions and sizes.
  Tab/arrows select controls; Enter activates them. In the drag editor,
  other enabled HUDs stay visible at their saved sizes and positions, with amber
  frames marking overlaps. Release the mouse to save and choose Done or press Enter to return.
  Sodium and vanilla video options accept **1 chunk** for render and simulation
  distance. Render distance 1 gives very short visibility and can improve FPS;
  simulation 1 reduces nearby ticking in local worlds. Multiplayer simulation
  remains controlled by the server. Normal defaults/maxima are preserved.
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
  work. Choose **Edit wheel** in the center (or press E) to add or remove favorites: the wheel
  holds up to eight, saved in the order you add them. Selected entries have an
  grey edge; remove one before adding another when full. Click **Done** to
  return. Esc or right click returns from editing, then closes the picker;
  click the center to stop an emote. Move, jump, attack or use an item to
  cancel. The center's **ON/OFF** button toggles emote display and saves your choice.
  Other players running the updated Cubeon Client can see them on ordinary
  servers without a server mod. Both launchers need an online Cubeon connection
  and both players must join using the same server address. Offline emotes remain visible to you. Unmodified
  Minecraft clients cannot display these animations.
- **In-game cosmetics:** on supported Fabric versions from Minecraft 1.20 through
  26.3, choose **Cosmetics** at the top right of Minecraft's main menu, or open
  **K → Cosmetics** while playing. The **Skins** tab lets you browse saved skins, drag the 3D preview or
  use the Left/Right keys to rotate it, and choose **CONFIRM** to save and immediately
  update your own player. Selecting a preview alone does not apply it.
  **Import PNG** opens a file picker; you can also drop a 64×64 or legacy
  64×32 skin PNG onto the page. Enter a Minecraft username and choose
  the **+** button to import that player's public Mojang skin without changing
  your account or username. Imported skins join the same library used by the
  launcher. The toolbar lets you switch list/grid, export a PNG, or delete an
  unused skin (click trash twice to confirm). Confirm a different skin before
  deleting the one you wear. The arm control cycles Auto, Alex and Steve;
  the six buttons beside the player toggle Minecraft's hat, jacket, sleeves
  and trouser layers and save those visibility settings. Keep Cubeon open and
  enable **CustomSkinLoader** under Settings → Game → In game. Other players'
  views still depend on their compatible skin support and service/cache refresh.
  The **Capes** tab offers **Cubeon Cape**, **No Cape**, and your uploaded capes.
  Import or drop a cape image, rotate the player to preview it, then choose
  **CONFIRM** to save and update it immediately. HD capes retain their original
  resolution in game. Cape pages stay loaded when switching tabs. Custom cape
  choices and No Cape affect your own screen; friends still see the shared
  Cubeon cape, as with the launcher's Cape pane.
- **Skin arms:** each uploaded skin has an **Auto / Alex / Steve** control.
  Auto detects normal skin sheets; choose **Alex · 3 px** for a slim skin
  whose editor filled its unused pixels, or **Steve · 4 px** for wide arms.
  The choice is saved for that skin. Restart Minecraft after changing it.

Screenshots live under **Settings → Screenshots**. Its folder button opens the
selected capture's folder, or the active instance's screenshots when no capture
is selected. Stats shows playtime and
activity comparisons; it does not measure the game's frame rate.

### Finding a mod

Mods is one content area with four selectors: **Mods**, **Modpacks**,
**Resource Packs**, and **Shaders**. Search directly below them, use **Installed**
to manage your files, or **Import mods** to add local JARs. Optional category and
compatibility choices sit under **Filters**. Compact tiles show artwork, name,
author, download count and installed status; click a tile for its description
and versions. **Install** adds the matching build. Modpacks create their own
instances and do not need to match the selected Minecraft version.
If Quilt reports resource or shader ZIPs under `<mods>`, Cubeon moves those
misplaced packs to the game folder's `mods_user_backup/` on the next launch.
To use one in an instance, select that instance and use **Import packs** or
**Import shaders** in the matching content selector.
Search pages adjust their card count to the available window space. Larger
windows show more results at once; paging keeps additional results available.

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

For mods you already have, choose **Mods → Import mods** and select one or more
JARs. Review the target instance, compatibility and dependency warnings before
importing. Identical files are skipped even if renamed. Select a replacement
explicitly to keep the previous build disabled as a backup. Each file reports
its result, so a bad file does not stop the rest. Use **Check & repair** afterward
if you want Cubeon to fetch missing dependencies.

Choose the instance on Play, then open **Mods → Resource Packs** or **Shaders → Installed**.
Each installed tile has an enable/disable switch. Disabling keeps the file and applies to
that instance on the next launch; re-enable it with the same switch. Other
instances keep their own state. Enabled packs are available to select in
Minecraft's resource-pack or shader settings; the launcher does not select them.
Installed packs use their included `pack.png` or saved project artwork. If no
image is available, Cubeon shows its logo.

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

If entities disappear or skins flicker, close Minecraft and select the affected
instance on Play. **Settings → Performance → Fix problems → Rendering → Apply compatibility** turns
off extra entity culling and enhanced batching in existing mod configs. Other
preferences and skin files stay intact. Restart Minecraft to test it; FPS may
decrease. **Restore settings** restores the saved values while preserving later
edits. This is an optional workaround, not a diagnosis of every rendering bug.

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

Choose **Chat** from Minecraft’s main menu, press **G** in game, or choose
**Friends** in the **K** client menu to message your Cubeon friends. Keep the launcher open: both views share the same
encrypted conversations, so messages sent in either place appear in both.
Use Enter to send, Ctrl+Up/Down to select a friend, and the wheel or Page Up/Down
to scroll. The game keeps your draft until the friends relay confirms the
message is in the shared conversation. An unconfirmed send retains its draft
and asks you to check the conversation before sending again; there are no
automatic resends. Rebind G in Minecraft's Controls.
New live messages and invitations show a compact Cubeon toast in game; an open
conversation stays quiet, and old history does not trigger alerts.

Minecraft's Mod Menu title/button count shows loaded top-level mod files.
Bundled Fabric API modules and libraries stay visible in Mod Menu's detailed list
but do not inflate that count. Cubeon's Installed list can also include disabled
files; those do not count as loaded in the game.

Minecraft's regular chat automatically stacks consecutive identical styled
messages as **hello ×4** within ten seconds. Different senders, intervening
messages and server changes start a new stack. This is always enabled and
changes only the displayed lines; original message history and signatures remain.

Local server hosting runs on your computer. Built-in public tunnels and
automatic internet world sharing are no longer supported. Players outside
your local network need a separately configured, reachable server address.

## Launcher settings

Settings has separate **Account**, **Game**, **Performance**, **Appearance**, **Theme**,
**Notifications**, **Files**, **Launcher**, and **Screenshots** sections. Advanced Java,
version options, maintenance and backup scheduling stay collapsed until opened.

**Settings → Game → In game** has separate **Cubeon Client** and
**CustomSkinLoader (CSL)** switches. Turn either off to stop its in-game features
on the next launch. CSL controls skins and capes; Cubeon Client controls the
Cubeon menu and HUD. Choices save immediately and also apply to modpack installs.
Turn CSL back on to restore the copy disabled by this setting.
You can also switch **Cubeon Client** on or off in **Mods → Installed**.
It shares the Settings preference for all instances and stays available after
the client has been disabled.

In **Settings → Appearance → Launcher**, open **Language** and search by native name,
English name, or language code. Select a language, then click the **Restart** button
that appears below the saved choice to apply it. Arabic, English, Russian, and Spanish appear first, followed by Chinese, Hindi,
Portuguese, French, German, Japanese, Turkish, Korean, Italian, Polish, Indonesian,
Ukrainian, Urdu, Bengali, Persian, Malay, Pashto, and Roman Urdu. Core navigation and
controls are translated; detailed messages without a translation fall back to English.
Arabic, Urdu, Persian, and Pashto use a right-to-left layout.

**Custom title bar** defaults on for Windows (including Windows 10) and Linux. An
explicit saved choice to switch it off is preserved. Restart after changing it.

**Settings → Theme → Seasonal look** enables the seasonal palette and extras.
Switch off **Play scenery** in that section to hide the trees, grass and particles
while keeping the seasonal colors and buddy. Spring has blossoms and petals; summer has green trees,
butterflies and fireflies; autumn has falling leaves; winter has snow. The tilted
tree appears in every season. A season selection updates the artwork immediately;
the launcher's color palette applies after a restart. Turn off **Full motion** in
Appearance to retain static artwork without moving particles. The **Seasonal buddy**
wanders the launcher edges, climbs borders and rests above Play; changing tabs
returns it to the bottom edge. Turning off Full motion also keeps the buddy static.
Particles stop while Play is hidden. All seasonal animation pauses when the window
is minimized or loses focus. There is no separate Weather effects option.

Install checks that Java exists, can run, and meets the selected game's requirement.
It uses suitable installed Java first, otherwise downloads or repairs a verified
runtime automatically. Download sources are measured on your connection, with server
fallback, parallel transfers where supported, and resume after interruption. Leave
**Java path** blank for automatic setup, or enter an executable, JDK folder or bin folder.

In **Settings → Performance → Advanced Java settings**, expand **Cubeon's default flags** to see the
options derived from your memory setting and hardware, with explanations and skipped
options. This readout updates when you change RAM or custom flags. Custom flags go
after defaults; choosing another garbage collector suppresses Cubeon's G1 options.
Turn off **Use Cubeon's default Java flags** to remove all Cubeon-added flags
on the next game launch. This also removes Cubeon's `-Xmx` and `-Xms` values,
so the RAM slider no longer sets the heap. Set your own heap flags in **Custom
Java flags** if needed. Minecraft and loader arguments remain required. The
switch saves immediately; no launcher restart is needed.

**Settings → Notifications → Chat messages** controls incoming message
notifications immediately. Open conversations in a focused launcher or the companion
mod suppress their alerts; old history and your own sent messages do not trigger them.

## Updates

Cubeon checks for a newer version when it starts. If one is available, a
prompt offers **Skip** and **Update**. Skip remembers that release across
launcher starts. A newer release can still appear; **Check for updates** in
Settings can offer a skipped release again. An installed or older version never
opens the prompt. Downloads start only after you choose Update.

Choose **Stable** or **Beta** in **Settings → Account → Updates**. Stable is
the default; Beta also includes prereleases. Use **Check for updates** to check
the selected channel immediately or retry after reconnecting to the internet.

Windows installations made with Cubeon's installer and Linux AppImages in
writable folders download and verify the update inside Cubeon. One **Update**
click downloads, verifies, closes Cubeon, installs and reopens the new version.
Cancel stops the download. Debian/Ubuntu package installs can also update
through the system authorization prompt when PolicyKit and apt are available.
Close Minecraft and stop active installs or hosted servers first. Updating the
AppImage keeps a `.cubeon-previous` copy beside it.

Legacy Windows portable copies should migrate by running the setup executable.
macOS, source checkouts and unsupported Linux packages offer an explicit
**Download manually** action. Update never
opens a browser automatically. A missing checksum stays an error inside
Cubeon; restart the launcher to check for a verified release again.

Reinstalling Cubeon keeps its data folders. Windows setup stages files before
replacement and restores the old program if replacement fails.

## Data and troubleshooting

| Location | Contents |
| --- | --- |
| `~/.cubeon_launcher/` | Settings, local identity, caches, and server data |
| `~/.cubeon_launcher/cubeon.log` | Launcher log |
| `~/.cubeon_minecraft/` | Cubeon's game files |

`~` means your home folder. The game path can be overridden in a development
environment. Back up worlds before removing game files, and keep identity
files private.

**Instances** is the main folder for your Minecraft installations. Visible
folders use readable names such as `26.3-Fabric`, `1.21.11-Fabric` or your custom
name. Minecraft's shared version downloads, assets and libraries are stored
inside `instances/.runtime/`; there are no duplicate runtime copies or links.
Long loader build IDs are only used inside that hidden runtime folder.

For migrated instances, worlds are in
`~/.cubeon_minecraft/instances/<instance>/saves/`. Each world is a folder
containing `level.dat`. Some instances have an inner `minecraft/` folder, so
their worlds are in `minecraft/saves/`. The easiest route is to select the
instance, click **Folder** on Play, and open `saves/` (or `minecraft/saves/`). A version you haven't
played may not have any world saves yet.

**Open Mods Folder** opens the folder Minecraft reads: add a compatible JAR to
install it, or remove it to uninstall it. Deleting an instance retains its game
folder under `backups/deleted-instances/` for recovery.

The **Organize Minecraft files** prompt migrates old global content, removes old
content folders from the main directory and combines shared version files under
Instances. Choose **Migrate now** for an old installation or **Organize folders**
if its content is already migrated, then **Restart Launcher**. **Later** keeps
the current setup working; the same action is under **Settings → Files**.

Worlds, configs and settings stay with their own instance. Folder renames move
existing files together without merging worlds or resetting settings. Original
global content is retained under `backups/legacy-content/shared-<id>/`.
Interrupted moves can recover, and completed instances keep newer changes.
Close Minecraft before organizing. Older launchers do not understand the new
paths; keep using the updated launcher after migration.

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

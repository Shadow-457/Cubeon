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
  skin support.

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

**Fix problems** in the installed-content view runs Cubeon's Doctor. For mods,
it checks duplicate copies, missing required dependencies, loader/version
compatibility, and declared Fabric conflicts. It can fetch compatible missing
dependencies. Before disabling extra copies, disabling incompatible/conflicting
mods, or replacing an installed build, it shows the affected files, instance,
and reason and asks for approval. Cancel leaves those mods unchanged. Doctor
keeps old files rather than deleting them; re-enable them in **Mods → Installed**.
The status reports how many problems were fixed and still need attention. A
cancelled required repair pauses launch instead of silently changing your mods.

The same system checks resource-pack compatibility and shader-pack structure;
automatic checks also cover installed modpacks and server plugins. Doctor
does not fix missing search results, repair arbitrary bugs inside a mod, or
make a mod run on an unsupported Minecraft version or loader. Back up worlds
before changing a modded installation.

## Friends and servers

Friends-enabled builds include chat and in-game integration. Some public
builds omit these features. You do not need to deploy the backend yourself
to use a build configured for Cubeon's services.

Local server hosting runs on your computer. Shared access depends on the
server and tunnel being available, and may be affected by firewall or
network settings.

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

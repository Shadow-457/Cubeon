# Cubeon Minecraft Launcher

A free desktop Minecraft launcher for playing with friends - offline/cracked
accounts, one-click modded launches, a shared skin network so players can see
each other's skins on **any** server, and built-in world hosting via tunnels.

Built with Python + Flet. No Mojang account, no paywall.

## Quick start

```bash
pip install -r requirements.txt
python main.py          # Java is auto-detected; MC downloads on first launch
```

## Features

- **Offline/cracked login** - any 3–16 character username. Your identity is a
  stable UUID (`~/.cubeon_launcher/auth_key.json`) that survives renames, so
  per-UUID server data (saves, inventory) is never orphaned.
- **Version manager** - browse releases/snapshots, auto-download on first
  launch.
- **Mod loaders** - Vanilla, Fabric, Quilt, Forge, NeoForge; auto-installs the
  loader for the chosen version. Per-profile mods in
  `~/.cubeon_launcher/mod_profiles/`, synced into `.minecraft/mods` at launch.
- **Skin network** - upload your own skin; other Cubeon players see it
  in-game on any server via CustomSkinLoader + a Cloudflare Worker backend.
  Every Cubeon player also wears the shared Cubeon cape automatically.
  See `agents/docs/skins-identity-workflow.md`.
- **Cosmetics** - hats baked into your skin sheet; capes; live body preview
  rendered from real pixels.
- **Friends** - unique Cubeon names, presence, chat, groups, voice
  (`worker/cubeon-friends.js` + `cubeon/friends.py`).
- **Host-a-world / tunneling** - invite codes that turn into tunnel addresses
  (`cubeon/invites.py`, `cubeon/tunnel_tab.py`).
- **Modpacks** - install/manage modpacks per version+loader profile.
- **Settings** - RAM slider, window resolution, custom Java path.

## Project layout

```
main.py                  UI entry point - builds every tab, boots Flet
launcher_core.py         Facade: `import launcher_core as core` re-exports cubeon/

ui/                      Flet UI layer - one module per tab/section, no business logic
  main window tabs: skin_tab, mods_tab, modpacks_tab, server_tab
  (Friends has no tab: its UI is the in-game mod/ - see cubeon/friends_service.py)

cubeon/                  ALL business logic (no UI imports):
  config.py      settings persistence + stable identity (auth_key.json)
  paths.py       every filesystem path in one place (~/.cubeon_launcher, .minecraft)
  launch.py      Java command construction + game process management
  skins.py       skin uploads/previews + network publish (heartbeat + upload)
  csl.py         CustomSkinLoader install + ExtraList registration
  cosmetics.py   hat composition onto base skins
  capes.py       cape pipeline        versions.py   version manifests
  mods.py        mod management       mod_loaders.py  Fabric/Forge/etc installs
  modpacks.py    modpack handling     invites.py    invite-code client
  friends.py     friends identity + WebSocket client
  server.py      local server lifecycle  p2p.py / voice.py / playit.py  networking

templates/               Color-theme palettes, loaded by cubeon/color_templates.py

worker/                  Cloudflare Workers (free tier) - see worker/README.md
  cubeon-skins.js        identity + skin API (heartbeat, uploads, CSL lookups)
  cubeon-friends.js      realtime Friends backend (Durable Object)

packaging/               Build scripts + PyInstaller specs - see BUILDING.md
tools/                   tests + dev scripts - see tools/README.md
agents/                  AI-agent notebook; also holds docs/ (design docs; start
                         with agents/docs/skins-identity-workflow.md) and
                         memory/ (quick-reference fact sheets)
assets/, web/            icons/art, marketing site

archive/                 old snapshots & regenerable build output (safe to delete)
```

## Backend infrastructure

Three Cloudflare Workers on the free tier (deploy = paste into dashboard
editor; see `worker/README.md`):

| Worker | Job | KV namespace |
|---|---|---|
| `cubeon-skins.js` | identity + skins + cape | `SKINS` |
| `cubeon-invites.js` | invite codes → host addresses | `INVITES` |
| `cubeon-friends.js` | presence/chat/voice signalling | Durable Object (`wrangler`) |

The launcher talks to them at:
`https://cubeon-skins.hamza-457-shahbaz.workers.dev`

## Building distributables

```bash
./packaging/build_appimage.sh        # Linux AppImage
python packaging/build_windows.py    # Windows EXE (or the .bat/.ps1 variants)
```

Details in `packaging/BUILDING.md`; CI does both automatically
(`.github/workflows/build.yml`). Old build output lives in `archive/` -
deleting it loses nothing.

## Notes

- Config and data live in `~/.cubeon_launcher/`; the game lives wherever
  minecraft-launcher-lib puts it (`~/.minecraft` by default).
- Skin network docs: `agents/docs/skins-identity-workflow.md` (architecture +
  testing), `agents/docs/phase1-skins-capes.md` (design history), CSL facts in
  `agents/memory/customskinloader-verified-facts.md`.
- Offline authentication only - works on servers that allow cracked clients.

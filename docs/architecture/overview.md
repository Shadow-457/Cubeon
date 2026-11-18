[Documentation](../README.md) / Architecture

# Architecture

Cubeon has a Python desktop launcher, a Fabric companion mod, and Cloudflare
Workers for online features. Minecraft runs as a separate Java process on
the user's computer.

```mermaid
flowchart LR
    subgraph Launcher[Desktop launcher]
        UI[Flet interface] --> Core[Game and service modules]
        Core --> Bridge[Local API bridge]
    end
    Core -->|Launch| Game[Minecraft Java process]
    Game <-->|Companion mod HTTP| Bridge
    Core <-->|HTTP and WebSocket| Workers[Cloudflare Workers]
```

The localhost bridge is used by the companion mod in Friends-enabled
configurations. Vanilla launches do not require that integration.

## Components

| Location | Responsibility |
| --- | --- |
| `main.py` | Application startup, window setup, navigation, and launch orchestration |
| `ui/` | Flet tab builders and dialogs |
| `cubeon/` | Launching, storage, downloads, services, and shared UI support |
| `launcher_core.py` | Compatibility facade for the underlying Python modules |
| `mod/` | Fabric client integration and Minecraft version brackets |
| `worker/` | Skins, invites, friends, downloads, and waitlist services |
| `packaging/` | Platform build and installer scripts |
| `tools/` | Regression checks, development harnesses, and release tools |

Most game and service logic can run without a Flet page. The `cubeon/`
package also contains UI helpers such as theme and motion; it is not a
strictly UI-free package.

## Desktop UI

`main.py` owns shared configuration and session state. Tab builders receive
the state and callbacks they need, returning a control tree and refresh
functions. Tabs are constructed lazily and retained for later navigation.
The shell wraps each tab in `ui.chrome.TabPane`. During a navigation repaint,
`thread_safe_ui.update_scope` enables Flet isolation at those panes, so the
parent Stack sends visibility without traversing retained libraries or
transcripts. Content changes repaint their own controls or hosts. Ordinary
full-page updates retain normal traversal for existing handlers; the isolation
scope is applied during the actual diff, including queued worker updates.
`ui.chrome.TabEntryQueue` prepares native tab entries on one page-context worker.
First visits paint a lightweight loading pane before mounting the completed
content; later visits reuse it. Rapid navigation keeps the latest pending entry,
and generation checks keep hidden completions from changing the visible tab.
Do not prebuild heavy tabs on the UI event loop after startup. Mods builds the
embedded Modpacks view only when its category is opened, and fresh cached Mods
navigation skips unchanged installed-list rendering.
The 64px sidebar uses Flet icons and a slim accent marker. `ui.chrome.NavSlider`
moves the marker using native offset animation inside a separate, noninteractive
paint viewport, so animation frames do not relayout the rail or repaint tab
content. It shares the tab-switch patch and reuses existing window resize events;
unchanged scroll events cause no paint. The settle is 120ms; reduced motion
snaps it into place. Native animations still require renderer frames, so headless
diff timings do not certify native frame rate.
The active glyph uses the accent color; tiles stay transparent, and keyboard
focus has a neutral outline. Server sub-tabs share the Servers position, and
Settings remains pinned below the rail.
Mods' content selectors retain the supplied Mods, Modpacks, Resource Packs and
Shaders SVGs and their original artwork colors.

`ui/mods_tab.py::ModsView` loads the selected content pane through
`_load_visible_content()`. Browse starts the first provider page, then requests
installation badges after results arrive. Installed loads its snapshot before
starting the automatic compatibility check. `InstalledSnapshot` includes the
instance's verified loader, read once on the worker; tile rendering uses that
snapshot while actual installation actions revalidate the on-disk instance.
`cubeon/mod_catalogue.py::ProviderPage` keeps independent pending, successful
and failed provider outcomes. Hidden completions cache data; returning paints
the latest cached page without restarting its requests. Icon metadata updates
repaint only changed artwork holders. The public builder still returns four
values: root, installed refresh, entry hook and profile refresh.

Downloads and service polling must not block UI handlers. Background tree
mutations use `thread_safe_ui.TREE_LOCK`, and repaint requests go through
`thread_safe_ui.refresh()` so they reach Flet's event loop safely. Worker bursts
coalesce per control and event loop; pending keys clear before diffing so a
mutation during a paint can request another delivery.

Refreshing a label, unread count, or presence ring should not recreate its
parent row or retransmit unchanged artwork. Existing controls can be updated
in place. See [Launcher](launcher.md) for more detailed entry points.

Appearance's `ui/color_studio.py` uses a responsive native hue/saturation wheel,
one brightness slider and a hex field with a retained launcher preview. Pointer
events perform no image decoding, filesystem work or saves. `launcher_palette`
retains the validated seed, depth and vividness recipe for compatibility;
choosing a color preserves existing depth/vividness values. `color_templates.py` derives
contrast-checked dark surfaces and accents while preserving semantic colors.
The package startup hook applies it before UI token imports; explicit color
flags and installer mode retain their palette overrides. Saving is transactional
and takes effect after a launcher restart.

## Game launch

The Play flow selects a Minecraft version and loader, installs missing
components, prepares the selected instance's content, and starts Java.

- `cubeon/versions.py` handles game versions and installation.
- `cubeon/mod_loaders.py` handles loader installation.
- `cubeon/launch.py` constructs the game command and starts the process.
- `cubeon/instances.py` reads installed-instance metadata.
- `cubeon/mods.py`, `modpacks.py`, and `content.py` manage installed content.
  Individual Mods discovery combines Modrinth and CurseForge through
  [the provider catalogue](mod-catalogue.md).

Selecting an installed instance must use that instance's loader, not leave
an unrelated loader toggle selected. Shared downloads can be reused, but
one instance's active mods or packs must not leak into another.

The storage and synchronization model is described in
[Content storage](content-storage.md) and [Mod management](mod-management.md).

## Identity and local state

The launcher's files live under `~/.cubeon_launcher/`; game files default
to `~/.cubeon_minecraft/`. `cubeon/paths.py` defines these locations.

An offline Minecraft username is not an authenticated Microsoft identity.
Cubeon's skin identity uses a public UUID and private capability token in
`auth_key.json`. The friends service has its own persisted identity and
relay-assigned ID. Do not treat display names as ownership credentials or
publish local identity files in diagnostic reports.

## Friends and the companion mod

`cubeon/friends_service.py` owns the process-level social service. The Chat
tab consumes that service directly; the in-game mod uses the authenticated
localhost bridge in `cubeon/local_api.py`. Both views operate on the same
launcher service rather than opening unrelated chat sessions.

The Worker handles presence and signaling. Direct-message encryption is
implemented in `cubeon/e2ee.py`. Voice audio is an optional dependency;
signaling support does not imply that audio is installed.

Friends can be disabled in a packaged build. `cubeon/features.py` resolves
the build marker and configuration override. See [Friends](friends.md),
[Networking](p2p.md), and the [protocol reference](../protocols/friends-api.md).

## Backend services

| Worker | Responsibility |
| --- | --- |
| `cubeon-skins.js` | Skin identity, uploads, cape delivery, and CustomSkinAPI reads |
| `cubeon-invites.js` | Invite-code creation and resolution |
| `cubeon-friends.js` | WebSocket presence, chat, groups, and call signaling |
| `cubeon-downloads.js` | Public download access to release assets |
| `cubeon-waitlist.js` | Website waitlist |

Worker source and Wrangler configuration live in `worker/`. Configuration
in the repository is not proof of a currently healthy deployment. Follow
the [Worker guide](../../worker/README.md) for deployment and verification.

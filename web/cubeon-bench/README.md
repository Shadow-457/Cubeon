# Cubeon Bench

A local Minecraft Java texture-pack and skin editor. Projects, imported files,
preferences, and activity stay in your browser. No account is required.

**Log out** is available at the top of Settings and in the profile menu. It
saves your workspace and returns to Welcome, staying logged out after a reload.
Your projects and preferences remain on this device; choose **Open Bench**
to return. If saving fails, the workspace stays open so you can retry or back up.

## Run locally

From this directory, run:

```sh
python3 tools/serve.py --port 8000
```

Open **http://127.0.0.1:8000/cubeon-bench/**. Use the same address, port, and
browser profile to access your saved projects. This server serves only the app.
The main website also mounts it at `/cubeon-bench/`.

The landing page is **http://127.0.0.1:8000/cubeon-bench/landing.html**. Scroll
through the Three.js painting → frames → 3D flower sequence, explore the actual
editor previews, and use the header's light/dark theme toggle. Its assets,
Three.js, and editor screenshots are bundled locally for offline use. The app
keeps its original address and saved projects. Test the landing with
`python3 tools/test_landing.py`; `--capture-editor` refreshes its real screenshots
using an isolated browser profile.

Directly opening `index.html` supports file mode and bundled textures. Localhost
or HTTPS provides the complete IndexedDB storage and app installation workflow.

## Editing and projects

Home's first-project area starts a skin or texture pack. Projects support
renaming, duplication, favorites, search, sorting, and export. Deleted projects
stay in **Settings → Trash** until permanently removed. Pack details include
description, creator, version, Minecraft compatibility, and an optional PNG icon.

The library contains 3,964 original Minecraft PNGs with native proportions,
transparency, and animation sheets. New packs support original, 2×, and 4× scale;
imports retain their resolution. Block previews use companion faces, items show
pixel edges, and skins use Minecraft's 64×64 layout. Imported JSON models are
preserved in exports; previews use the built-in geometry.

The default tools are **Draw**, **Erase**, **Fill**, and **Pick**. Choose a color,
then paint on the canvas. **More tools** contains shapes, selection, and shading;
their keyboard shortcuts also open the relevant controls. **More colors and
opacity** contains HEX, opacity, studio colors, and recent colors. Mirroring
and custom brush sizes are under **Brush settings**.
The canvas opens fitted to its available space. Its footer puts **Fit**, zoom,
and Help within reach. **Canvas settings** contains grid and Hand panning.
Manual zoom stays put;
Fit follows window/sidebar changes. Tool guidance explains what to do next.
**Colors in this texture** offers reusable source colors with exact alpha.
Affected grass/leaves have an **In-game colors** switch between grayscale source
and natural Minecraft colors. This changes the display; saved/exported pixels
retain their original values.

Drag the sidebar dividers to resize them. Widths persist, with at least 320
pixels reserved for the desktop canvas. Divider arrow keys adjust widths;
double-click restores defaults. 3D Preview stays pinned while texture tabs
scroll. **⋯ → Texture actions** offers image import/PNG download, flip, rotate,
clear, and reset. Dark mode uses a dark transparency checkerboard.

Choose **Create animation** above the canvas to start with two copies of your
texture. Animated textures open on one editable frame, with a panel between
the canvas and tools. Select a frame, paint it differently, then press **Play**.
**Add frame** copies the selected frame. The default duration field uses seconds,
rounded to the nearest Minecraft tick. Shorter means faster. Preview,
thumbnails, adding frames, and timing stay together in the panel.

Drag frame handles to reorder, or use **Alt+↑/↓**. Reordering preserves pixels,
timing, and repeated references, supports undo/redo, and exports the sequence.
Close the panel with **×** and reopen with **Frames** above the canvas; desktop
visibility is saved. Mobile frame selection closes the drawer so you can paint.
**More options** provides native tick timing (20 ticks = 1 second), shared timing,
blending, moving/removing frames, the full sheet view, and disabling animation.
Saved frame/sheet view preferences are respected.

Activity counts distinct project textures whose pixels or animation metadata
changed on each local calendar day. Repeated edits count once per texture that
day; opening projects and changing display settings do not count.

Panels slide and fade, the canvas adjusts smoothly as the frame panel opens or
closes, and reordered frame rows glide into position. Menus, dialogs, settings,
and navigation use coordinated short transitions. The app's **Reduce motion**
setting and system preference stop these effects immediately.

## Import, export, and backups

Open a texture and choose **Import image** above the canvas (Ctrl / ⌘ Shift I).
Browse, drop, or paste a PNG, JPG, or WebP. Compare the source crop with the
actual output; choose Fill, Fit, or Stretch, move/zoom the crop, rotate/flip,
and select a texture resolution. Resizing suggests sharp pixels for pixel art
and smooth sampling for photos. Extra options preserve transparency or fill a
background color. Grass/leaves/water can preview Minecraft's tint without
changing saved image colors. A framed checker shows the exact texture bounds;
**Preview backdrop → Auto / Light / Dark** helps inspect dark or light pixels
without changing the exported image. Files stay on your device.

**Apply image** saves through normal edit history; Cancel changes nothing, and
Undo restores the previous pixels and dimensions. Animated imports default to
the selected frame; an explicit sheet option replaces the complete sheet while
preserving frame order/timing. Their sizes stay fixed, and skins require a
prepared 64×64 layout. Images are limited to 16 MB / 16 million pixels. Dropping
an image onto an open editor uses this preview workflow.

Use **Import** or drop one Java resource-pack ZIP, 64×64 skin PNG, or Cubeon
workspace backup. Pack imports handle wrapper folders and preserve namespaces,
animation metadata, models, sounds, fonts, and other binary files.

Packs export with `pack.mcmeta` at the root and textures under
`assets/<namespace>/textures/`. New packs export edited textures, or their
starting texture when untouched; Minecraft supplies other vanilla textures.
Skins export as PNGs. Creator/version details also appear in
`.cubeon/project.json`. New packs default to Java 26.1 compatibility; Pack
details offers other supported versions.

**Settings → Backups** exports all projects, Trash, edits, animations, and
original imported files to a `.cubeon.zip`. Restore merges projects with new
IDs and commits project data and binary files together. Existing work is
preserved. Profile/appearance restoration is optional.

Projects autosave in IndexedDB. The save indicator reports completed writes
and failures. Heavy edits/imports stay out of localStorage. Browser quotas and
clearing browser data affect local saves. Use **Protect local saves** and keep
workspace backups for portability.

## Offline and installation

Offline access prepares automatically on localhost or HTTPS, including all
bundled textures and local fonts. After **Offline ready** appears, reload,
editing, and export work without a connection. Install through the browser's
app menu or **Settings → Offline app**; support depends on the browser.

Localhost fetches current files first so changes appear on reload, with a cache
fallback when disconnected. An old cache-first worker in an already-open tab
may need one hard refresh. Hosted updates wait for **Save and update**.

## Shortcuts

Open **F1** or **?** for the searchable, grouped shortcut guide. Ctrl below
also supports ⌘ on Mac. Click a frame to use frame commands; click the canvas
to use pixel commands. Text fields keep their normal typing and clipboard keys.

| Action | Shortcut |
| --- | --- |
| Quick actions / help | Ctrl K / F1 or ? |
| New project / import pack or skin | Ctrl Alt N / Ctrl O |
| Import image as texture / paste image | Ctrl Shift I / Ctrl V with an image copied |
| Save / undo / redo | Ctrl S / Ctrl Z / Ctrl Shift Z or Ctrl Y |
| Export project / texture PNG | Ctrl Shift E / Ctrl Alt E |
| Search textures | Ctrl F |
| Previous / next tab; close texture tab | Alt ← / →; Shift W |
| Canvas / 3D preview | P |
| Draw / erase / fill / pick | B / E / G / I |
| Line / rectangle / ellipse / select | L / R / O / M |
| Lighten / darken / color picker | U / D / C |
| Temporary color pick / filled shape | Alt + click / hold Shift while drawing |
| Select all / deselect pixels | Ctrl A / Ctrl Shift A or Escape |
| Copy / cut / paste pixels | Ctrl C / X / V on canvas |
| Clear selected pixels | Delete / Backspace on canvas |
| Copy / cut / paste animation frame | Ctrl C / X / V in frame panel |
| Frame copy / cut / paste from canvas | Ctrl Shift C / X / V |
| Duplicate selected frame | Ctrl D |
| Remove frame | Delete / Backspace in frame panel |
| Select previous / next frame | Arrows in frame list; Page Up / Down on canvas |
| First / last frame | Home / End in frame list |
| Reorder frame | Alt ↑ / ↓ in frame panel |
| Animation play / pause | Space in frame panel; Shift Space on canvas |
| Create animation / add frame; toggle frames | Shift A; Shift F |
| Brush size / zoom / 100% zoom | [ ] / + − / 0 |
| Fit canvas / toggle grid / Hand tool | F / Shift G / H |
| Temporary canvas pan | Hold Space and drag |
| Rotate 3D model / larger steps | Arrows / Shift + arrows |
| Reset 3D / auto-rotate | F or 0 / Space |
| Resize focused sidebar divider | ← / → |
| Focus / activate controls | Tab or Shift Tab / Enter or Space |
| Close panel / leave editor | Escape |

Frame copying preserves exact pixels and duration. Pasting inserts an independent
frame after the selection; its dimensions must match the destination animation.
The internal frame clipboard works across open projects in this session. Frame
removal keeps at least one frame and is undoable. Animated 3D faces use persistent
canvas surfaces, so playback does not replace/decode a PNG every frame.

## Development and verification

No build step is required. After changing bundled textures, regenerate the
catalog and offline/file-mode fallback:

```sh
python3 tools/build_texture_catalog.py
```

Browser checks require Playwright/Chromium, or Firefox and Pillow:

```sh
python3 tools/test_app.py
python3 tools/test_website_browser.py
python3 tools/test_website_firefox.py
python3 tools/test_website_firefox.py --mobile
python3 tools/test_website_firefox.py --workflow
```

The app suite checks editing, resizing, backups, failure recovery, offline
reload/export, animation reordering/export, and mobile layouts. Firefox's
workflow also checks large projects and a full browser restart. Read
`agents/docs/module-map.md` before changing modules. Bump `sw.js`'s `VERSION`
whenever shipped app assets change.

ZIP support uses the vendored MIT-licensed fflate library
(`vendor/fflate.LICENSE`). Inter is bundled under `fonts/OFL.txt`.

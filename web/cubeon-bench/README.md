# Cubeon Bench

Open `index.html` directly, or serve this folder with `python3 -m http.server 8000`.

The library uses the original Minecraft PNGs in `textures/`, organized by their Minecraft folders. PNGs keep their native proportions, transparency, and animation strips. The editor supports the original resolution or scaling by 2× and 4×. Block previews use companion face textures; items have pixel edges, and player skins use Minecraft's skin layout.

Projects and imported files autosave locally in IndexedDB. Cloud storage and authentication are not required. The save indicator reports completed writes and storage failures. Large edits stay out of localStorage; it only holds small startup metadata. Reopen the same browser profile and address to continue working. Browser quotas depend on available space, and clearing browser data removes local projects. Use **Protect local saves** in Settings and keep exported ZIP backups.

Create a texture pack with its description, creator, version, and optional PNG icon, then use **Pack details** to update them. There is no preset palette selection. Choose any color with the custom saturation/brightness square, hue slider, HEX/RGB fields, and opacity control, or reuse a recent color. Settings also lets you upload a custom profile picture. Cubeon sign-in is disabled and marked **Coming soon**.

**Import .zip** opens Minecraft Java resource packs, including ZIPs with a wrapper folder. Imports preserve the original textures, animation metadata, namespaces, models, sounds, fonts, and other archive files. Imported textures keep their existing resolution and Minecraft compatibility settings. Preview geometry uses the built-in block, item, and skin shapes; imported JSON models are retained in exports.

The editor’s download button exports a Minecraft resource-pack ZIP with `pack.mcmeta` at the root and textures under `assets/<namespace>/textures/`. Newly created packs export the edited textures; Minecraft supplies the remaining vanilla textures. An untouched new project exports its starting texture. Pack descriptions and compatibility go in `pack.mcmeta`, icons go in `pack.png`, and creator/version details also go in `.cubeon/project.json`. Skin projects download as PNGs. The supplied textures default to Minecraft Java 26.1 compatibility; older supported versions can be selected in Pack details.

Motion includes coordinated view entrances, a moving navigation indicator, restrained hover feedback, and actual save/import/export progress. Both the system’s reduced-motion preference and the app’s **Reduce motion** setting are respected.

After adding or replacing textures, rebuild the catalog and the fallback used when opening the page directly:

```sh
python3 tools/build_texture_catalog.py
```

Browser checks with Firefox and Pillow:

```sh
python3 tools/test_website_firefox.py
python3 tools/test_website_firefox.py --mobile
python3 tools/test_website_firefox.py --workflow
```

The workflow check covers ZIP round trips, custom colors and profile pictures, projects above 5 MB, storage failure recovery, and reopening saved projects after a full Firefox restart. `tools/test_website_browser.py` also provides Playwright checks for Chromium when a local server and browser automation are available.

ZIP support uses the vendored MIT-licensed fflate library; see `vendor/fflate.LICENSE`.

[Documentation](../README.md) / Development

# Neon cosmetics store

Cubeon's **Wardrobe → Browse** downloads capes, animated GIF capes, pets,
wings, headwear, footwear and auras from the public website API. Downloads appear in
**Cape**, **Pets**, **Back**, **Head**, **Feet** or **Aura**; the user explicitly selects an item to equip it. Custom capes use the
existing importer and animation support. Pets and wings use Cubeon's existing
box/feather geometry, texture atlas and animation rig.

The launcher keeps visible category buttons inside **My items** and remembers
that category when returning from **Browse**. Category toolbars stay outside a
bounded native `GridView`; at most four columns fit the measured viewport.
Native cells build on demand, with one row of cache. The single thumbnail worker
renders only the visible rows plus one nearby row and follows the current category
and scroll position. Cached cards and images survive selection, filtering and
category returns. Equip repaints the previous/new cards and current toolbar,
without diffing the whole grid or page. Back filters retain their controls.
Cape cards load on first opening; uploads add cards without replacing unchanged
skin/cape artwork. The character preview is requested once on entry.

The Store shows a validated saved page immediately while refreshing it in the
background. Pages are keyed by API address and offset, saved atomically, and
retained for up to 24 hours. A page fetched within the last 60 seconds needs no
new request unless **Refresh** is pressed. First-time installs use the bundled
public collection snapshot, refreshed through the same API. Offline refreshes
keep the saved cards usable; downloads still verify the current pinned checksum.
Catalog reads are bounded and malformed snapshots are ignored. Ownership checks
read only the selected revision's manifest and texture presence, without preparing
its rendering geometry. Opening Store does not download or equip models.
The complete bundled snapshot is capped at 4 MB; each selected page, saved page
and API response retains the separate 450,000-byte limit.

The launcher Store searches the full collection by name, description, ID and
category. Typing waits briefly before searching; Enter searches immediately.
Matching results retain the normal 12-item pagination, and clearing the field
returns to the first unfiltered page. Search assembles the existing API pages on
a worker and shares a complete index for 60 seconds. Its saved index has the
same 4 MiB bound as the bundled snapshot and allows up to 1,024 items. Offline
search uses saved or bundled data; incomplete saved pages are identified in the
status message. Request generations prevent older results from replacing a
new query, and typing never downloads or equips cosmetics.

**Aura → Celestial Butterfly Aura** is bundled with Cubeon Client. Eight blue
butterflies orbit at different heights around the body, flutter independently,
and carry an emissive mask. It attaches to the torso so crouching and swimming
follow the player; Cosmetic motion off freezes the rig. Its small wings use
two-sided cutout textures to keep the mesh at 40 boxes. Auras equip independently
of pets, wings, headwear and shoes.
Each butterfly shares one pivot across its body, antennae and wings; the client
prepares eight independent poses with faster wing beats, gentle banking, bobbing
and radial drift. Base artwork and glow use the same pose. Floating headwear
with `motion: "float"`, including Sunward Halo and Tidal Crown, has a visible
bob and a slow sway. Fixed headwear keeps its existing pose. Both animations
use interpolated entity age, pause with the game, and draw their rest geometry
when Cosmetic motion is off. These changes require an updated client JAR.
The skins Worker's bundled-ID catalog accepts `aura_butterfly` for peer
sharing. Deploy the updated skins Worker when introducing a new bundled ID;
the Neon website deployment does not update this separate service.

Celestial Butterfly Aura is also published as a downloadable Aura Store model,
reusing the bundled geometry, PNG and emissive mask. Aura Store downloads need
the updated launcher and `kind=all&models=3` API. Older launchers keep their
existing Store categories; the bundled Aura choice remains available.
The shipped client selects the eight independent butterfly poses only for the
bundled `aura_butterfly` ID. Downloaded Store IDs use the generic orbit/flutter
motion; publishing the matching artwork does not change that Java behavior.

Fitted wearables suppress the outer skin parts they cover. The preview and
client share the same coverage rules: fitted head/face geometry hides the hat
layer, footwear hides outer trousers, wristwear hides its sleeve, and waistwear
hides the jacket layer. Floating head ornaments, wings, pets and auras keep
the skin layers. The client uses per-player model-part visibility, also honored
by 3D Skin Layers, without editing skins or Minecraft's saved preferences.
Removing the wearable immediately restores the original visibility setting.

The first catalog contains one **Cubeon Cape Sample**, using the original
bundled `assets/capes/cubeon_cape.png` artwork. After installing the client version
that supports store models, publishing another supported cosmetic requires no
launcher rebuild, client JAR rebuild, Git push or website deployment.

## Set up the database

Copy the Neon branch connection string from **Connect** into the repository's
ignored `.env` file, retaining any existing entries:

```dotenv
NEON_DATABASE_URL=postgresql://USER:PASSWORD@YOUR-ENDPOINT.neon.tech/neondb?sslmode=require
```

The connection string belongs only in owner tooling and the server environment.
It is never a launcher setting or bundled asset. The website speaks Neon's
[SQL-over-HTTPS protocol](https://github.com/neondatabase/serverless), using
parameterized queries, certificate verification and bounded timeouts.

From the repository root, using the project's Python environment:

```bash
python worker/manage-cosmetics.py sample
python worker/manage-cosmetics.py list
```

`sample` creates `cubeon_cosmetics` using `worker/cosmetics.sql` and upserts
exactly one sample id. Existing unrelated tables and cosmetics remain intact.
Use `init` to create an empty store instead.

## Publish another cape

The repository includes a publishing script and a **Git-ignored `cosmetics/`
folder**. Initialize a new checkout once:

```bash
./publish-cosmetics.sh setup
```

This creates the existing sample in `cosmetics/capes/`, empty `pets/`,
`wings/`, `head/`, `feet/` and `auras/` folders, and example recipes under `examples/`. It preserves existing
files. The examples are not uploaded.

Put PNG or GIF capes in `cosmetics/capes/`, then run:

```bash
./publish-cosmetics.sh --dry-run  # validate without credentials or uploads
./publish-cosmetics.sh            # publish new/changed cosmetics to Neon
```

Model recipes and their textures can use nested folders such as
`cosmetics/wings/7x7/` and `cosmetics/feet/7x7/`; sync scans these recursively.
Sibling review folders outside these six kind folders are not upload sources.

The published Bough Wings and Sunward Halo variants live under
`cosmetics/wings/bough-wings-12-flowers/` and
`cosmetics/head/sunward-halo-12-colors/`. Their original paths directly under
`cosmetics/` remain symlink aliases. Sync sees each stable ID once; retain
the supplied PNG artwork and emissive masks when updating these collections.

The script uses the checkout's `.venv` or `.venv-build`, falling back to
`python3`. Set `CUBEON_PYTHON` to select another interpreter. The same commands
are available as `python worker/manage-cosmetics.py setup` and `sync`.

Cape filenames produce stable ids and display names. An optional same-stem
JSON file overrides metadata. For example, `emerald.png` and `emerald.json`:

```json
{"id": "emerald-cape", "name": "Emerald Cape", "description": "My original emerald cape."}
```

Keep the id when renaming a file or updating its artwork. Duplicate ids fail
validation before uploads. Every input is validated before any database write;
unchanged entries retain their timestamp. Interrupted uploads can be rerun.
Removing local files does not delete or hide existing Neon entries. Sync
republishes entries present in the folder; move a hidden entry out of its upload
folder before rerunning sync.

Explicitly retired designs are listed by stable identity in
`cubeon/cosmetic_retirement.py`. They are excluded from saved/live Store pages
and the local picker, and owner sync rejects them before uploading. The owner
generator excludes them too, so regeneration cannot restore a removed design.
Morpho Orbit Halo, Zephyr Sprite, Dune Runner Cap, Cloudlet Head Wings and
Dawnflare Halo are retired Store entries; Floating Crown and Sun Halo are retired
bundled choices. Existing bundled source artwork is retained for compatibility.

The explicit single-file command remains available:

```bash
python worker/manage-cosmetics.py upload /path/to/cape.png \
  --id emerald-cape --name "Emerald Cape" \
  --description "An original emerald cape."
```

Inputs are validated with the launcher's cape decoder. PNG and animated GIF
files are limited to **2 MB**. The original file, SHA-256 checksum, metadata,
and a static first-frame preview are stored in Neon. Using the same id updates
that catalog entry; the checksum changes when its bytes change. A later download
of a new revision creates a separate local cape, preserving equipped older
copies. Owners can set `published = false` in Neon to hide an entry without
deleting its bytes. The API caches pages for 60 seconds; clients may show older
saved cards during an offline or slow refresh. Explicit retirements are filtered
from those saved pages too.

## Publish models

Pets and wings need a JSON recipe and PNG texture atlas. A raw image alone has
no 3D geometry. Copy `cosmetics/examples/pet.json` into `cosmetics/pets/`, or
`examples/wing.json` into `cosmetics/wings/`, then edit its id and name.
The examples reuse the existing animated Ember Fox and Small Ember Wings:

```json
{
  "id": "my-fox",
  "name": "My Fox",
  "description": "My original pet recolour.",
  "based_on": "shoulder_ember_fox",
  "texture": "my-fox.png"
}
```

Place `my-fox.png` beside that JSON recipe. Retain the template's atlas dimensions
and layout. Omitting `texture` uses the bundled artwork. For a completely new
model, replace `based_on` with a `model` object in the format used by
`assets/cosmetics/catalog.json`: `slot`, `texture`, `tex_w`, `tex_h`, `boxes`,
and optional `feathers`/`flat`. Pets use `shoulder`; wings use `back`;
headwear uses `head`; footwear uses `feet`. Headwear and footwear recipes go
in the matching `head/` and `feet/` folders. Footwear boxes must use
`motion: "left_leg"` or `"right_leg"` so each shoe follows its native leg.
Auras use the `aura` slot and `cosmetics/auras/`. The Butterfly Aura recipe
uses `based_on: "aura_butterfly"`; omitting texture/glow overrides reuses
bundled artwork without duplicating PNG files in the owner workspace.
Boxes use
`origin`, `size`, `uv`, `px`, and optionally `pivot`/`motion` for the existing
animation rig. `float` adds gentle hovering and headwear sway; `hover_body` and `hover_head`
compose hovering with the pet's breathing and glances. `orbit` and
`orbit_wing_left`/`orbit_wing_right` provide a slow head-centred butterfly orbit
and local wing beats. `aura` rotates around the box pivot while hovering.
Motion respects the existing in-game Cosmetic motion setting.
An optional `emissive_texture` PNG marks luminous pixels with opaque colour and
leaves other pixels transparent. It must match the base atlas dimensions and UV
layout. The client renders it over the same animated geometry at full brightness,
so glows remain visible in dark scenes. Preview bloom is included in the launcher;
Minecraft bloom depends on the user's shader setup. Use `flat_emissive_texture`
for a flat variant's mask. Complete packages allow up to four embedded PNGs.
Use the exact `emissive_texture` spelling. Opaque black pixels in this overlay
cover the base artwork; nonluminous mask areas need zero alpha.
`separate_feathers: true` preserves each feather's curved rest geometry and rig;
include it when using per-box `feather` indices. `flat_texture` supplies the optional flat wing variant's PNG.
The publisher embeds textures and geometry into a data-only package; it never
uploads executable scripts. Models allow up to 2,048 boxes, 16 feather guides,
2,048-pixel PNG textures and **2 MB** per complete package. Arbitrary OBJ,
Blockbench project files and executable mods must be converted to this format.

Run the same publishing script. Cubeon verifies checksums, validates the package,
and stores each revision in its own local directory. Downloaded models join the
existing Pets/Back/Head/Feet libraries; old equipped revisions and bundled artwork remain
available. When equipped, their geometry is written beside the instance selection
file and textures are installed through a dedicated `cubeon-store` resource pack.
The pack format follows the exact launch target and inherited client JAR, including
JSON-only Fabric profiles. Formats 65 and later use `min_format`/`max_format`
without the deprecated `supported_formats` key; Minecraft rejects that key for
these packs. Prelaunch restores the pack selection after repairing its metadata.
Other selected resource packs and graphics settings are preserved. **Restart
Minecraft after equipping a newly downloaded model** so its textures load.
Downloaded models have a Delete action in their Pets/Back/Head/Feet library
cards. Deleting an equipped item clears only that slot, removes its local
revision and unused generated textures, and leaves the Store entry available
to download again. Deleting the last equipped downloaded model disables only
the generated Store pack; other resource packs and saved appearance stay intact.

Collection wings use the built-in Giant hinge `(2, 2, 2.25)` and layered roots
against the back. The launcher adapts legacy collection packages on read,
preserving source files, textures, revision IDs and checksums. Other authored
rigs stay unchanged. Downloaded wings share the built-in render-only Elytra
replacement: Minecraft's resource manager validates their artwork, and resource
reloads clear cached readiness. Missing artwork preserves vanilla Elytra;
equipment and flight behavior stay unchanged.

These models require Cubeon Client on supported Fabric/Quilt versions; the Rust
beta and vanilla Minecraft cannot render them. Downloads do not equip items.
Custom store models are local; other players need the same model installed for
its id to resolve. The peer service currently publishes bundled IDs only;
custom models are cleared from that optional publication so they do not prevent
skin or bundled-cosmetic updates. Existing bundled cosmetics retain their shared visibility.

Complex downloaded wings, pets and wearables use cached coplanar preview textures in
`cubeon/cosmetic_preview.py`. Curved planes, UV colors, normals, depth and glow
remain separate; full game geometry is unchanged. The launcher character renders at
160×220 without supersampling or a second render after dragging. It keeps raised
skin caps, solid cosmetic surfaces, transparency and glow, omitting fine voxel/wing
walls at every angle. Its displayed size and camera fitting stay the same.
Camera fitting uses the original mesh bounds,
and the revision/file-aware cache is limited to 24 entries and 64 MiB. Solid pet
and wearable side surfaces remain visible during dragging. Plane sampling fits
the viewport resolution; returning to cached items reuses their prepared faces.
Launcher cosmetic cards render at 64×64 and omit subpixel feather walls; the reference
renderer and public exports retain full detail. Both rasterizers shade sampled visible
pixels instead of entire source atlases. Card images decode near their displayed size.
One draining thumbnail worker per section renders only the open pane and active filters,
defers hidden cards until they return, and drops jobs for removed cards. Pane returns and
selection changes retain the existing image controls and cached frames.
Categories reuse `ui.chrome.TabPane` and `TabEntryQueue`: their retained Stack
sends visibility changes before preparation. Native catalogue reads and card builds
run on one page-context worker; rapid clicks keep only the latest pending category.
Cached returns skip unchanged picker repaint, and refreshed library generations prevent
a late build from restoring deleted items. Headless fixtures still prepare inline.
Run `python tools/test_cosmetic_preview.py` for visual/performance regression
checks. `python tools/test_cosmetic_store_native.py 1.21.11` verifies pack
acceptance and real base/glow GPU textures in a temporary copy of an installed
world; it requires cached Minecraft, Fabric API and a graphical desktop.

The original reference-inspired owner collection can be regenerated locally:

```bash
python tools/gen_cosmetics.py --store-collection
./publish-cosmetics.sh --dry-run
```

This replaces the generator-owned files under each kind's `collection/`
subfolder. Keep manual designs outside those subfolders. It generates layered
feathers, curved membrane wings, companions, headwear and sneakers; it does
not upload anything. Review the generated models before running the publisher.
Normal client builds regenerate the bundled art only.

## Website gallery

The public `/store` page reads the same Neon catalog as the launcher, including
headwear, footwear and auras. Category filters, search and item previews work in the
browser; downloads and equipping stay in Cubeon. New uploads appear through the
API without a website deployment.
Validated pages update the gallery as they arrive, within a 60-second overall
loading deadline. If a later page fails, confirmed items remain alongside the
offline collection. Only a complete catalog removes outdated fallback entries.

For larger public previews of the owner collection, run:

```bash
python tools/prepare_store_gallery.py
```

This reuses validated packages and the launcher's renderer to update the Store's
HTML fallback and `web/assets/store/` WebP images. Images match the full package
checksum, so a changed revision uses its API thumbnail until the larger preview
is regenerated and deployed. The generator does not write to Neon. The static
collection remains readable when JavaScript or the catalog is unavailable.

## Deploy the public API

Set **NEON_DATABASE_URL** in the existing Cubeon Vercel project's server
environment, then deploy the tested website changes. Use a database role with
`SELECT` access to `cubeon_cosmetics` for the server when managing roles;
keep the owner's publishing credential separate. The local `.env` file is
ignored and does not configure a production deployment.
An existing Neon `DATABASE_URL` supplied by the Vercel integration also works;
`NEON_DATABASE_URL` takes precedence when both are present.

Both existing hosting layouts are supported: `web/api/cosmetics.js` for a
`web/` project root and `api/cosmetics.js` for a repository-root project.
The server helper in `web/server/neon.js` must deploy with the function.
No new Node or Python dependencies are required.

The default launcher address is `https://www.ylet.online/api/cosmetics`.
For a development server or another deployment, set `CUBEON_COSMETICS_API`
to its endpoint. HTTPS is required except for localhost testing; it must
contain no credentials or query string.

## Public protocol

| Request | Result |
| --- | --- |
| `GET /api/cosmetics?offset=0` | Schema 1, up to 12 cape entries and `has_more`, for older clients |
| `GET /api/cosmetics?offset=0&kind=all` | Schema 1, up to 12 cape/pet/wing entries and `has_more`, for original store-model clients |
| `GET /api/cosmetics?offset=0&kind=all&models=2` | Schema 1, up to 12 entries including headwear/footwear and `has_more` |
| `GET /api/cosmetics?offset=0&kind=all&models=3` | Schema 1, up to 12 entries including auras and `has_more`; separate cache from older catalogs |
| `GET /api/cosmetics?id=ID&sha256=SHA256` | Published PNG/GIF or model-package bytes pinned to the advertised checksum |
| `HEAD` on either route | The same headers, without a body |
| Any write method | 405; there is no public upload or database query route |

Catalogs cache for 60 seconds; checksum-pinned downloads cache immutably.
The four catalog variants have separate caches. `models=2` and `models=3` are accepted only
with `kind=all` on catalog requests. Deploy this API update before publishing
headwear/footwear or releasing the expanded client so older clients retain a
usable catalog.
An outdated download id/checksum returns 404, so Refresh retrieves the latest
catalog. Conditional requests use ETags. Database errors return a generic 503
without connection strings or upstream details. Metadata fetches coalesce
within one server instance. Limits are 120 requests/minute/address and eight
concurrent operations **per instance**; configure Vercel's firewall for shared
enforcement if needed. No raw addresses are logged or retained by the function.

Cubeon fetches only on first opening Store, an explicit Refresh, or page
navigation. Hidden completions stay cached. Transfers use the pooled network
transport and download gate, enforce file/preview bounds and verify SHA-256
before import. Local files and metadata commit through the existing atomic
cape importer. Repeat downloads reuse the local revision; deleting that cape
allows a new import. Downloads never change the active cape.

## Verification

```bash
node worker/test-neon-cosmetics.cjs
python tools/test_cosmetics_store.py
python tools/test_cosmetic_packages.py
python tools/test_cosmetics_picker.py
python tools/test_capes.py
python tools/test_gif_capes.py
```

These are offline tests. Separately verify the deployed endpoint and download
the Neon sample into an isolated launcher library; local tests do not establish
production deployment health.

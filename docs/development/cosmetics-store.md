[Documentation](../README.md) / Development

# Neon cosmetics store

Cubeon's **Cosmetics → Store** downloads capes, animated GIF capes, pets,
wings, headwear and footwear from the public website API. Downloads appear in
**Cape**, **Pets**, **Back**, **Head** or **Feet**; the user explicitly selects an item to equip it. Custom capes use the
existing importer and animation support. Pets and wings use Cubeon's existing
box/feather geometry, texture atlas and animation rig.

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
`wings/`, `head/` and `feet/` folders, and example recipes under `examples/`. It preserves existing
files. The examples are not uploaded.

Put PNG or GIF capes in `cosmetics/capes/`, then run:

```bash
./publish-cosmetics.sh --dry-run  # validate without credentials or uploads
./publish-cosmetics.sh            # publish new/changed cosmetics to Neon
```

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
deleting its bytes. Clients may retain cached catalog entries for 60 seconds.

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
Boxes use
`origin`, `size`, `uv`, `px`, and optionally `pivot`/`motion` for the existing
animation rig. `float` adds gentle hovering; `hover_body` and `hover_head`
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
Other selected resource packs and graphics settings are preserved. **Restart
Minecraft after equipping a newly downloaded model** so its textures load.
These models require Cubeon Client on supported Fabric/Quilt versions; the Rust
beta and vanilla Minecraft cannot render them. Downloads do not equip items.
Custom store models are local; other players need the same model installed for
its id to resolve. The peer service currently publishes bundled IDs only;
custom models are cleared from that optional publication so they do not prevent
skin or bundled-cosmetic updates. Existing bundled cosmetics retain their shared visibility.

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
headwear and footwear. Category filters, search and item previews work in the
browser; downloads and equipping stay in Cubeon. New uploads appear through the
API without a website deployment.

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
| `GET /api/cosmetics?id=ID&sha256=SHA256` | Published PNG/GIF or model-package bytes pinned to the advertised checksum |
| `HEAD` on either route | The same headers, without a body |
| Any write method | 405; there is no public upload or database query route |

Catalogs cache for 60 seconds; checksum-pinned downloads cache immutably.
The three catalog variants have separate caches. `models=2` is accepted only
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

[Documentation](../README.md) / Development

# Neon cosmetics store

Cubeon's **Cosmetics → Store** downloads free capes from the public website API.
Downloads appear in **Cape**; the user explicitly selects a cape to equip it.
This uses the existing cape importer, previews, animation support and instance
sync. A custom cape is visible locally; other players still see the shared
Cubeon cape under the existing skin service contract.

The first catalog contains one **Cubeon Cape Sample**, using the original
bundled `assets/capes/cubeon_cape.png` artwork. Publishing an additional PNG
or GIF cape requires no launcher or client JAR rebuild. Back items and pets
retain the generated launcher/JAR catalog described in
[the architecture guide](../architecture/overview.md).

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
| `GET /api/cosmetics?offset=0` | Schema 1, up to 12 metadata entries and `has_more` |
| `GET /api/cosmetics?id=ID&sha256=SHA256` | Published PNG/GIF bytes pinned to the advertised checksum |
| `HEAD` on either route | The same headers, without a body |
| Any write method | 405; there is no public upload or database query route |

Catalogs cache for 60 seconds; checksum-pinned downloads cache immutably.
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
python tools/test_cosmetics_picker.py
python tools/test_capes.py
python tools/test_gif_capes.py
```

These are offline tests. Separately verify the deployed endpoint and download
the Neon sample into an isolated launcher library; local tests do not establish
production deployment health.

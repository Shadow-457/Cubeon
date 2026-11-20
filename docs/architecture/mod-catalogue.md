# Individual mod catalogue

For Java instances, Mods searches Modrinth and CurseForge concurrently. Each page requests 24
results per provider, interleaves them without changing either provider's
order, and displays up to 48 provider results. Provider offsets and exhaustion
are independent. Healthy results remain usable during a partial outage.
Instance/query generations prevent old responses from painting a new search.

`cubeon/mod_catalogue.py` owns CurseForge normalization, provider identities,
link parsing and required-dependency traversal. Existing functions in
`cubeon/mods.py` default to Modrinth and accept a `source` keyword or a qualified
`curseforge:<project-id>` reference. Search, details, versions and downloads
support explicit `force` refresh. Empty results expire after one minute;
failed requests must not become authoritative "No matching build" verdicts.

CurseForge requests reuse the existing modpack credential and HTTP layer.
Individual mods use game 432, class 6, exact game-version strings and the
official loader enums: Forge 1, Fabric 4, Quilt 5, NeoForge 6. Missing credentials
produce a visible provider error, rather than pretending the catalogue is empty.
Categories have an explicit Modrinth-to-CurseForge mapping.

Search summaries cannot establish incompatibility. Filtered matches carry their
Minecraft/loader target; installation resolves and validates a matching release.
Pasted project/file links preserve provider and optional file identity. Release
history is fetched in bounded pages on demand. A compatible file that cannot be
downloaded directly offers its official page and the existing local-import flow.

Source-qualified identities key rows, artwork, install claims and dependency
lookups. Sidecars add `source`, `file_id` and `icon_url` alongside the existing
project ID, slug and URL. Identified legacy sidecars default to Modrinth;
anonymous local JARs stay anonymous. Identical names or IDs from different
providers do not establish that two projects are the same mod.

CurseForge installation resolves required provider dependencies before publishing
the main file, with cycle and request limits. Downloads share checksum/host
verification, the global store, cancellation and captured instance destinations.
Both new and cached CurseForge JARs are checked against their internal loader and
Minecraft declarations before publication. Older same-project builds are retained
disabled. The final actual-JAR graph check stays offline and read-only; resolving
remaining requirements or replacing unrelated roots uses the explicit Resolve flow.

The regression fixture uses CurseForge project 1511174/file 9215662: the original
Modrinth Immersive Portals project has no Fabric 1.21.11 release, while this
CurseForge project supplies one. See `tools/test_mod_catalogue.py` and the focused
checks in [Testing](../development/testing.md).

## Horizon content mods for Rust

The same Mods view uses Horizon when the captured instance ID is
`cubeon-rust-26.3`. `cubeon/rust_mods.py` reads the public schema-1 API at
`https://horizon-rust.github.io/horizon-mods/index.json`, reusing `local_cache`
with a five-minute freshness interval, offline catalogue fallback and explicit
Retry. Healthy entries survive malformed projects/releases; duplicate project
IDs are excluded. Browse pages contain 24 results. Java's default provider list
stays Modrinth/CurseForge.

Search, details, release selection and install claims use `horizon:<id>`
identities. Only 26.3 content packages with API 0.2 and the `registries`
capability are installable. Native and WebAssembly releases remain blocked
with an explanation; no engine build or upgrade is started. The existing
Java dependency/compatibility checks do not run for Rust.

Before publication, downloads verify the registry's size, SHA-256 and minisign
signature when supplied, then validate the package manifest and content fence.
Only the registry's/project's GitHub release URLs and GitHub asset redirects
are accepted. Original bytes share the existing global mod download cache.
Unsigned projects are identified in details and still require their published
checksum. An installed signing key cannot silently change.

Cubeon's fork expects `cubeon-mod.toml`, `data/<id>/cubeon/` declarations and
`cubeon:` built-in identifiers. The adapter translates those from Horizon's
equivalents after verification, preserving artwork, licenses and unchanged JSON
bytes. Local `.hmod` imports use the same validation/conversion without network
access. Java JARs, code packages, unsafe archives and namespace replacement are
refused. This format conversion does not make native code compatible; content
packages that depend on a separate native mod still need that mod's engine
support, as described on their project page.

Adapted packages are regular files at
`CUBEON_HOME/rust/instances/26.3/cubeon-mods/<id>.hmod`. Source receipts retain
the original SHA-256 for revocations and the Horizon release ID for updates.
Publication restores the previous package, receipt and enable settings on
failure. New installs are enabled; updates preserve the existing enabled state.
Enable/disable writes `mod.<id>:true/false` to `cubeon-mods.txt`, preserving other
mods and key bindings. Cached revocations refuse installs and disable known
installed copies with their reason. Changes apply on the next game launch.

`tools/test_rust_mods.py` covers these contracts and captured launcher targets.
The native world probe accepts `--content-mod /path/to/adapted.hmod` to verify
the content overlay, custom registries, rendered terrain and save/reopen against
an installed Cubeon runtime.

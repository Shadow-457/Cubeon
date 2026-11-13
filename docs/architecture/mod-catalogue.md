# Individual mod catalogue

Mods searches Modrinth and CurseForge concurrently. Each page requests 24
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

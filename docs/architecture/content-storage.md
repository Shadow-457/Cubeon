# Content Storage Architecture

This document describes how Cubeon manages mods, modpacks, resource packs, shaders, and other game content.

## Overview

Cubeon uses a **global store + per-profile links** model:

- **Global store**: `~/.cubeon_minecraft/global_mods/` - single copy of each mod jar
- **Profile directories**: `~/.cubeon_launcher/mod_profiles/<mc_version>-<loader>/` - symlinks into global store
- **Launch-time staging**: `launch.py` calls `content.sync_content_to_game(mc_version, loader)` to stage content into the actual game directory

This ensures:
- No duplicate jars across profiles
- Atomic installs/updates
- Easy cleanup

## Key Modules

### `cubeon/global_mod_cache.py`
Manages the global mod store:
- `download_mod()` - downloads to unique temp file, validates, then atomically publishes to global store
- `link_into_profile()` - creates symlink/hardlink/copy in profile directory
- `cleanup()` - removes unreferenced jars from global store
- Concurrency-safe with lock-guarded index writes

### `cubeon/mods.py`
Mod management logic:
- `install_mod_with_dependencies()` - downloads main mod + missing required dependencies
- `mod_doctor()` - auto-repair: duplicate detection, missing deps, version conflicts, incompatible loaders
- `required_dependencies()` - reads Modrinth's latest-version `dependencies` (only `required` type)
- `read_mod_metadata()` - unzips `fabric.mod.json`/`quilt.mod.json` for local `depends`/`breaks`/`id`
- `version_satisfies()` - implements Fabric/Maven version ranges

### `cubeon/modpacks.py`
Modpack handling:
- `install_modpack_from_url()` / `install_modpack_from_cf()` - two-phase: download archive, then install from zip
- `_install_from_zip()` - extracts, processes `modrinth.index.json` or `manifest.json`, installs each file
- Folder resourcepacks preserved as directories (not flattened)

### `cubeon/content.py`
Unified content interface (resource packs, shaders, modpacks):
- `download_content()` - downloads with resume/hash verification
- `list_content()` - lists installed content with compatibility info
- `sync_content_to_game()` - stages content for launch
- `delete_content()` - removes content and cleans up

### `cubeon/doctor.py`
**Single entry point** for all content validation:
- `run_doctor(mc, loader, auto_fix, include=...)` covers mods, resourcepacks, shaders, modpacks, server plugins
- Sections independent; `include=` scopes a run
- Called at launch with `check_online=False` for best-effort pre-repair

### `cubeon/packformat.py`
Single source of truth for "will the game accept this file?":
- `pack_verdict()` - resource pack format validation (pack_format, supported_formats, min-max keys)
- `shader_verdict()` - shader folder structure validation
- `repair_pack()` - widens declared range to cover installed versions

## On-Disk Layout

```
~/.cubeon_minecraft/
├── global_mods/                    # Global store (one copy per mod)
│   ├── fabric-api-0.100.0+1.21.jar
│   ├── sodium-0.6.0+1.21.1.jar
│   └── index.json                  # Tracks: sha256 -> {project_id, version, ref_count}
│
├── mod_profiles/                   # Per-version/loader profiles
│   ├── 1.21.1-fabric/
│   │   ├── mods/                   # Symlinks to global_mods/
│   │   ├── resourcepacks/
│   │   └── shaderpacks/
│   └── 26.1-neoforge/
│       └── mods/
│
└── global_content/                 # Global store for packs/shaders
    ├── resourcepacks/
    └── shaderpacks/

~/.cubeon_launcher/
├── mod_profiles/                   # Symlink farm (legacy compat)
├── cache/                          # Downloaded jars before global store
└── local_cache/                    # API response cache (Modrinth, CurseForge, etc.)
```

## Install Flow

```
User clicks "Install" in Mods tab
       ↓
ui/mods_tab.py:on_download()
       ↓
mods.install_mod_with_dependencies()
       ↓
global_mod_cache.download_mod()  →  unique temp file → validate → os.replace() to global store
       ↓
global_mod_cache.link_into_profile()  →  symlink/hardlink/copy into profile
       ↓
mod_doctor() auto-fix (optional)
```

## Modpack Install Flow

```
User provides modpack URL/CurseForge ID
       ↓
modpacks.install_modpack_from_url() / install_modpack_from_cf()
       ↓
Phase 1: Download archive (unknown size) → progress: "Downloading modpack... 42%"
       ↓
Phase 2: _install_from_zip() → extract → parse index/manifest → install each file
       ↓
       progress: "Downloading mods... 12/345" (FILE UNITS, not bytes)
       ↓
global_mod_cache for each mod → link into profile
```

## Content Compatibility

- `content.py` drops search results whose file list has no build for the selected MC version **before** they render
- `get_content_download()` re-checks at download time (defense in depth)
- Installed-but-incompatible items still show — with a badge + one-click doctor fix
- Launch pre-repair: `launch.py` calls `run_doctor(..., include=("mods", "resourcepacks", "shaders"), check_online=False)`

## Folder Packs Are First-Class

- Pack format verdicts/repair accept UNZIPPED pack directories
- Doctor's content scan (`_iter_content_packs`) handles directories
- `content.list_content`/`delete_content` accept directories
- Dir repair = atomic `pack.mcmeta` write + `_flatten_dir` (refuses to merge over existing root entry)
- `list_content` items carry `folder: True`
- CONTENT_TYPES keys are singular (`"resourcepack"`, `"shaderpack"`) - `list_content('resourcepacks')` raises

## Tests

- `tools/test_mod_store.py` - global mod store (27 checks, concurrency + copy-failure)
- `tools/test_mod_detail.py` - mod detail + auto-repair (81 checks)
- `tools/test_modpacks.py` - modpack installs (64 checks)
- `tools/test_mod_install_progress.py` - install progress in FILE UNITS (39 checks)
- `tools/test_content_doctor.py` - unified doctor (88 checks)
- `tools/test_csl.py` - CustomSkinLoader registration (14 checks)
- `tools/test_capes.py` - cape pipeline (19 checks)
- `tools/test_gallery.py` - local library pipeline (32 checks)
- `tools/test_perf_mods.py` - Sodium/Lithium auto-install (17 checks)
- `tools/test_mod_matrix.py` - brackets/jar routing (68 checks)
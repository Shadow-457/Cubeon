"""
launcher_core - backward-compatible facade.

All real logic now lives in the cubeon/ package, split by concern
(paths, config, versions, mod_loaders, mods, launch, skins, server,
profile) instead of one 1400+ line file. This module just re-exports
everything under the old names so main.py / mods_tab.py / server_tab.py /
skin_tab.py can keep doing `import launcher_core as core` unchanged.

See cubeon/mods.py and cubeon/launch.py docstrings for what was actually
wrong with mods/Fabric/Forge before and how it's fixed now.
"""

# --- paths ---
from cubeon.paths import (
    APP_NAME, MINECRAFT_DIR, MODS_DIR, CONFIG_PATH,
    SKINS_DIR, SKINS_META_PATH, PFP_DIR, SERVERS_DIR,
    CAPES_DIR,
    PROFILES_DIR,
    MOD_META_SUFFIX, PROFILE_META_FILENAME,
    CSL_DIR, CSL_CONFIG_PATH, CSL_LOCAL_SKINS_DIR, CSL_EXTRALIST_DIR,
    RESOURCEPACKS_DIR, SHADERPACKS_DIR,
)

# --- config / auth / file picker ---
from cubeon.config import (
    DEFAULT_CONFIG, load_config, save_config,
    load_window_geometry, save_window_geometry,
    offline_uuid, validate_username, run_file_picker,
    get_system_ram_mb, recommended_max_ram_mb,
    ensure_auth_key, stable_uuid, stable_secret, AUTH_KEY_PATH,
)

# --- backup system ---
from cubeon import backup as backup_module

# --- versions ---
from cubeon.versions import (
    get_installed_versions, suggest_friendly_name, extract_mc_version,
    get_available_versions, get_latest_release, install_version,
    delete_version,
)

# --- mod loaders ---
from cubeon.mod_loaders import (
    SUPPORTED_LOADERS, MOD_CAPABLE_LOADERS,
    is_loader_supported, is_fabric_supported,
    find_installed_loader_version, install_mod_loader, install_fabric,
)

# --- launch ---
from cubeon.launch import (
    find_java,
    find_java_for_version,
    java_major_version,
    required_java_major,
    build_launch_command,
    launch_game,
)

# --- mods ---
from cubeon.mods import (
    MODRINTH_API, MODRINTH_HEADERS, RECOMMENDED_MOD_SLUGS, MOD_CATEGORIES,
    profile_key, get_profile_dir, list_profiles,
    list_mods, toggle_mod, delete_mod, add_mod_file, open_mods_folder,
    install_local_mod, sync_mods_to_game, copy_mods_between_profiles,
    get_recommended_mods, search_mods, get_mod_download, download_mod,
    installed_project_ids, required_dependencies, install_mod_with_dependencies,
    get_mod_icons, get_mod_details, get_mod_versions, mod_doctor,
)

# --- modpacks (Modrinth .mrpack: install a whole version+loader+mods bundle) ---
from cubeon.modpacks import (
    ModpackError, summarize as summarize_modpack,
    install_modpack_from_file, install_modpack_from_url,
    install_modpack_from_cf, curseforge_enabled,
    search_modpacks, get_popular_modpacks, get_modpack_file,
    # split search phases the Modpacks tab renders incrementally (Modrinth
    # first, CurseForge merged in when its slower fetch lands)
    search_modpacks_modrinth, search_modpacks_curseforge, merge_modpack_hits,
    list_installed_modpacks, export_mrpack, forget_modpack_for_version,
)

# --- resource packs & shaders (shared, version-agnostic game folders) ---
from cubeon.content import (
    CONTENT_TYPES, content_dir, category_choices,
    list_content, delete_content, install_local_content, open_content_folder,
    is_installed as content_installed,
    search_content, get_recommended_content, get_content_download, download_content,
)

# --- emoji (Discord-style :shortcode: expansion for chat) ---
from cubeon.emoji import expand_emoji, all_shortcodes, SHORTCODES

# --- skins ---
from cubeon.skins import (
    validate_skin_file, list_custom_skins, add_custom_skin, delete_custom_skin,
    get_custom_skin_path, set_active_skin, skin_mod_installed,
    sync_local_skin_to_csl,
    render_local_skin_preview, get_skin_face_url,
    name_contested,
)

# --- custom capes (upload/store/preview + LocalSkin sync, mirrors skins) ---
from cubeon.capes import (
    validate_cape_file, list_custom_capes, add_custom_cape, delete_custom_cape,
    get_custom_cape_path, set_active_cape, sync_local_cape_to_csl,
    render_cape_preview,
)

# --- cosmetics (pixel hats baked into the skin's hat layer) ---
from cubeon.cosmetics import (
    list_hats, set_hat, apply_hat_layer, compose_skin_with_hat,
    render_hat_preview, preview_composed_body, hat_requirement, hat_unlocked,
)

# --- gallery (LOCAL skins/capes library; see cubeon/gallery.py) ---
from cubeon.gallery import (
    list_gallery_skins, list_gallery_capes,
    install_gallery_skin, install_gallery_cape,
    load_player, gallery_id_for_file, forget_file, ensure_gallery,
    featured_cached_count, prefetch_featured, suggest_player,
    featured_count, all_gallery_items, matches_query,
    SKIN_LIBRARY_DIR, CAPE_LIBRARY_DIR,
)


# --- milestones (earnable hats; see cubeon/milestones.py for the KV budget) ---
from cubeon.cosmetics import hat_unlocked as _hat_unlocked  # noqa: F401 (re-export clarity)
from cubeon.milestones import (
    MILESTONES as _MILESTONE_TABLE, evaluate as milestones_evaluate,
    add_play_seconds as milestones_add_play_seconds,
    add_hosted_session as milestones_add_hosted,
    note_friends_count as milestones_note_friends,
    begin_play_session as milestones_begin_play_session,
    end_play_session as milestones_end_play_session,
    reconcile_play_session as milestones_reconcile_play_session,
)


def milestone_name(milestone_id):
    """Display name of a milestone id (for toasts/console notes)."""
    for m in _MILESTONE_TABLE:
        if m["id"] == milestone_id:
            return m["name"]
    return milestone_id

# --- CustomSkinLoader setup (auto-install + registering Cubeon's sources) ---
from cubeon.csl import (
    CUBEON_SKIN_API_ROOT, CSL_MODRINTH_SLUG, EXTRALIST_ENTRIES,
    read_csl_config, registered_names, pending_names, is_registered,
    is_installed as csl_installed,
    write_extralist_entries, remove_pending_entries,
    install as install_skin_mod, ensure_ready as csl_ensure_ready,
)

# --- server ---
from cubeon.server import (
    DEFAULT_SERVER_PROPERTIES, get_server_dir, is_server_installed,
    eula_accepted, set_eula_accepted, install_server, find_local_paper_jar,
    get_server_properties, save_server_properties, is_server_running,
    # remove a version's whole server folder (jars, world, properties, plugins)
    delete_server,
    # a server left running by a previous Cubeon process (detached, so it
    # survives a launcher restart and keeps the world's session.lock held)
    is_server_orphaned, stop_orphaned_server, world_lock_holder,
    start_server, send_server_command, stop_server, get_local_lan_address,
    # real whitelist management (whitelist.json + live console commands)
    get_whitelist, add_to_whitelist, remove_from_whitelist, is_whitelisted,
    # server type (Paper only - vanilla hosting was removed 2026-08-26)
    SERVER_TYPE_PAPER, SERVER_TYPES,
    get_server_type, set_server_type, switch_server_type, get_installed_server_types,
    # high-ping / low-latency optimization preset
    high_ping_optimization_enabled, set_high_ping_optimization,
    # per-player distance caps (server.properties view/simulation distance)
    VIEW_DISTANCE_RANGE, SIMULATION_DISTANCE_RANGE, clamp_distance,
    # open the server's folder on disk
    open_server_folder,
    # plugins (Paper only)
    list_plugins, toggle_plugin, delete_plugin, install_local_plugin,
    get_recommended_plugins, get_low_ping_plugins, search_plugins,
    get_plugin_download, download_plugin,
    # Smooth mode auto-installs the curated low-ping stack
    ensure_smooth_mode_plugins,
    # managed defaults (AuthMe login security) - auto-installed at start,
    # protected from deletion
    ensure_default_plugins, is_protected_plugin_stem,
)

# --- profile picture ---
from cubeon.profile import (
    validate_pfp_file, set_profile_picture,
    get_profile_picture_path, clear_profile_picture,
)

# --- Minekube Connect tunnel: letting friends join over the internet ---
# Imported as a module rather than flattened names because several of its
# functions have names far too generic to re-export bare (`status`,
# `install`, `address`).
from cubeon import minekube
from cubeon import invites

# --- CubeonGate: the server password gate (per-UUID, enforced pre-spawn) ---
from cubeon import gate

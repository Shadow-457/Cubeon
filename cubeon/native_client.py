"""Bind the native companion to Cubeon's existing appearance and loopback services.

Rust reads the same LocalSkin mirrors as Java CSL. No Java mod or second account
is installed into the native game, and the launcher keeps ownership of cosmetics.
"""
from pathlib import Path
from . import atomicio, paths


def prepare(cfg: dict, game_dir: str, username: str) -> dict[str, str]:
    from . import csl, cosmetics, skins, capes, local_api
    # These mirror functions preserve hand-managed files, rename ownership,
    # explicit skin models and the transparent cape used for Hide.
    skins.sync_local_skin_to_csl(cfg)
    capes.sync_local_cape_to_csl(cfg)
    cosmetics.sync_to_game(cfg, game_dir)
    directory = Path(game_dir) / "config"
    directory.mkdir(parents=True, exist_ok=True)
    appearance = {
        "schema": 1,
        "enabled": bool(cfg.get("csl_enabled", True) and cfg.get("manage_skin_mod", True)),
        "username": username,
        "localSkinDir": paths.CSL_LOCAL_SKINS_DIR,
        "localCapeDir": paths.CSL_LOCAL_CAPES_DIR,
        "localElytraDir": str(Path(paths.CSL_DIR) / "LocalSkin" / "elytras"),
        "model": "slim" if skins._active_skin_is_slim(cfg.get("active_skin")) else "classic",
        "publicRoot": csl.CUBEON_API_BASE,
    }
    atomicio.write_json(str(directory / "cubeon-native-appearance.json"), appearance)
    from .features import friends_enabled
    return {"CUBEON_BRIDGE_FILE": str(local_api._TOKEN_FILE),
            "CUBEON_CLIENT_ENABLED": "1" if friends_enabled() and cfg.get("client_mod_enabled", True) else "0"}

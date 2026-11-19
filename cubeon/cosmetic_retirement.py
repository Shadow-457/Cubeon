"""Stable identities of designs removed from the public/local collection."""

STORE_IDS = frozenset({
    "cubeon-morpho-orbit", "cubeon-zephyr-sprite", "cubeon-dune-runner-cap",
    "cubeon-cloudlet-headwings", "cubeon-dawnflare-halo",
})
BUNDLED_IDS = frozenset({"head_crown", "head_halo"})


def retired(item):
    return item.get("id") in BUNDLED_IDS or item.get("store_id", item.get("id")) in STORE_IDS

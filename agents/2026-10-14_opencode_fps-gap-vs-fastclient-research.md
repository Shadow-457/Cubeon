# 2026-10-14 — RESEARCH: Cubeon ~500 FPS vs FastClient ~900 FPS (memory + GC + settings)

**Research only — no code changed.** Another agent owns the codebase. Everything
below is measured from the live installs on this box (`.cubeon_minecraft`,
`.fastclient`) and from the real `1.21.11.jar` (decompiled with `javap`).
NOTE: the two F3 screenshots the user posted could not be loaded (this model has
no image input), so the numbers here come from the user's text (500 vs 900) and
from filesystem evidence, not from reading the images.

## TL;DR
1. The **memory pattern the user noticed is fully explained and is NOT a leak**:
   Cubeon passes `-Xms = -Xmx` **plus** `-XX:+AlwaysPreTouch` (→ F3 "Allocated:
   100%") and a big G1 young gen (`G1NewSizePercent=30` → young GC only after
   ~1.2 GB fills → heap climbs to ~50% before it "cleans"). FastClient passes
   `-Xms512 -Xmx4096` and **no GC flags** → "Allocated: 28%", young GCs at ~20%,
   dropping to 7-12%. Allocation rate is identical (~205-207 MB/s) → it is
   purely GC policy, not workload.
2. **Two real bugs in `cubeon/game_options.py` "Max FPS" mode** (verified
   against 1.21.11.jar):
   - `particles:"0"` is labelled "Minimal" but **0 = ALL** (jar: ALL=0,
     DECREASED=1, MINIMAL=2). Max FPS mode is *maximising* particles.
   - `graphicsMode:"0"` (labelled "the biggest lever") **does not exist in
     1.21.11** — the live key is `graphicsPreset:"fast"`; `graphicsMode` only
     survives in a legacy DataFixer. `_set_options` skips absent keys, so this
     lever never applies on 1.21.11.
3. The **FPS gap itself is mostly renderer/mod/config**, not the JVM. Prime
   suspects (below): Cubeon's Sodium has `use_entity_culling:false` and
   `use_fog_occlusion:false` (FastClient: both `true`); Cubeon loads **18 mods
   incl. Wurst + XaeroWorldMap + Jade** vs FastClient's 9; Cubeon has 6 resource
   packs and `ao:true`/`graphicsPreset:"custom"` vs FastClient `ao:false`/"fast".

---

## 1. Memory / GC — the user's finding, explained

### Cubeon
- `cubeon/launch.py:587` → `jvm_args = [f"-Xmx{ram_mb}M", f"-Xms{ram_mb}M", ...]`
  with `ram_mb = 4096` (`.cubeon_launcher/config.json`). **`-Xms == -Xmx`.**
- `client_jvm_flags()` (`launch.py:336`) with `cores = 12` (E5-1650, via
  `os.sched_getaffinity`) takes the `>4` branch:
  `G1NewSizePercent=30`, `G1MaxNewSizePercent=40`, `MaxGCPauseMillis=200`,
  plus `G1ReservePercent=20`, `InitiatingHeapOccupancyPercent=15`, etc.
  → young-gen floor = **30% × 4096 ≈ 1229 MB** (max ≈ 1638 MB). A young GC only
  fires once eden is that full, so heap usage climbs to **~47-50%** first.
- `_pretouch_flag(4096, 23948MB)` (`launch.py:369`): system RAM (24 GB) ≥ 8 GB
  and heap (4096) ≤ half (11974) → returns **`-XX:+AlwaysPreTouch`** → the whole
  4 GB is committed *and faulted* at startup.
- Net: F3 **Allocated 100% (4096 MB)**; young GCs are **rare but large**, so the
  memory graph rises to ~50% then drops.

### FastClient
- `~/.local/share/FastClient/logs/fastclient.log` shows its real args:
  **`-Xms512 -Xmx4096`** and **no GC flags at all** (only vanilla
  `-XX:HeapDumpPath=...`).
- → F3 **Allocated 28% (1186 MB)**; JVM-default G1 young gen (adaptive, starts
  ~5%, `G1NewSizePercent` default 5) → young GC every few hundred MB → usage
  oscillates **~20% → 7-12%**.

### Verdict
Identical allocation rate (~205 vs ~207 MB/s) on both. The difference is 100%:
`Xms=Xmx` (+PreTouch) and `G1NewSizePercent=30` vs JVM defaults. Neither is a
leak, and neither directly costs steady FPS — the Aikar set is tuned for
*throughput/fewer pauses*, which is why it "cleans late". If the goal is
FastClient-like smoothness, the levers are `G1NewSizePercent` (→ ~5-10) and
dropping `Xms=Xmx`/`AlwaysPreTouch`.

### Java runtime differs (minor)
- Cubeon launches mll's managed JRE, **not** the system one:
  `~/.cubeon_minecraft/runtime/java-runtime-delta/.../bin/java` = **OpenJDK
  21.0.7** (F3 shows 21.0.7). System `java` = 21.0.12; `java-runtime-epsilon` =
  25.0.1 also present.
- FastClient profile `javaPath: "java"` (profiles.json) → PATH → **21.0.12**
  (its bundled `jdk-25.0.4.1` runtime is not what the game used here).
- Same major version → negligible FPS impact; noted for completeness.

---

## 2. Two verified bugs in `cubeon/game_options.py` (Max FPS mode)

`MAX_FPS_OPTIONS` currently is:
```
graphicsMode "0"            # "Fast graphics - the biggest lever after the renderer"
particles "0"               # "Minimal particles"
entityShadows "false"
entityDistanceScaling "0.75"
biomeBlendRadius "0"
syncChunkWrites "false"
```

### Bug A — `particles:"0"` is ALL, not minimal
From `1.21.11.jar` (`javap -c awx.class`, the `ParticleStatus` enum):
```
ALL        <init>("ALL",      ordinal 0, id 0, "options.particles.all")
DECREASED  <init>("DECREASED",ordinal 1, id 1, "options.particles.decreased")
MINIMAL    <init>("MINIMAL",  ordinal 2, id 2, "options.particles.minimal")
```
and the option is serialized via `Codec.INT.xmap(idToValue, valueToId)` — i.e.
options.txt stores the **id**. So **`particles:0` = ALL particles**; minimal is
`2`. Cubeon's `options.txt` really does contain `particles:0` (FastClient has
`particles:1` = Decreased), and `tools/test_perf_mods.py:297-314` encodes the
same wrong value (`particles:2` fixture → expects `particles:0`).

### Bug B — `graphicsMode` is dead on 1.21.11; the live key is `graphicsPreset`
From the same jar:
- `gfo.class` = the real **Options** class; its keys are `renderDistance`,
  **`graphicsPreset`**, `particles`, `maxFps`, `enableVsync`, `simulationDistance`.
  **No `graphicsMode`.**
- `bph.class` contains `graphicsMode`/`fancyGraphics` but it **extends
  `com.mojang.datafixers.DataFix`** — it is only a **legacy migration** rule.
- Real `options.txt` on both installs has `graphicsPreset:"fast"` (FastClient)
  / `"custom"` (Cubeon) and **no `graphicsMode`**. `_set_options` only rewrites
  keys already present → `graphicsMode` is reported as
  "skipped (not in options.txt yet)" and **the "biggest lever" never fires on
  1.21.11**. (On older versions where `graphicsMode` *is* live, the `0` value's
  meaning should be re-checked too.)

**Effect:** "Max FPS mode" on 1.21.11 delivers entityShadows/entityDistance/
biomeBlend/syncChunkWrites, but **not** fast graphics and **not** fewer
particles — it actually keeps ALL particles.

---

## 3. Where the ~500 vs ~900 FPS gap actually lives (ranked)

| # | Lever | Cubeon | FastClient | Notes |
|---|-------|--------|-----------|-------|
| 1 | Sodium `use_entity_culling` | **false** | **true** | Biggest single candidate. Launcher never writes sodium-options.json (verified: no repo hits) — user toggled or Sodium default. |
| 2 | Sodium `use_fog_occlusion` | **false** | **true** | Same story. |
| 3 | Mod load | **18 jars** | **9 jars** | Cubeon extra: **Wurst 7.54.1**, **XaeroWorldMap**, **Jade**, herobot, CustomSkinLoader, emotes, cubeon-client, cloth-config, moreculling, entityculling, ImmediatelyFast. FC extra: Krypton, fastclient-hud. Wurst + XaeroWorldMap are per-frame heavy. |
| 4 | graphics preset | `"custom"` + `ao:true` | `"fast"` + `ao:false` | Smooth lighting/AO on = costlier terrain shading + meshing. |
| 5 | Resource packs | 6 loaded | none | GUI/Low-fire/PvP + NewGlowingOres (emissive). |
| 6 | `mipmapLevels` | 4 | 2 | Mostly load-time. |
| 7 | `particles` | 0 (ALL) | 1 (Decreased) | See Bug A — Cubeon renders more, not less. |
| 8 | Sodium version | 0.8.12 | 0.8.14 | Minor. |
| 9 | `cloudRange` | 128 | 32 | Source unidentified (both files have the key). |
| — | renderDistance / simulationDistance | 8 / 6 | 8 / 6 | **Identical** (not a factor). |
| — | `chunk_builder_threads` | 2 | 2 | **Identical** (both low for 12 threads, but equal). |
| — | Allocation rate | ~207 MB/s | ~205 MB/s | **Identical** → workload is the same. |

Also present but not a factor: `graphicsPreset` values differ but both have
`renderClouds:"fast"`; `biomeBlendRadius` 0 vs 1 favours Cubeon.

**Not the cause:** the GC/Xms difference (steady-state FPS), Java 21.0.7 vs
21.0.12, and the `Allocated 100%` figure (that is committed heap, not usage).
Menu/pause FPS is also not representative — the gap must be re-measured in-world.

---

## 4. How to confirm (suggested A/B, no guessing)
1. In **Cubeon**, set Sodium → Performance → enable **Entity Culling** and
   **Fog Occlusion** (and match `ao:false`, `graphicsPreset:fast`), then re-check
   in-world FPS. This isolates lever #1-4.
2. Temporarily disable **Wurst** and **XaeroWorldMap** in the Cubeon profile;
   re-measure. This isolates lever #3.
3. Compare the F3 **pie chart** (F3+L) on both — that attributes frame time
   (terrain/entities/block entities) instead of guessing.

## 5. Verification commands used (reproducible)
- Cubeon launch args: `cubeon/launch.py:587` + `client_jvm_flags()` (launch.py:336)
  + `_pretouch_flag()` (launch.py:369); `cat /proc/meminfo` for the 24 GB gate.
- FastClient args: `grep -E '\-X[a-zA-Z:]+[0-9]' ~/.local/share/FastClient/logs/fastclient.log`.
- Enum/key proof:
  `unzip -o 1.21.11.jar 'awx.class' 'gfo.class' 'bph.class' && javap -p -c awx.class`.
- Config parity: `diff <(sort .fastclient/profiles/1.21.11-Fabric/options.txt) <(sort .cubeon_minecraft/options.txt)`.

## 6. Open questions for the next agent / user
- Who set Cubeon's Sodium `use_entity_culling:false` / `use_fog_occlusion:false`
  (mtime 10-14 14:15, i.e. today)? If the launcher should own these, that is a
  product decision, not a read-only fix.
- Confirm the intended `particles` and `graphicsPreset` values for Max FPS mode
  before changing `game_options.py` (and the matching `test_perf_mods.py`).
- `cloudRange` origin (128 vs 32) is unidentified.

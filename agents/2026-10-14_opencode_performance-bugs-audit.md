# 2026-10-14 — RESEARCH: performance bug audit (launcher "Max FPS" / GC / mod suite)

**Research + documentation only — NO code changed** (another agent owns the
codebase). Every claim below was checked against the live installs
(`~/.cubeon_minecraft`, `~/.fastclient`) and the real `1.21.11.jar`
(`javap`/`strings`), not guessed. Companion doc:
`agents/2026-10-14_opencode_fps-gap-vs-fastclient-research.md` (the 500-vs-900
FPS gap analysis).

Severity: **P1** = reduces FPS / startup on every launch; **P2** = measurable
but situational; **P3** = cosmetic/latent.

---

## A. `cubeon/game_options.py` — "Max FPS mode" bugs

### P1 — A1. `particles:"0"` is ALL, not Minimal (inverted)
`MAX_FPS_OPTIONS` sets `("particles", "0", "Minimal particles")`, but the value
is back-to-front. Proof from `1.21.11.jar`, `javap -c awx.class`
(the `ParticleStatus` enum):
```
ALL        ("ALL",       ordinal 0, id 0, "options.particles.all")
DECREASED  ("DECREASED", ordinal 1, id 1, "options.particles.decreased")
MINIMAL    ("MINIMAL",   ordinal 2, id 2, "options.particles.minimal")
```
and the option serializes through `Codec.INT.xmap(idToValue, valueToId)` → the
int stored in options.txt is the **id**. So `particles:0` = **ALL particles**;
minimal is **2**. Live evidence: Cubeon `options.txt` has `particles:0`;
FastClient has `particles:1`. Net effect: Max FPS mode currently *maximises*
particles.

### P1 — A2. `graphicsMode:"0"` is a DEAD key on 1.21.11
`("graphicsMode", "0", "Fast graphics - the biggest lever after the renderer")`
never fires. Proof:
- `gfo.class` (the real **Options** class) declares keys
  `graphicsPreset`, `particles`, `maxFps`, `enableVsync`, `renderDistance`,
  `simulationDistance`, `ao`, `renderClouds` — **no `graphicsMode`**.
- `graphicsMode`/`fancyGraphics` appear only in `bph.class`, which
  `extends com.mojang.datafixers.DataFix` → a **legacy migration** rule.
- Both live `options.txt` files carry `graphicsPreset:"fast"`/`"custom"` and no
  `graphicsMode`.
`_set_options` only rewrites keys already present, so this row is reported as
"skipped (not in options.txt yet)" and the "biggest lever" is a no-op on
1.21.11. The live key is **`graphicsPreset`** (valid: `fast`/`fancy`/
`fabulous`/`custom`, verified in `gfb.class`).

### P1 — A3. `_set_options` cannot idempotently write a quoted STRING option
This is the blocker for fixing A2. Demonstrated live:
```
options.txt = 'graphicsPreset:"custom"...'
_set_options(p, {"graphicsPreset": "fast"})    -> writes  graphicsPreset:fast      (UNQUOTED)
_set_options(p, {"graphicsPreset": '"fast"'})  -> writes  graphicsPreset:"fast"     changed=['graphicsPreset']
_set_options(p, {"graphicsPreset": '"fast"'})  -> changed=['graphicsPreset']  every run (NON-idempotent)
```
Cause (`game_options.py:97-108`): it compares `raw.strip().strip('"')` (bare)
but writes `f"{key}:{value}"` verbatim. So:
- a bare value → writes an **unquoted** string, which options.txt does not use
  for string options (`renderClouds:"fast"`), likely reset on load;
- a quoted value → correct text, but `current` never equals the quoted string,
  so it **rewrites and reports "changed" on every launch** (the "Max FPS options
  applied" toast fires every time; not idempotent).
Every current `MAX_FPS_OPTIONS` entry is int/bool so the bug is latent — but it
must be fixed before `graphicsPreset`/`renderClouds`/`ao` (string keys) can be
set correctly.

### P2 — A4. Ambient occlusion (`ao`) is left ON
Max FPS mode does not touch `ao`; Cubeon runs `ao:true` (from its "custom"
preset), FastClient runs `ao:false`. `ao` is a real terrain-shading/meshing
cost. Borderline "visual", but it is the one remaining default that FastClient
turns off as part of its fast preset.

### P3 — A5. The test encodes the same wrong values
`tools/test_perf_mods.py:297-314` seeds `graphicsMode:2`/`particles:2` and
asserts the result contains `graphicsMode:0`/`particles:0`. So the unit test
**pins** A1 and A2; any fix must update it too.

---

## B. `cubeon/launch.py` — Aikar **server** GC tuning shipped to a client

The client flag set (`client_jvm_flags()`, launch.py:336) is Aikar's
server-tuned G1 set. On a client — where GC shares cores with the render thread
— several values are pessimisations, not wins.

### P1 — B1. `-Xms == -Xmx` (+ `AlwaysPreTouch`) commits the whole heap
`build_launch_command` (launch.py:587) passes `-Xmx{ram}M -Xms{ram}M`, and
`_pretouch_flag` (launch.py:369) adds `-XX:+AlwaysPreTouch` whenever
`system_ram >= 8192` and `heap <= system_ram/2` — true here (24 GB, 4096 MB).
Result: F3 **"Allocated: 100% 4096 MB"** (vs FastClient 28%: `-Xms512 -Xmx4096`).
Costs commit-all + fault-all at startup and pins RSS for the session. FastClient
uses a small `-Xms` and lets the heap grow.

### P1 — B2. `G1NewSizePercent=30` / `G1MaxNewSizePercent=40` → the user's memory pattern
Young-gen floor = 30% × heap ≈ **1229 MB** at 4 GB (max ≈ 1638 MB), so G1 will
not run a young GC until eden is that full → heap rises to **~50%** before it
"cleans". That is exactly the user's observation ("Cubeon cleans when it goes to
50%+"). It also makes each young collection large (hundreds of MB copied on the
render-thread's cores). FastClient passes **no GC flags** → default G1 young gen
(starts ~5%) → GC at ~20%, dropping to 7-12%. Allocation rate is identical on
both (~205 vs ~207 MB/s), so this is purely young-gen sizing, not workload.

### P2 — B3. Other server-oriented values kept
`-XX:InitiatingHeapOccupancyPercent=15` starts concurrent marking at 15% heap →
more concurrent collectors competing with the render thread.
`-XX:G1ReservePercent=20` reserves 20% of the heap (only ~3.2 GB usable at 4 GB).
`-XX:SurvivorRatio=32` + `-XX:MaxTenuringThreshold=1` promote to old gen after a
single young GC → faster old-gen growth → more mixed cycles. All are Aikar
server values; on a CPU-bound client they cost frames. (Earlier work already
softened `MaxGCPauseMillis` 40→200 and added `G1HeapWastePercent=5`; these four
were left at server values.)

### P2 — B4. Default heap = half of system RAM
`config.recommended_max_ram_mb()` (config.py:67) returns
`system_ram // 2` rounded to 512 MB (24 GB box → **~11.7 GB**), and it is seeded
as the default on first run (config.py:229). Minecraft rarely benefits past
6-8 GB; combined with B1 it commits that up front. Over-large heaps lengthen GC
pauses and starve the rest of the system.

---

## C. `cubeon/perf_mods.py` + live mod/profile state

### P1 — C1. Cubeon loads 18 mods; FastClient loads 9
Cubeon game dir (`~/.cubeon_minecraft/mods/`) vs FastClient profile. The extras
that cost frame time every frame:
**Wurst-Client 7.54.1** (cheat client: ESP/tracers/HUD), **XaeroWorldMap**
(full map renderer), **Jade** (raycast tooltips), **herobot**, **emotes**,
**CustomSkinLoader**, **cubeon-client**, cloth-config. FastClient's extra is only
`krypton` (network) + its HUD. Wurst + XaeroWorldMap are the two to test first.

### P2 — C2. Stale Sodium pinned (no auto-update)
Profile holds **sodium 0.8.12**; FastClient has **0.8.14**. `perf_mods._present()`
treats any present build as "keep", so the launcher never refreshes it. Prior
work called this intentional (Iris pairing) — recorded here as a perf gap, not to
"fix" blindly.

### P2 — C3. Sodium's own culling is OFF (likely someone/something toggled it)
`~/.cubeon_minecraft/config/sodium-options.json`:
`use_entity_culling:false` and `use_fog_occlusion:false` (Sodium defaults are
`true`; FastClient has `true`/`true`). Verified the launcher **never writes**
sodium config (no `sodium-options` reference in `cubeon/` or `main.py`), so this
was toggled in-game or by another mod — worth confirming before "fixing". Both
configs share the same `chunk_builder_threads:2`.

### P3 — C4. Retired `Dynamic FPS`
`RETIRED_PERF_MODS` removes `dynamic-fps`. Dynamic FPS *lowers* FPS when the
window is unfocused (power/thermals). Removing it means full-speed rendering
while alt-tabbed — a cost when backgrounded, though FastClient also omits it, so
this is arguably intended.

### P3 — C5. Iris present with shaders disabled
`iris.properties` has `enableShaders=false` on Cubeon (FastClient `true` but no
shaderpack installed). Iris patches Sodium regardless of the toggle → small
overhead. Both sides carry Iris, so it is not a differentiator — noted for
completeness.

---

## D. `options.txt` non-launcher differences (context)

| Key | Cubeon | FastClient | Note |
|-----|--------|-----------|------|
| `graphicsPreset` | `"custom"` | `"fast"` | See A2. |
| `ao` | `true` | `false` | See A4. |
| `particles` | `0` (ALL) | `1` (Decreased) | See A1. |
| `mipmapLevels` | `4` | `2` | Mostly load-time. |
| `resourcePacks` | 6 packs | none | GUI/Low-fire/glow-ores. |
| `cloudRange` | 128 | 32 | Origin unidentified. |
| `renderDistance` / `simulationDistance` | 8 / 6 | 8 / 6 | **Identical.** |

---

## E. Checked and NOT bugs (so the next agent doesn't "fix" them)

- **`maxFps:260` is correct** — it is the slider maximum ("Unlimited").
  Proven: `gfo.class` `sipush 260` with `options.framerateLimit` +
  `options.framerateLimit.max`. FPS >260 observed confirms it is not a cap.
- **Allocation rate identical** (~205 vs ~207 MB/s) → the memory difference is
  GC policy, not a leak.
- **`sync_mods_to_game` hard-links** (`mods.py`), zero-copy, wipes+relinks each
  launch — not a per-launch I/O cost.
- **`-Dorg.lwjgl.util.NoChecks`** — still present in
  `org/lwjgl/system/Configuration.class` (LWJGL 3.3.3, the version 1.21.11 uses),
  so it is still read. Not dead (an initial suspicion, disproven).
- **`chunk_builder_threads:2`** identical on both (both arguably low for a
  12-thread CPU, but equal → not the gap).
- **Java 21.0.7 vs 21.0.12** — Cubeon uses mll's managed
  `runtime/java-runtime-delta` (21.0.7); FastClient uses PATH (21.0.12). Same
  major → negligible.

---

## F. Suggested fix order (for the code owner — not applied here)
1. **B2/B1** (GC): drop `-Xms=-Xmx` and lower `G1NewSizePercent` (~5-10) for
   clients; re-evaluate `AlwaysPreTouch`. This directly addresses the user's
   memory observation and GC smoothness.
2. **A1/A2/A5**: fix `particles` → `2`, replace `graphicsMode` with
   `graphicsPreset:"fast"`, and fix **A3** (`_set_options` quoting/idempotency)
   — update `tools/test_perf_mods.py` in the same commit.
3. **C3**: decide who owns Sodium's entity-culling/fog-occlusion toggles and set
   them ON.
4. **C1**: measure with Wurst + XaeroWorldMap disabled to size their cost.
5. **B4**: cap the default heap (e.g. 4-6 GB) instead of half of RAM.

## G. Reproduce the evidence
```bash
# particle enum + graphics key (jar)
cd /tmp && unzip -o ~/.cubeon_minecraft/versions/1.21.11/1.21.11.jar 'awx.class' 'gfo.class' 'bph.class' 'gfb.class'
javap -p -c awx.class | sed -n '/static {};/,$p'      # ALL=0, DECREASED=1, MINIMAL=2
javap -p -c gfo.class | grep -iE 'graphicsPreset|graphicsMode|maxFps'   # graphicsPreset is the live key
# launch args
sed -n '587p;336,366p;369,381p' cubeon/launch.py
grep -oE '\-X[a-zA-Z:]+[0-9]+[MGk]?' ~/.local/share/FastClient/logs/fastclient.log | sort -u
# config parity
diff <(sort ~/.fastclient/profiles/1.21.11-Fabric/options.txt) <(sort ~/.cubeon_minecraft/options.txt)
diff <(cat ~/.fastclient/profiles/1.21.11-Fabric/config/sodium-options.json) <(cat ~/.cubeon_minecraft/config/sodium-options.json)
```

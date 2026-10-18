# FPS benchmark: 2026-10-15 (Cubeon vs SKLauncher vs FastClient)

What the website's [benchmarks page](../../web/benchmarks.html) publishes, where
the numbers came from, and what weakens them. The evidence is
`benchmarks/Minecraft_FPS_Report-1.pdf` (8 pages, written 2026-10-15); the site
serves the same file verbatim as `web/assets/Minecraft-FPS-Report.pdf`.

## Setup

- Minecraft 1.21.11, one PC: Xeon E5-1650, Radeon RX 580.
- Three separate one-minute runs per launcher. FPS was counted **frame by frame
  from screen recordings**, one sample per second of video, not read from any
  launcher's own counter.
- "In game" ≈ 28–32 s of actual gameplay per launcher; "menu" is the pause screen.
- All three were launched as-is. Nothing was added or changed by hand. SKLauncher
  ran with **no Sodium and no mods at all** (plain vanilla), so it is being
  compared against launchers that ship Sodium.

## Results (second recording), FPS

| Launcher | In-game mean | Median | 5th pct (lows) | Min | Max | Menu mean | Whole video |
|----------|-------------:|-------:|---------------:|----:|----:|----------:|------------:|
| Cubeon | 206 | 217 | 148 | 102 | 271 | 256 | 233 |
| SKLauncher | 119 | 123 | 70 | 33 | 165 | 147 | 133 |
| FastClient | 152 | 156 | 105 | 37 | 211 | 166 | 160 |

## Findings

- Cubeon was fastest in game: about 35% above FastClient (152) and 74% above
  SKLauncher (119).
- Cubeon had the best worst case too, its lowest in-game second was 102 FPS,
  against 37 (FastClient) and 33 (SKLauncher).
- FastClient held up best between menu and game (about an 8% drop; Cubeon and
  SKLauncher each lost about 19%).
- SKLauncher looked frame-capped on the pause menu at about 147 FPS, and was
  slowest in game with the deepest dips.

## What weakens the comparison (published on purpose)

- **Not a lab test.** Each launcher was recorded in a different spot in the
  world. The same world, camera path and several runs each would be stronger.
- **F3 was on for Cubeon and SKLauncher, off for FastClient** (it uses its own
  FPS display). The debug screen costs a little FPS, so this slightly favours
  FastClient, and the gap is still large.
- **Nothing was equalised.** SKLauncher ran vanilla with no Sodium, and its own
  defaults differed (fancy clouds, RGSS filtering, where Cubeon was on fast
  clouds with no filtering). Its numbers say "a vanilla install on this PC",
  not "this launcher's best".
- **FastClient's digits are blurry in the video.** A few of its menu readings
  may be off by about 5 FPS. Every reading was checked by eye, twice.

## Why Cubeon's numbers look like this

Cubeon's **FPS boost** is on by default (`cubeon/perf_mods.py`): it installs
Sodium plus Lithium, ImmediatelyFast, Entity Culling, FerriteCore and More
Culling into the profile being launched, and writes the graphics options that
cost frames to their fast values. Turning the switch off restores vanilla
graphics on the next launch. A big part of the SKLauncher gap is therefore the
mods Cubeon installs for you, not the launcher's own code, which is exactly
what the caveat above says.

# 2026-10-18 — Ylet is now a company folder, and Cubeon is branded as its product

Agent: opencode · session started in `Products/Cubeon`, ended in `products/cubeon`.

## What was asked

The owner has three products now (Cubeon, Icono, Spruce) and the folder that
holds them had grown without a plan. The ask, verbatim in spirit: *map the
projects correctly, init their git repos, give them a better file structure,
remove stale things, add new links to Ylet, write docs, mark Cubeon as a Ylet
product, and draft the legal pack — signatures come later.*

## What I did

**1. Mapped first, then asked.** Wrote `~/Ylet_Productions/docs/PROJECTS.md`
from the files themselves, then asked five questions rather than guessing.
Answers: Cubeon + Icono + Spruce are the products (the launch video is
marketing); Cubeon's repo stays put and the rest move to `ylet-co`; the proposed
tree was approved; **Ylet is not a registered entity yet**; "forum" meant *legal
forms/documents*.

**2. Restructured (nothing deleted).**

    Ylem_brand/            -> brand/
    ylet/                  -> site/
    Products/Icono         -> products/icono
    Products/spruce        -> products/spruce
    Products/cubeon        -> products/cubeon        (see the trap below)
    Products/cubeon-launch-video -> products/launch-video
    Products/.scripts      -> tools/spruce-catalog
    Products/              -> gone

The three folders that had **no version control at all** now have repos:
`brand/`, `products/launch-video/`, `tools/spruce-catalog/`. `products/spruce/`
also got the `.gitignore` it never had.

**3. Cross-linked.** The company site's Products section was built for more
than one row (they were numbered `01`) but only had Cubeon, labelled "Our first
app". It now has three rows. Icono and Spruce are marked **"In development" and
are deliberately not links** — neither has a domain yet (Spruce's HTML still
says `https://YOUR-DOMAIN`), so linking them would ship two 404s from the
company site. Cubeon's own site now says "A Ylet product" on all 15 pages.

**4. Legal pack** in `legal/`: a dated operator notice ("Cubeon is now operated
by Ylet"), plus `TERMS.md`, `PRIVACY.md`, `TRADEMARK.md`, and `signatures/`.
Every blank only the owner can fill is marked `[[FILL: …]]` and listed in one
place. They are drafts and say so — I am not a lawyer and the pack says that in
its first paragraph.

**5. Docs.** Root `README.md`, `docs/PROJECTS.md` (the map), `docs/BRAND.md`,
`docs/OPERATIONS.md`, `brand/README.md`, `tools/spruce-catalog/README.md`.

## The trap I nearly walked into

Moving the repo I was *sitting in*. `mv Products/Cubeon products/cubeon` kills
the harness's default working directory, and every subsequent shell command
fails to start. The fix is `tools.opencode.session_move({directory})` — call it
immediately after the `mv`. I checked first that nothing else depended on the
old path (the `.desktop` file launches an installed AppImage from
`~/.local/opt/Cubeon`; no repo self-references `Products/`), so the only
collateral is a stale VS Code workspace path.

## Live-site changes, and what I deliberately did *not* change

Changed and shipped as commits, locally:

| Repo | Commit | What |
|---|---|---|
| `site` | `5a95711` | 3 product rows; `ylem-theme` → `ylet-theme` in 11 files |
| `products/cubeon` | `9e0d030` | "A Ylet product" on 15 pages; privacy operator paragraph |
| `products/spruce` | `b3d8f7a8` | `.gitignore` (the repo had none) |
| `brand`, `products/launch-video`, `tools/spruce-catalog` | new | first commits |

**Not changed, on purpose:**

- The pages' **"Policies last updated"** dates. The wording moved; the date
  should move with the *signed* version. Bumping it now would date a legal text
  that nobody has signed.
- `site/site.webmanifest` — the owner's uncommitted work, and it is **wrong**:
  the *company* site's manifest now declares itself `"name": "Spruce"`. Left
  alone because it is their edit, flagged in `docs/PROJECTS.md` §2.
- The formal legal documents: authored, unsigned, unpublished.

## Something odd, for the record

`products/cubeon/web/assets/cubeon-play.png` is locally **modified** and was
*before* any of my edits: on disk it is 1871×1166 / 288 KB, while `HEAD` has
2720×1610 / 2.0 MB. Its mtime is 17 Oct, its ctime is 18 Oct 07:02. No code in
the repo writes that path (`tools/make_og_card.py` only *reads* it), so
something outside the repo replaced it — plausibly another agent or an image
optimizer. **Left uncommitted deliberately**; it is not mine to commit. Worth
asking the owner whether the downscaled hero is wanted.

## Prior baton, answered

The previous note's §5 asked whether to build an FPS preset from the Sodium
config. The owner answered: **don't ship it, and reset mine to Sodium defaults.**
Done — `~/.cubeon_minecraft/config/sodium-options.json`
`chunk_builder_threads` 2 → 0, all 16 graphics keys now equal the compiled
defaults (backup: `/tmp/opencode/sodium-options.json.before`). The
`module-map.md` rule "do NOT ship a `sodium-options.json` as the FPS boost
config" stands.

## Baton to the next agent

1. **Pushing is the owner's call and I have not pushed.** Every push to Cubeon's
   `main` mints a published release (`v*`, 6 artifacts) — a footer change would
   do that. `site`, `spruce` and the three new repos have no such side effect.
   The new repos also have **no remote yet**; creating GitHub repos under
   `ylet-co` needs the owner's say-so.
2. **Icono and Spruce need domains** before their rows on the company site can
   become links. Then: set the domain in Spruce's HTML (`sed` in
   `docs/OPERATIONS.md`), and un-mark them "In development".
3. **Do not move Cubeon's GitHub repo** before changing
   `cubeon/updater.py::DEFAULT_FEED` and shipping that. Installed clients poll
   that hardcoded path.
4. If Ylet is ever registered, `legal/README.md` has the one list of every
   `[[FILL: …]]`, and the notice has the order of operations.

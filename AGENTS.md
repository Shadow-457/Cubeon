# Repository instructions

## Before work
- **Read `agents/docs/module-map.md` FIRST when present.** It is the local index: what
  every module does, where the entry points are, the invariants you must not
  break, and how to run the tests.
- On a fresh checkout, use `docs/architecture/overview.md` and
  `docs/development/testing.md`; local `agents/` references are ignored by Git.
- Read the newest task note in `agents/` when present. Address any relevant open question
  in your own completion note.

## Reuse existing work (entire repository)
- Before adding code, assets, UI components, dependencies or tooling, search the
  repository for an existing implementation or resource that serves the purpose.
  Reuse or extend suitable existing work instead of creating duplicates.
- Use the existing branding, fonts, theme tokens, components and interaction
  patterns for the surface being changed. For launcher visuals, use the real
  `assets/cube.svg`, bundled fonts defined in `cubeon/theme.py`, and matching
  user-supplied icons from `assets/icons/` before choosing generic substitutes.
- Preserve supplied artwork and its colors, existing control identity, accessibility
  and behavior when integrating or extending it.
- Add something new only when existing work cannot reasonably meet the requirement
  or the user explicitly requests a replacement. Briefly record the reason in the
  completion note. This rule applies to every directory in the repository.

## After work
- Add ONE short Markdown note to `agents/` about what you actually did and how
  you verified it.
- Only write it AFTER the work is done, no "I plan to..." placeholders. A note
  about work that never happened misleads the next agent.
- **If you learned a durable fact** (an invariant, a path, a gotcha, a contract)
  that the next agent will need, add a line to `agents/docs/module-map.md`
  when present instead of leaving it only in the task note. Shared contracts belong
  in the relevant public guide under `docs/`.

See `agents/README.md` when present for the local reference layout and note format.

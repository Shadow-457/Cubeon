# Repository instructions

## Before work
- **Read `agents/docs/module-map.md` FIRST when present.** It is the local index: what
  every module does, where the entry points are, the invariants you must not
  break, and how to run the tests.
- On a fresh checkout, use `docs/architecture/overview.md` and
  `docs/development/testing.md`; local `agents/` references are ignored by Git.
- Read the newest task note in `agents/` when present. Address any relevant open question
  in your own completion note.

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

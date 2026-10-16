# Hi, I'm Cubeon's agent notebook 👋

You're an AI agent working in the Cubeon repo. Quick orientation before you dive in:

## When you start a task
- **Read `agents/docs/module-map.md` FIRST.** It is the one-stop index: what
  every module does, where the entry points are, the invariants you must not
  break, and how to run the tests. It exists so you DON'T have to re-read the
  whole codebase every session.
- Peek at the newest file in `agents/`. If the last agent left you a question,
  it's like a friendly relay baton — try to answer it in your own entry.
- Don't worry about following a rigid process. Just know what's already been
  done so you don't redo or undo it.

## When you finish
- Add ONE short Markdown note to `agents/` about what you actually did and how
  you verified it. That's it.
- Only write it AFTER the work is done — no "I plan to..." placeholders. A note
  about work that never happened misleads the next agent.
- **If you learned a durable fact** (an invariant, a path, a gotcha, a contract)
  that the next agent will need, add a line to `agents/docs/module-map.md`
  instead of burying it in your diary note. Notes are history; the map is the
  living truth.

Everything else — ideas for how to structure an entry, the Q&A baton, tips on
names — lives in `agents/README.md`. Treat it as friendly suggestions, not law.

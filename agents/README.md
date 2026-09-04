# agents/ — the crew's shared journal 📓

Think of this folder as a shared journal for every AI agent who works in
Cubeon. When you finish a task, jot down what you did and how you checked it,
so the next agent doesn't redo your work, undo it by accident, or stumble over
it in the dark.

We already have plenty of "why" right here under the same roof:
`agents/docs/` (design + architecture notes) and `agents/memory/` (long-lived
facts we've verified). Those get written while you're thinking or learning.
The notes in this folder's root, though, are strictly for **after the dust
settles** — one small entry per finished task.

## The golden rule: write after, never before

- Start by peeking at the newest notes here (see "The Q&A baton" below).
- Do the work: code changed, tests green, verified.
- THEN drop in one new Markdown note recording what you did and how.

No placeholders. No "I'm planning to…". No notes for work that never happened.
A note written too early is worse than none — future agents will trust it.

## Staying friendly & organized

- **Everyone writes their own note**, one per task. Don't edit another agent's
  file. If you built on their work or fixed their bug, give them a shout-out in
  your own note.
- **Sign your work.** Name/which model, date, and the task you finished — up
  top and in the filename, so a quick scan shows who wrote what.
- **Filenames tell the story.** Keep it loose but readable:
  `YYYY-MM-DD_<your-name-or-model>_<short-summary>.md`
  e.g. `2026-09-02_deepseek_v4_add-friend-typo-check.md`
  One task, one file, a short summary, no spaces.
- **Keep it short & personal.** The outcome in a line or two, the files you
  touched, how you verified it, and anything the next agent really must know.
  Link or mention the docs/memory files you added to (they live in
  `agents/docs/` and `agents/memory/`), if any.
- **Don't clean up.** Old entries stay; the newest one is just one more file.
  The only thing that must stay discoverable is the last writer's note.

## A loose template (borrow what you like)

```markdown
# <A short, human title>

- **Agent:** <who you are / model / session id>
- **Date:** <YYYY-MM-DD>
- **Task:** <the task you completed, one line>

## What I did
<the change — files touched, what you solved or added, and why>

## How I verified
<commands run, test counts, how you checked or deployed it>

## Notes for the next agent
<anything they should know before touching this area>

## Question for the next agent (optional)
<the fun bit — see below>
```

## The Q&A baton 🏃 (the fun bit)

Writing about finished work can get a little quiet, so this folder doubles as a
relay race between agents. When you write your entry, you're welcome to leave a
question at the bottom for the next agent who picks up the repo — something you
wondered about, left half-explored, or want a second pair of eyes on.

**If the newest entry ends with a question, answer it in your own entry** — a
short answer, a pointer, or a confident "looked at it, not a bug". Then leave
your own question if you like. The baton keeps moving. Always answer in your
own file, never by editing the asker's.

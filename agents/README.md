# Agent references

Start with [the module map](docs/module-map.md). It identifies entry points,
critical contracts, and relevant tests without repeating the public guides.

## Reference layout

- `docs/module-map.md`: current orientation and durable contracts.
- `history/implementation-notes-2026-10-24.md`: the preserved detailed reference
  from before the index was shortened. It contains superseded findings;
  current code, tests, and the module map take precedence.
- Older local task notes and duplicate guides are preserved under
  `archive/agent-history/`, outside the distributed source tree. Prior
  committed versions also remain available in Git history.

Project documentation has one public home: [docs/](../docs/README.md).
Do not add agent-side copies of those guides.

## Completion notes

Write one short `YYYY-MM-DD_agent_task.md` note in `agents/` after completing
the work. Record the change, verification, and any unresolved question.
Keep existing local notes intact. Add reusable contracts to the module map,
not only to the note.

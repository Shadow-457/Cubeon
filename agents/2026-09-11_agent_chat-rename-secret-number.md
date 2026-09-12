# 2026-09-11 - Chat rename: chosen name + secret-derived number

## Ask
"add a area to rename the cubeon name the one for chat but using the secret key
add a number with that name so it becomes unique"

## Reading
The auto handle (`Player_<8hex>`) had no way to change, and a bare chosen name
can collide (and on the server the loser just gets "already taken"). The user
wants a rename area in the Chat tab where a chosen display name gets a number
derived from the machine's secret appended, so it is unique without hand-checking
availability.

## What changed
- **`cubeon/friends.py`**
  - `AUTO_NAME_DIGITS = 4`.
  - `unique_number(attempt=0)` = last 4 decimal digits of `sha256(stable_secret())`
    (plus `attempt`, mod 10k). Deterministic per auth_key.json.
  - `unique_name(base, attempt=0)` -> `base + unique_number(...)`. Strips
    non-`[A-Za-z0-9_]` and trailing digits from the base first, so re-applying a
    generated handle is idempotent ("Dragon4821" -> "Dragon4821", not
    "...48214821") and a reserved base ("admin") is freed by the suffix.
    Truncated to 16 chars. Empty base falls back to "Player".
  - `name_base(name)` -> the editable stem (current handle minus the trailing
    digits) for prefilling the rename field.
- **`cubeon/friends_service.py`** - split `rename()` into the claim + a new
  `_finish_rename(name, was)` (persist cfg, reconnect presence, republish E2EE
  key, notify, `_changed`), and added `rename_unique(base)`: walks
  `friends.unique_name(base, attempt)` for `attempt` 0..7, retrying only while
  the relay says `name_taken`; any other error stops at once with claim's own
  sentence.
- **`ui/chat_tab.py`** - added a "Your name" area (field + save) that calls
  `service.rename_unique(base)` and reports the final name; prefills the field
  from `friends.name_base(current)` when empty. Also routed all network service
  calls (`send_chat`, `add_friend`, accept/decline, remove, rename) through a new
  `_run()` daemon-thread helper - Flet click handlers run on the UI thread and
  `send_chat`/`claim` do blocking I/O (this was a latent freeze in the tab).
- Docs: module-map.md (Chat-tab bullet + test counts), guide-ui-modules.md
  (Chat layout + rename/threading notes).

## Verification
- `test_friends_service` 212/212 (+12): new `test_unique_rename` pins
  determinism, valid/suffixed output, attempt walk, idempotence, reserved-base
  safety, `name_base`, collision retry, base preservation, persistence, and
  stop-on-real-error.
- `test_ui_smoke` 97/97 (+1): the Chat tab has a rename area wired to
  `rename_unique`/`name_base`.
- `py_compile` clean on the three edited modules.

## Note for next agent
The number is 4 digits, so two *different* secrets sharing both the same base and
the same number collide ~1/10000. `rename_unique` resolves that by walking the
number, but the walk is per-machine and not re-derived from the peer's secret -
if the first candidate is taken by a different machine, we simply try the next.

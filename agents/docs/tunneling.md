# Tunneling - what's built, what's blocked, and what to run

The pitch is *"click host, send a link, they're in, in 30 seconds."* This is the
"send a link" half.

## Status

| Piece | State |
|---|---|
| Invite codes (`CUBE-7F4K-9QMN`) - format, storage, network client | **done**, `cubeon/invites.py` |
| Invite Worker (claim / resolve / unpublish) | **done**, not deployed, `worker/cubeon-invites.js` |
| playit download - platform detection, asset resolution, verification | **done**, `cubeon/playit.py`, verified against the real v1.0.10 asset list |
| Downloading **both** programs (daemon + control client) | **done**, `install()` - see "Two programs, not one" below |
| Telling the two programs apart at runtime | **done**, `accepts_subcommands()` probe |
| Running playitd without root, as Cubeon's own child process | **done**, `daemon_start()`, verified by a real run |
| Reading daemon state (`status`) | **done**, parsed from verbatim captured output |
| Headless claim flow | **built**, `claim()` - argument shapes still unseen, so degradation is explicit |
| Reading the public tunnel address | **built with fallback** - `_find_address()`, plus an "Open playit.gg" button when it can't be read |
| Configuring which local port is tunnelled | **blocked**, may be dashboard-only |
| Host / Join UI - Host half | **done**, `tunnel_tab.py`, mounted in the Server tab |
| Host / Join UI - Join half (enter someone's code) | not built; `invites.resolve()` exists, unwired |
| Tying tunnel start/stop to `cubeon/server.py` | not wired - Host starts a tunnel, not a server |

## Why the blocked parts aren't written on spec

This project already paid for building on an assumed file format once: the
launch-argument sanitizer assumed every entry had a `"value"` key, TLauncher
writes `"values"`, and the sanitizer deleted the whole argument block on two real
modpacks. Permanently, because the deleted data was the only copy.

A parser written against guessed CLI output is the same bet. The rule for this
feature: **no parsing code until someone pastes real output.** Everything below
marked *verified* was captured from a real run on the owner's machine.

---

## Verified: the release assets (v1.0.10, captured from the releases API 2026-08-22)

All 32 entries are in `tools/test_playit.py` verbatim, and the tests run against
them. Capturing the list killed three assumptions, each a live bug:

| Assumed | Actually |
|---|---|
| macOS builds exist (Apple Silicon + Intel) | **No macOS asset at all.** Linux + Windows only. |
| `playit-cli-*` covers every platform | **Linux only** - `amd64`, `aarch64`, `armv7`, `i686`. No Windows CLI. |
| Windows ships one `.exe` per arch | Also ships **`-signed`** variants of both `.exe` and `.msi`. |

Confirmed as expected: standalone binaries need no installer; `.deb`/`.rpm`/
`.apk` (including an `openrc` family) and `.msi` packages are published and must
**not** be picked up. Note `playit_*` packages carry no OS word at all
(`playit_amd64.deb`), so they're filtered by suffix rather than platform.

`cubeon/playit.py` resolves the asset **at runtime from the GitHub releases API**
rather than hardcoding a URL. Asset names are not a stable API, and a rename
would otherwise ship as "Host is broken" for every user simultaneously with no
fix short of a Cubeon update.

Windows prefers the **`-signed`** build: an unsigned `.exe` trips SmartScreen's
"Windows protected your PC" dialog, which for a launcher shared through YouTube
tutorials reads as a virus warning.

---

## Verified: the CLI surface

`playit-cli --help`, then `--help` on each subcommand, run on the owner's
machine. **This is a daemon plus a control client, not a TUI to scrape.**

```
Commands:
  version      Print version information
  attach       Attach to a running playitd service
  start        Start the installed playitd service
  stop         Stop the installed playitd service
  status       Show the status of the installed playitd service
  reset        Removes the secret key on your system so the playit agent can be re-claimed
  secret-path  Shows the file path where the playit secret can be found
  setup        Setup playit by provisioning a new secret to playitd
  account      Account management commands
  claim        Setting up a new playit agent
Options:
  -s, --stdout                     Prints logs to stdout
      --socket-path <SOCKET_PATH>  Override the IPC socket or named pipe used to reach playitd
      --systemd
      --openrc
```

### ✅ No root needed - playit documents the self-managed path itself

`playit-cli start` without `--systemd`/`--openrc` fails, but its error message is
the answer:

```
`playit start` can only start the installed service when run with --systemd or --openrc.

If you are managing playitd yourself, start it in the background and connect with --socket-path:
  playitd --socket-path=./playit.sock --secret-path=./playit.toml
  playit --socket-path=./playit.sock
```

So the design is: **Cubeon runs playitd as its own child process**, with
`--socket-path` and `--secret-path` pointing inside `~/.cubeon_launcher/`. No
system service, no root, no systemd unit.

That also buys isolation worth having. This machine already has a claim at
`~/.config/playit_gg/playit.toml` dated months earlier - a user who already uses
playit must not have their setup disturbed by a game launcher, and pointing
`--secret-path` at Cubeon's own directory guarantees that in both directions.

### ⚠️ `status` exit codes are a trap

```
$ playit-cli status;      → "The playit service is not running."   exit 0
$ playit-cli secret-path; → "Could not connect to the playit service."   exit 1
```

**`status` exits 0 when the service is not running.** Treating exit 0 as "up"
would report a working tunnel to a user with no tunnel - they'd send friends a
link to nothing. So health has to come from parsing the output, not the exit
code, and `status` needs a real fixture before `address()` is written.

`secret-path` also turned out to need a *running* service - it is not a static
path lookup, so it can't be used to answer "has this user claimed yet?" while
playitd is down.

### ✅ `claim` is a real headless API - no log scraping at all

```
claim generate  Generates a random claim code
claim url       Print a claim URL given the code and options
claim exchange  Exchanges the claim for the secret key
```

This is the whole browser flow, decomposed into commands that each return a
value. Cubeon can generate a code, build the URL, open it with
`webbrowser.open()`, and wait on `exchange` - never parsing a log stream and
never guessing whether a line will appear.

`account login-url` similarly generates a login link, so even account creation
can be launched from Cubeon's own UI.

`attach -s/--stdout` says *"Print logs to stdout instead of using TUI"* -
confirming the plain agent is a TUI, and giving a scrapeable fallback if `status`
turns out not to carry the address.

---

## Two programs, not one (verified 2026-08-22 by running both)

**The plain `playit-<os>-<arch>` agent IS the daemon.**
`./playit-linux-amd64 --socket-path=./playit.sock --secret-path=./playit.toml`
started a working playitd with no root and no installer.

But the agent is *only* the daemon. Handing it a subcommand is rejected outright:

```
$ ./playit-linux-amd64 claim generate
error: unexpected argument 'claim' found
exit=2
```

Its entire option list is `--secret`, `--secret-path`, `--socket-path`,
`-l/--log-path`, `--platform-docker`, `--version-overrides`. No subcommands at
all. Meanwhile `playit-cli-*` owns every subcommand - `claim`, `status`, `setup`,
`account` - and is Linux-only.

So the two halves of the feature live in **two different files**:

| Program | Job | Has `claim`/`status`? |
|---|---|---|
| `playit-linux-amd64` | the daemon (`playitd`) | **no** - exit code 2 |
| `playit-cli-linux-amd64` | the control client | yes |

### Consequence ①: `install()` downloads both

Downloading one is not enough, and *which* one you pick decides which half of the
feature is broken. `PREFER_CLI = False` (correct - a launcher with only the CLI
has a control client and nothing to control) meant a fresh Linux install got the
agent alone, so **every "Connect to playit.gg" click would have failed on a fresh
Linux install** with `error: unexpected argument 'claim' found`. Caught before
release only because the binaries were run instead of trusted.

`install()` now fetches both from a **single** releases-API call - GitHub's
unauthenticated API is rate-limited per IP, and two calls per install doubles the
chance of a 403 for a user on a shared/CGNAT connection. A missing or 404'd CLI
asset still installs the agent and honestly reports `cli_path is None`.

### Consequence ②: which-is-which is *probed*, not inferred from the filename

Windows publishes **one `.exe` and no CLI build**, and nobody has run it. Whether
that single file carries the subcommands is genuinely unknown. Guessing from the
filename would either break every Windows claim silently or break every Linux
one, so `accepts_subcommands(path)` asks the binary:

```python
proc = subprocess.run([path, "--help"], ...)
ok = "Commands:" in text and "claim" in text
```

`--help` is used rather than a real subcommand because it's the one invocation
that touches no network, no socket and no config. Both markers are required -
`Commands:` alone would match some future help layout that lists something else.
The result is cached per path (cleared when that path is re-downloaded), and a
failed *launch* is deliberately left uncached so an antivirus holding a lock for
a second doesn't permanently mark a good binary as broken.

`control_binary()` returns the first probed-yes binary or `None`;
`agent_binary()` returns a probed-no binary, falling back to whatever is
installed. If no control program exists, Cubeon says so in one sentence -
*"Cubeon doesn't have a working playit control program yet… check that antivirus
isn't removing it"* - instead of failing every claim with a stack trace.

So on Windows, **if** the `.exe` carries subcommands everything works with no
change; if it doesn't, the user gets a readable message. Either way nothing is
built on an assumption.

---

## The open design question: which binary is `playitd`?

**Answered 2026-08-22 by running it: the plain `playit-<os>-<arch>` agent IS the
daemon.** See "Two programs, not one" above for the full finding - including that
the agent rejects *all* subcommands, which is what forced `install()` to fetch
both programs.

Consequence: **`PREFER_CLI` flipped to `False`** for the *daemon* slot. A test
locks that default in.

### Verified: a self-managed daemon, running

```
playitd daemon status for socket ./playit.sock:
  Phase: waiting for secret
  PID: 48375
  Uptime: 5 seconds
  Version: 1.0.10
  Socket: ./playit.sock
  Secret path: ./playit.toml
  Secret configured: false
  IPC version: 2
  Capabilities: ["structured_responses", "stream_events", "lifecycle_state", "rich_status", "secret_provisioning"]
```

Both this and the not-running line are in `tools/test_playit.py` verbatim, and
`_parse_status()` is tested against them. Notes that shaped the code:

- **Structured `Key: value` output**, so parsing is generic rather than
  field-by-field. New releases add fields; a parser that only knows today's keys
  throws away tomorrow's - and `Tunnel address` may well be one of tomorrow's.
- **`Secret configured: false`** gives a direct answer to "has this user
  claimed?", which `secret-path` couldn't (it needs a running service). Anything
  not clearly true is treated as *not* configured: re-claiming is a recoverable
  annoyance, while assuming a secret exists produces a tunnel that never comes up.
- **`Capabilities` advertises `secret_provisioning` and `rich_status`.** The
  first says the secret can be handed over IPC rather than written to a file. The
  second is the encouraging signal for the address question - a claimed daemon
  plausibly has much more to say than `Phase: waiting for secret`.
- **`Another instance is already running`** (seen on the second spawn) means the
  socket is a singleton. `daemon_start()` therefore checks `status()` first and
  returns the existing daemon rather than erroring - clicking Host twice must not
  produce a dialog.

### What's built on top of that

`cubeon/playit.py` now has `install()` (both programs), `accepts_subcommands()`,
`control_binary()`, `agent_binary()`, `daemon_start()`, `status()`, a `Status`
class, `_parse_status()`, the `claim()` flow, `address()` and
`tunnel_up()`/`tunnel_down()`. The daemon is spawned with
`start_new_session=True` so a Ctrl-C in Cubeon's terminal doesn't kill the
tunnel, logs to `~/.cubeon_launcher/playitd.log`, and is polled rather than
slept-on until it answers.

Socket and secret live at `~/.cubeon_launcher/playit.{sock,toml}` -
deliberately **not** playit's default `~/.config/playit_gg/playit.toml`. This
machine already had a claim there from March; a game launcher must not disturb an
existing playit setup, and the isolation works both ways.

---

## Unverified - do not code against these

1. Whether **anything exposes the public address locally**. The only status seen
   so far was `Phase: waiting for secret`, which naturally carries no tunnel
   info. `_find_address()` is written and tested against plausible shapes, and
   when it finds nothing the UI says "Tunnel running" and shows an **Open
   playit.gg** button rather than claiming failure.
2. **Argument shapes and output of `claim generate` / `url` / `exchange`**, and
   whether `exchange` blocks until browser approval or needs polling.
3. **How the local port is configured.** Checked exhaustively on 2026-08-22 -
   the agent's whole option list and every CLI subcommand's `--help`. **Nothing
   sets it.** Very likely dashboard-only, which is a real hole in the "30
   seconds" claim and the biggest remaining unknown.
4. **Whether the Windows `.exe` accepts subcommands.** Nobody has run it. Handled
   by probe, not assumption - see "Two programs, not one".
5. Free-tier ceilings: concurrent tunnels, bandwidth, idle reclamation.

**Retired by the runs so far:** whether root is needed (no); which binary is the
daemon (the plain agent); **whether one binary does both jobs (no - the agent
rejects every subcommand with exit code 2)**; whether the claim URL must be
scraped from logs (no); the `playit.toml` format (Cubeon points `--secret-path`
at its own file and never parses it); whether `status` output is machine-readable
(it is).

---

## What to run next

Both of these are safe and exit on their own.

### ① The claim API's real shapes

`generate` makes a random code locally and `url` only prints a string - neither
needs a service or changes anything on the account:

```bash
for c in generate url exchange; do echo "===== claim $c ====="; ~/playit-test/playit-cli claim $c --help 2>&1; done
```

```bash
~/playit-test/playit-cli claim generate; echo "exit=$?"
```

Then build a URL from that code with whatever syntax `claim url --help` showed,
and paste the command you used plus its output.

### ② A claimed daemon's status - the last blocking question

Visit the claim URL in a browser to approve it, then with the daemon running:

```bash
cd ~/playit-test && (./playit-linux-amd64 --socket-path=./playit.sock --secret-path=./playit.toml >/tmp/playitd.log 2>&1 &) ; sleep 6; ~/playit-test/playit-cli --socket-path=./playit.sock status 2>&1; echo "=== log ==="; tail -30 /tmp/playitd.log
```

**Does a public address appear** (`something.gl.joinmc.link:41234` or similar),
in either the status block or the log? Don't read it off the dashboard - whether
the launcher can learn it *without* one is the entire question.

Cleanup when done:

```bash
pkill -f 'playit-linux-amd64 --socket-path' ; rm -f ~/playit-test/playit.sock
```

### ③ Free-tier limits

From playit's current account/tier docs, not from memory - these change.

---

## What's left

1. ~~`daemon_start()`~~ - **done**, verified.
2. ~~`claim()`~~ - **done**: `claim generate` → `claim url` → `webbrowser.open()`
   → `claim exchange`. Argument shapes still unverified, so failures surface as
   readable messages.
3. ~~`address()`~~ - **done with an honest fallback** (Open playit.gg button).
4. ~~Host UI~~ - **done**, `tunnel_tab.py` in the Server tab.
5. **Deploy `worker/cubeon-invites.js`.** Until then `invites.publish_new()`
   fails and the UI shows the raw playit address instead of a `CUBE-` code -
   which works, just uglier.
6. **The Join half.** No UI yet for a friend to type a `CUBE-xxxx-xxxx` code.
   `invites.resolve()` is built and tested but unwired.
7. **The local port.** Nothing configures it from the CLI (see Unverified #3), so
   the tunnel currently points wherever the dashboard says.
8. **Wire tunnel start/stop to `cubeon/server.py`'s lifecycle**, with playitd
   owned and reaped alongside the server.
9. `invites.publish_new(...)` on host, `invites.unpublish(...)` on stop - built
   and tested, called once the Worker is live.

**If the address turns out to be dashboard-only**, step 3's fallback is what
ships. Better options in order: playit's own API if one exists for reading tunnel
state; a fixed pre-created tunnel per install; or the `$5/mo VPS + frp` escape
hatch, which removes the browser signup entirely and gives a fixed port 25565.

`cubeon/invites.py` is deliberately provider-agnostic - the code maps to *an
address*, not to playit. That seam is what makes any of those fallbacks a
contained change instead of a rewrite.

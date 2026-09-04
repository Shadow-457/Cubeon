# Cubeon Phase 2b - Batch 2

Implemented on 2026-08-23.

## Features

### 1. Automatic P2P join launch

After the joiner has both:

- completed direct UDP hole punching, and
- finished the host mod/config synchronization,

Cubeon now starts Minecraft automatically with the local P2P relay as its
server target (`127.0.0.1:<relay-port>`). The user no longer needs to open
Multiplayer and manually type a Direct Connect address.

The existing normal launch path is unchanged because the new arguments are
optional parameters on `launch_game()`.

### 2. Explicit P2P launch state

The Friends UI now exposes a dedicated `Launching Minecraft into ...` state
between synchronization and the game process starting. This makes it clear
that the P2P connection succeeded and Cubeon is handing the connection to
Minecraft, rather than leaving the user on a generic `Connecting` message.

If the automatic launch fails, the P2P flow reports the error explicitly and
does not fall back to the dedicated-server/playit path.

## Validation

- Python syntax compilation: PASS
- P2P pure helper checks: PASS
- Direct-connect launch argument checks: PASS
- Existing dependency-heavy full test suite: not runnable in this environment
  because optional project dependencies such as Flet and
  `minecraft_launcher_lib` are not installed. The tests that were able to
  execute before dependency import failures reported passing checks.

# Switch Cubeon IDs to eight digits

- **Agent:** Codex
- **Date:** 2026-09-19
- **Task:** Change the public friend/account ID format from 12 digits to 8 digits.

## What I did

Updated launcher validation, formatting, UI copy, worker validation/serialization, and the Minecraft client bridge to use zero-padded 8-digit IDs. The worker also reissues legacy IDs above the new range when those rows are encountered.

## How I verified

Ran Python compilation, Node syntax checking, and direct 8-digit canonicalization/formatting assertions successfully.

# Contributing

## Bug Reports

Open an issue (or send a note to the contact in `SECURITY.md`/`README.md`)
describing: the command or route you ran, expected vs actual behavior, and
whether it touched a document project's schema (include the project name so
state can be reproduced).

## Feature Requests

Describe the workflow gap in terms of the existing command surface (CLI flag
or web route) it's missing from — Mode 1 (directory chunker) vs Mode 2
(document project management) — so it's clear which subsystem it belongs to.

## Noncommercial Contribution Terms

Contributions are accepted under the same PolyForm Noncommercial 1.0.0 terms
as the rest of the project. By contributing you agree your changes may be
distributed under that license.

## Code Conventions

Match the existing style: verbose self-describing names, `BASE_DIR`-relative
path resolution (never hardcoded absolute paths), `cmd_<verb>_<noun>` for
CLI-exposed commands and `_<verb>_<noun>` for internal helpers, and a full
file header (Library/Description/Version/Date/Author/Contact/RELATIONAL_ID)
on every new file. See `AGENTS.md` for the full convention list.

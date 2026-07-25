# AGENTS.md

## Build / Lint / Test / Run

No build step (pure Python, no compiled assets). No test suite is present in
this repo. Run directly:

```bash
python Doc_Chunker.py --doc-list          # CLI
python Doc_Chunker_Flask.py               # Web UI, http://localhost:5050
```

Dependency: `pip install flask` (only third-party package used).

## Code Style & Conventions

- Verbose, self-describing names throughout (`MOUNT_TTL_SECONDS`,
  `ACTIVE_DOC_FILE`, `PERSIST_DIR`) — no compressed identifiers.
- Every top-level path constant is resolved relative to `BASE_DIR =
  Path(__file__).resolve().parent` — never hardcoded absolute paths.
- CLI commands follow `cmd_<verb>_<noun>` naming; internal helpers follow
  `_<verb>_<noun>` (leading underscore = not a CLI-exposed command).
- Each file carries a header docstring with Library/Description/Version/
  Date/Author/Contact/RELATIONAL_ID and an inline changelog.
- Library files under `lib/` use the family-prefixed naming scheme
  `lib_bejson_<Family>_<name>.py` (e.g. `lib_bejson_Core_bejson_core.py`).
  Older flat-named library files (`lib_bejson_core.py`, `lib_mfdb_core.py`,
  etc.) are deprecated under this convention — see docs/cleanup-log.md for
  what was removed as unreachable dead weight from a prior naming migration.

## Architectural Rules

- `Doc_Chunker_Flask.py` never duplicates logic — it imports `Doc_Chunker`
  as a module and calls its functions directly (`import Doc_Chunker as DC`),
  so CLI and web share one source of truth for state (active document, mount
  status).
- Document schemas are stored as BEJSON `104db` files under
  `Document_Project/<name>/Schema/`. These are databases, not disposable
  data — never delete or hand-edit them outside the tool's own commands.
- Mount state (`data/persist/mounted.json`) has a TTL
  (`MOUNT_TTL_SECONDS = 3600`) checked at startup; stale mounts are cleared
  automatically rather than left dangling.
- `--doc-archive-delete` is the only sanctioned way to remove a document
  project — it zips to `Document_Project_Archive/` first, so deletion is
  never destructive.

## Directory Map

| Path | Contents |
|---|---|
| `Doc_Chunker.py` | CLI entry point, all `cmd_*` commands, argparse wiring |
| `Doc_Chunker_Flask.py` | Flask routes, imports `Doc_Chunker` directly |
| `lib/` | BEJSON core/env/errors/validator/utility support libraries |
| `data/` | Runtime state: active document pointer, mount tracking |
| `Document_Project/` | Live document schemas + compiled Markdown output |
| `Document_Project_Archive/` | Zipped archives of retired document projects |
| `templates/`, `static/` | Flask UI (Jinja2 templates, CSS/JS) |
| `docs/` | Project documentation |

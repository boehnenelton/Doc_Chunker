# Architecture

## Components

**Doc_Chunker.py (CLI core)**
The single source of truth. Owns all state paths (`BASE_DIR`-relative),
all `cmd_*` command implementations, and the argparse CLI wiring. Two
largely independent feature sets live in this one file:

1. **Directory chunker** — takes an arbitrary directory, walks it, and
   packs contents + metadata into a portable BEJSON `104db` file
   (`--chunk`/`--unchunk`), with a project registry (`project_registry`)
   tracking chunk history and version numbers per numeric project ID.
2. **Document project manager** — a separate, higher-level system for
   long-form hand-authored documents. Each document project has its own
   `104db` schema (categories + chunks + tags + status + ordering),
   supports a "mount" workflow (explode schema to individual text files
   for external editing, then commit or discard), and compiles to
   Markdown with an auto-generated table of contents.

**Doc_Chunker_Flask.py (web wrapper)**
A thin Flask layer with zero duplicated business logic. It does
`sys.path.insert(0, str(CHUNKER_DIR))` then `import Doc_Chunker as DC`,
and every route is a call into `DC.*` functions, translating results into
Jinja2 template context. State is shared with the CLI because both talk
to the same on-disk files — there is no separate web-only state.

**lib/ (BEJSON support libraries)**
Five modules survive as actually-imported dependencies of the entry
points: `lib_bejson_Core_bejson_core` (core BEJSON read/write),
`lib_bejson_Core_bejson_env` (path resolution — `resolve_path`),
`lib_bejson_Core_bejson_errors` (error types, imported inside a function
in the validator module), `lib_bejson_Core_bejson_validator`, and
`lib_bejson_Utility_bejson_utility`. Everything else previously in `lib/`
(older flat-named duplicates, an MFDB wrapper pair, a standalone parser,
a provider module, a state-management module, a static backend, and a
bejson_server helper) formed a self-referencing but entry-point-unreachable
cluster and was removed — see `docs/cleanup-log.md`.

## Data Flow

**Chunking a directory:**
`--chunk DIR` -> walk DIR -> build BEJSON 104db record set (via
`lib_bejson_Core_bejson_core`) -> validate (via
`lib_bejson_Core_bejson_validator`) -> write `.104db.bejson` -> register
project + version in the project registry.

**Document editing (CLI or web, same path):**
`--doc-sel IDX` sets `data/active_doc.txt` -> subsequent commands read
the active document's schema from
`Document_Project/<name>/Schema/<name>.104db.bejson` -> chunk-level
commands (`--doc-chunk-write`, `--doc-chunk-tag`, etc.) mutate that schema
in place -> `--doc-compile` reads the schema and renders
`Document_Project/<name>/Compiled/<name>.md` with a generated TOC.

**Mount workflow:**
`--doc-mount` explodes the active schema's chunks into individual files
under `Document_Project/<name>/Mounted/`, and records the mount in
`data/persist/mounted.json`. `--doc-commit` reads those files back and
writes the changes into the schema; `--doc-discard` throws the mounted
files away instead. On every startup, entries in `mounted.json` older
than `MOUNT_TTL_SECONDS` (3600s) are cleared automatically so a forgotten
mount session doesn't linger indefinitely.

**Archiving:**
`--doc-archive-delete` zips the full `Document_Project/<name>/` directory
into `Document_Project_Archive/`, then deletes it from `Document_Project/`
and clears the active-doc pointer and any mount-state entry referencing
it — so retiring a document is non-destructive (a zip survives) but the
live working tree stays clean.

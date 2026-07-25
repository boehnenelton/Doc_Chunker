# Usage Guide

Every flag below is real — pulled directly from the `argparse` definitions
in `Doc_Chunker.py`. Exactly one flag from the mutually-exclusive command
group is required per invocation; the shared options (`--dest`, `--label`,
`--content`, `--tags`, `--status`, `--tag`, `--delimiter`, `--category`) are
passed alongside whichever command needs them.

## Mode 1 — Directory Chunker (BEJSON 104db archival)

| Flag | Args | Description |
|---|---|---|
| `--chunk` | `DIR` | Chunk a directory into BEJSON 104db |
| `--chunk-index` | `ID` | Chunk a registered project by numeric ID |
| `--unchunk` | `FILE` | Unchunk a BEJSON 104db file (`--dest DIR` optional) |
| `--unchunk-index` | `ID` | Unchunk a historical chunk by numeric ID |
| `--list-chunk-index` | — | List all registered projects |
| `--list-project-index` | — | Alias for `--list-chunk-index` |
| `--list-unchunk-index` | — | List all historical chunks with numeric IDs |
| `--expell-project` | `ID` | Remove a project from registry (files kept) |
| `--delete-project` | `ID` | Remove a project and delete all chunk files |
| `--get-versions` | `ID` | List all versions for a project ID |
| `--delete-version` | `ID VER` | Delete a specific version for a project ID |

## Mode 2 — Document Project Management

**Project-level**

| Flag | Args | Description |
|---|---|---|
| `--doc-new` | `NAME` | Create a new document project |
| `--doc-list` | — | List all document projects |
| `--doc-sel` | `IDX` | Select active document project by index |
| `--doc-mount` | — | Mount active doc — explode schema to text files |
| `--doc-discard` | — | Discard mounted changes, restore schema state |
| `--doc-commit` | — | Commit mounted edits back into the schema |
| `--doc-compile` | — | Compile active doc -> Markdown with TOC |
| `--duplicate-doc` | `IDX NEWNAME` | Duplicate a doc project by index to a new name |
| `--rename-doc` | `IDX NEWNAME` | Rename a doc project by index |
| `--export-doc` | `IDX FORMAT` | Export doc by index (`md`, `txt`, `json`) |

**Category-level**

| Flag | Args | Description |
|---|---|---|
| `--doc-cat-list` | — | List categories in active doc |
| `--doc-cat-sel` | `IDX` | Print category name at index (for scripting) |
| `--doc-cat-add` | `NAME` | Add a new category to active doc |
| `--doc-cat-del` | `IDX` | Delete a category by index (must be empty) |
| `--doc-cat-inc-idx-pos` | `IDX` | Move category at IDX one position earlier |
| `--doc-cat-dec-idx-pos` | `IDX` | Move category at IDX one position later |

**Chunk-level**

| Flag | Args | Description |
|---|---|---|
| `--doc-chunk-list` | — | List all chunks in active doc, grouped by category |
| `--doc-chunk-sel` | `CHUNK_ID` | Print full content of chunk by ID |
| `--doc-chunk-add` | `CATEGORY` | Add a new chunk to a category (`--label` optional) |
| `--doc-chunk-write` | `CHUNK_ID` | Write content to a chunk (use `--content`) |
| `--doc-chunk-del` | `CHUNK_ID` | Delete a chunk by ID |
| `--doc-chunk-set-parent-cat` | `CHUNK_ID CATEGORY` | Move chunk to a different category |
| `--doc-chunk-inc-idx-pos` | `CHUNK_ID` | Move chunk one position up within its category |
| `--doc-chunk-dec-idx-pos` | `CHUNK_ID` | Move chunk one position down within its category |

**Search, tagging, status, compile, merge, import, lock, snapshot**

| Flag | Args | Description |
|---|---|---|
| `--doc-find` | `TEXT` | Search all chunks in active doc for text |
| `--doc-stats` | — | Print word count and stats for active doc |
| `--doc-chunk-tag` | `CHUNK_ID` | Set tags on a chunk (use `--tags`) |
| `--doc-chunk-set-status` | `CHUNK_ID` | Set chunk status: `draft\|review\|final\|skip` (use `--status`) |
| `--doc-compile-filtered` | — | Compile filtered chunks (use `--tag` and/or `--status`) |
| `--doc-merge` | `IDX_LIST OUTPUT_NAME` | Merge compiled docs (comma-separated IDX list) into one |
| `--doc-import-file` | `FILE` | Import text file as chunks (use `--delimiter`, `--category`) |
| `--doc-lock` | `[IDX]` | Lock doc by index, or active doc if omitted |
| `--doc-unlock` | `[IDX]` | Unlock doc by index, or active doc if omitted |
| `--doc-snapshot` | — | Snapshot active doc schema+compiled to zip |
| `--doc-restore-snapshot` | `FILE` | Restore a snapshot zip into active doc |

## Shared Options

| Flag | Used with | Description |
|---|---|---|
| `--dest DIR` | `--unchunk` | Custom destination directory |
| `--label LABEL` | `--doc-chunk-add` | Chunk label |
| `--content TEXT_OR_FILE` | `--doc-chunk-write` | Content text, or a path to a file to read content from |
| `--tags TAGS` | `--doc-chunk-tag` | Comma-separated tags |
| `--status STATUS` | `--doc-chunk-set-status`, `--doc-compile-filtered` | Chunk status value |
| `--tag TAG` | `--doc-compile-filtered` | Single tag to filter by |
| `--delimiter DELIM` | `--doc-import-file` | Delimiter to split on (e.g. `---` or `\n\n`) |
| `--category CATEGORY` | `--doc-import-file` | Target category for imported chunks |

## Web Routes (`Doc_Chunker_Flask.py`)

The Flask app exposes a route per major CLI action (dashboard, document
list, category view, chunk editor, compile, mount/mount-file-editor,
archive-delete, tools/find, tools/stats) rendered through the templates in
`templates/`. Every route calls the corresponding `DC.*` function from
`Doc_Chunker.py` directly — there is no parallel web-only implementation of
any command, so behavior (including the mount TTL cleanup and archive
safety) is identical between CLI and web use.

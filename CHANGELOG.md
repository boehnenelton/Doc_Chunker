# Changelog

## [Unreleased] — Repo Prepper audit pass
- Removed 17 verified-unimported library files from `lib/` (unreachable from
  both entry points via full import-chain analysis — see
  `docs/cleanup-log.md` for the complete list and verification method)
- Removed `__pycache__/` build artifacts (root and `lib/`)
- Flagged (kept, not deleted) `lib/__init__.py`, `.bejson_project.json`, and
  `doc chunker fixes.txt` for manual review — see `docs/cleanup-log.md` for
  why each was excluded from automatic removal
- Regenerated LICENSE, README.md, AGENTS.md, docs/architecture.md,
  docs/usage-guide.md, .gitignore, CONTRIBUTING.md, SECURITY.md

## v2.3.0 — pkg005 (2026-07-22)
- Spell/grammar-checked and rewrote 5 of 6 chunks in Chunked_Policy (Lead
  Developer, Purposeful Speech, Goal_Driven, High Standards, Low Confidence)
  for clarity and directness as LLM system instructions. Corrected garbled
  voice-transcription artifacts. Dropped one incomplete trailing sentence in
  High Standards that was cut off in the source with no way to recover the
  intended ending. Left "Assume The Worst" chunk empty (no source content
  existed) rather than inventing replacement text. Recompiled
  Chunked_Policy.md.

## v2.3.0 — pkg004 (2026-07-22)
- Fixed 4 reported bugs: (1) chunk_tag/chunk_set_status now auto-save
  in-progress editor content before redirecting; (2) added
  cmd_doc_archive_delete + /doc/archive-delete route to archive-then-remove
  a managed document; (3) added cmd_doc_chunk_rename_label +
  /chunks/rename-label route; (4) fixed aliasing bug in `_shift_chunk_pos`
  causing chunk move up/down to corrupt index_pos. Used the new
  archive-delete feature to remove managed documents GEMINI_Policies,
  Testing, and stray '.be.json' from Document_Project/, leaving only
  Chunked_Policy. Archived copies kept in Document_Project_Archive/.

## v2.2.2 — pkg003 (2026-07-16)
- Added categories CLAUDE and REACT. Imported CLAUDE.md and
  React_Policy OFC.md from dev/Policy. Applied specific tags 'claude' and
  'react' to imported chunks in GEMINI_Policies database. Compiled updated
  document project.

## v2.2.1 — pkg002 (2026-07-16)
- Ingested combined GEMINI policies from NewAgent Global context into
  document database project GEMINI_Policies under category Core_Policies.

## v2.2.0 — pkg001 (2026-07-16)
- Initial registration of CLI_Doc_Chunker in ecosystem.

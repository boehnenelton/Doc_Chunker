#!/usr/bin/env python3
"""
Doc_Chunker_Flask.py
Flask Web Interface — Doc_Chunker Visual Wrapper
Version:       1.2.0
Date:          2026-07-22
Author:        Elton Boehnen
Contact:       eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 70e62537-1295-4bb5-b2e0-d463b3318e48

Description:
  Mobile-optimized Flask wrapper for Doc_Chunker.py.
  Imports Doc_Chunker as a module — no subprocess calls.
  All routes call Doc_Chunker functions directly and return
  structured context to Jinja2 templates.

  Run: python Doc_Chunker_Flask.py
  Default: http://localhost:5050

Changelog:
  v1.1.0 — Prior baseline.
  v1.2.0 — /chunks/tag and /chunks/set-status now auto-save any in-progress
           editor content (via a hidden field synced from the textarea) before
           applying the tag/status change, so a redirect no longer discards
           unsaved edits. Added /chunks/rename-label route. Added
           /doc/archive-delete route (archive-then-remove a managed document).
"""

import os
import sys
import json
import logging
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout
from flask import Flask, render_template, redirect, url_for, request, flash, Response

# ── Self-locate and import Doc_Chunker as module ───────────────────────────────
FLASK_DIR  = Path(__file__).resolve().parent
CHUNKER_DIR = FLASK_DIR.parent  # Doc_Chunker.py lives one level up
sys.path.insert(0, str(CHUNKER_DIR))

import Doc_Chunker as DC

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "doc-chunker-flask-dev-key"

DEBUG_MODE = False  # Set True to enable verbose logging

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ── Helper: capture stdout from DC functions that print() results ──────────────
def capture(fn, *args, **kwargs):
    """Run a DC function, capture its printed output, return (output_str, return_val)."""
    buf = StringIO()
    ret_val = None
    with redirect_stdout(buf):
        ret_val = fn(*args, **kwargs)
    return buf.getvalue().strip(), ret_val

# ── Helper: build nav context (active doc, mount state) ───────────────────────
def nav_context():
    active_doc  = DC._get_active_doc()
    mount_state = DC._load_mount_state()
    is_mounted  = active_doc and active_doc in mount_state
    return {
        "active_doc": active_doc,
        "is_mounted": is_mounted,
        "mount_state": mount_state,
    }

# ── Helper: load full doc data for panel rendering ────────────────────────────
def load_active_doc_data():
    active_doc = DC._get_active_doc()
    if not active_doc:
        return None, [], []
    doc = DC._load_doc_schema(active_doc)
    if not doc:
        return active_doc, [], []
    values = doc.get("Values", [])
    cats   = DC._sorted_cats(values)
    chunks = DC._get_chunks(values)
    return active_doc, cats, chunks

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — DOCUMENTS panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def panel_documents():
    DC.cleanup_stale_mounts()
    docs        = DC._list_doc_names()
    active_doc  = DC._get_active_doc()
    mount_state = DC._load_mount_state()

    doc_rows = []
    for i, name in enumerate(docs, 1):
        doc = DC._load_doc_schema(name)
        values    = doc.get("Values", []) if doc else []
        cat_count = len(DC._get_categories(values))
        chk_count = len(DC._get_chunks(values))
        doc_rows.append({
            "idx":       i,
            "name":      name,
            "cat_count": cat_count,
            "chk_count": chk_count,
            "mounted":   name in mount_state,
            "active":    name == active_doc,
        })

    return render_template("documents.html",
        doc_rows=doc_rows,
        **nav_context()
    )

@app.route("/doc/new", methods=["POST"])
def doc_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Document name is required.", "error")
        return redirect(url_for("panel_documents"))
    out, _ = capture(DC.cmd_doc_new, name)
    flash(out, "success")
    return redirect(url_for("panel_documents"))

@app.route("/doc/sel/<int:idx>")
def doc_sel(idx):
    docs = DC._list_doc_names()
    if 1 <= idx <= len(docs):
        DC._set_active_doc(docs[idx - 1])
    return redirect(url_for("panel_documents"))

@app.route("/doc/duplicate", methods=["POST"])
def doc_duplicate():
    idx      = request.form.get("idx", "").strip()
    new_name = request.form.get("new_name", "").strip()
    if not idx or not new_name:
        flash("Index and new name are required.", "error")
        return redirect(url_for("panel_documents"))
    out, _ = capture(DC.cmd_duplicate_doc, idx, new_name)
    flash(out, "success" if "ERROR" not in out and "Error" not in out else "error")
    return redirect(url_for("panel_documents"))

@app.route("/doc/rename", methods=["POST"])
def doc_rename():
    idx      = request.form.get("idx", "").strip()
    new_name = request.form.get("new_name", "").strip()
    if not idx or not new_name:
        flash("Index and new name are required.", "error")
        return redirect(url_for("panel_documents"))
    out, _ = capture(DC.cmd_rename_doc, idx, new_name)
    flash(out, "success" if "ERROR" not in out and "Error" not in out else "error")
    return redirect(url_for("panel_documents"))

@app.route("/doc/archive-delete", methods=["POST"])
def doc_archive_delete():
    idx = request.form.get("idx", "").strip()
    if not idx:
        flash("Index is required.", "error")
        return redirect(url_for("panel_documents"))
    out, _ = capture(DC.cmd_doc_archive_delete, idx)
    flash(out, "success" if "ERROR" not in out and "Error" not in out else "error")
    return redirect(url_for("panel_documents"))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — CATEGORIES panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/categories")
def panel_categories():
    active_doc, cats, chunks = load_active_doc_data()
    if not active_doc:
        flash("No active document. Select one first.", "error")
        return redirect(url_for("panel_documents"))

    cat_rows = []
    for i, r in enumerate(cats, 1):
        cat_name  = r[DC._fi("category_name")]
        cat_pos   = r[DC._fi("category_index_pos")]
        chk_count = len(DC._sorted_chunks_in_cat(
            [*cats, *chunks], cat_name
        ))
        cat_rows.append({
            "idx":       i,
            "name":      cat_name,
            "pos":       cat_pos,
            "chk_count": chk_count,
        })

    return render_template("categories.html",
        cat_rows=cat_rows,
        **nav_context()
    )

@app.route("/categories/add", methods=["POST"])
def cat_add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("panel_categories"))
    out, _ = capture(DC.cmd_doc_cat_add, name)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_categories"))

@app.route("/categories/del", methods=["POST"])
def cat_del():
    idx = request.form.get("idx", "").strip()
    out, _ = capture(DC.cmd_doc_cat_del, idx)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_categories"))

@app.route("/categories/move", methods=["POST"])
def cat_move():
    idx       = request.form.get("idx", "").strip()
    direction = request.form.get("direction", "").strip()
    if direction == "up":
        out, _ = capture(DC.cmd_doc_cat_inc_idx_pos, idx)
    else:
        out, _ = capture(DC.cmd_doc_cat_dec_idx_pos, idx)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_categories"))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CHUNKS panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/chunks")
def panel_chunks():
    active_doc, cats, chunks = load_active_doc_data()
    if not active_doc:
        flash("No active document. Select one first.", "error")
        return redirect(url_for("panel_documents"))

    all_values = [*cats, *chunks]
    grouped = []
    for cat_row in cats:
        cat_name   = cat_row[DC._fi("category_name")]
        cat_chunks = DC._sorted_chunks_in_cat(all_values, cat_name)
        chunk_rows = []
        for i, c in enumerate(cat_chunks, 1):
            chunk_rows.append({
                "idx":     i,
                "id":      c[DC._fi("chunk_id")],
                "label":   c[DC._fi("chunk_label")],
                "pos":     c[DC._fi("chunk_index_pos")],
                "preview": (c[DC._fi("chunk_content")] or "")[:80].replace("\n", " "),
                "empty":   not (c[DC._fi("chunk_content")] or "").strip(),
            })
        grouped.append({
            "cat_name":  cat_name,
            "cat_pos":   cat_row[DC._fi("category_index_pos")],
            "cat_idx":   cats.index(cat_row) + 1,
            "chunks":    chunk_rows,
        })

    cat_names = [r[DC._fi("category_name")] for r in cats]

    return render_template("chunks.html",
        grouped=grouped,
        cat_names=cat_names,
        **nav_context()
    )

@app.route("/chunks/add", methods=["POST"])
def chunk_add():
    category = request.form.get("category", "").strip()
    label    = request.form.get("label", "").strip() or None
    if not category:
        flash("Category is required.", "error")
        return redirect(url_for("panel_chunks"))
    out, _ = capture(DC.cmd_doc_chunk_add, category, label)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_chunks"))

@app.route("/chunks/del", methods=["POST"])
def chunk_del():
    chunk_id = request.form.get("chunk_id", "").strip()
    out, _   = capture(DC.cmd_doc_chunk_del, chunk_id)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_chunks"))

@app.route("/chunks/move", methods=["POST"])
def chunk_move():
    chunk_id  = request.form.get("chunk_id", "").strip()
    direction = request.form.get("direction", "").strip()
    if direction == "up":
        out, _ = capture(DC.cmd_doc_chunk_inc_idx_pos, chunk_id)
    else:
        out, _ = capture(DC.cmd_doc_chunk_dec_idx_pos, chunk_id)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_chunks"))

@app.route("/chunks/reparent", methods=["POST"])
def chunk_reparent():
    chunk_id    = request.form.get("chunk_id", "").strip()
    new_category = request.form.get("new_category", "").strip()
    out, _ = capture(DC.cmd_doc_chunk_set_parent_cat, chunk_id, new_category)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_chunks"))

# ── Chunk editor ───────────────────────────────────────────────────────────────

@app.route("/chunks/edit/<chunk_id>")
def chunk_edit(chunk_id):
    active_doc, cats, chunks = load_active_doc_data()
    if not active_doc:
        flash("No active document.", "error")
        return redirect(url_for("panel_documents"))

    target_chunk = None
    all_values = [*cats, *chunks]
    chunk_list = DC._get_chunks(all_values)
    for i, c in enumerate(chunk_list):
        if c[DC._fi("chunk_id")] == chunk_id:
            target_chunk = {
                "id":       c[DC._fi("chunk_id")],
                "label":    c[DC._fi("chunk_label")],
                "content":  c[DC._fi("chunk_content")] or "",
                "category": c[DC._fi("parent_category")],
                "pos":      c[DC._fi("chunk_index_pos")],
                "tags":     c[DC._fi("chunk_tags")] or "",
                "status":   c[DC._fi("chunk_status")] or "draft",
                "prev_id":  chunk_list[i - 1][DC._fi("chunk_id")] if i > 0 else None,
                "next_id":  chunk_list[i + 1][DC._fi("chunk_id")] if i < len(chunk_list) - 1 else None,
            }
            break

    if not target_chunk:
        flash(f"Chunk '{chunk_id}' not found.", "error")
        return redirect(url_for("panel_chunks"))

    cat_names = [r[DC._fi("category_name")] for r in cats]

    return render_template("chunk_editor.html",
        chunk=target_chunk,
        cat_names=cat_names,
        **nav_context()
    )

@app.route("/chunks/save", methods=["POST"])
def chunk_save():
    chunk_id = request.form.get("chunk_id", "").strip()
    content  = request.form.get("content", "")
    out, _   = capture(DC.cmd_doc_chunk_write, chunk_id, content)
    flash("Chunk saved." if "Error" not in out else out,
          "success" if "Error" not in out else "error")
    return redirect(url_for("chunk_edit", chunk_id=chunk_id))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MOUNT & EDIT panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/mount")
def panel_mount():
    active_doc  = DC._get_active_doc()
    mount_state = DC._load_mount_state()
    mounted_files = []

    if active_doc and active_doc in mount_state:
        mounted_dir = DC._doc_mounted_dir(active_doc)
        if mounted_dir.exists():
            for cat_dir in sorted(mounted_dir.iterdir()):
                if cat_dir.is_dir():
                    for txt_file in sorted(cat_dir.iterdir()):
                        if txt_file.suffix == ".txt":
                            mounted_files.append({
                                "category": cat_dir.name,
                                "filename": txt_file.name,
                                "path":     str(txt_file.relative_to(mounted_dir)),
                                "size":     txt_file.stat().st_size,
                            })

    mount_entry = mount_state.get(active_doc, {}) if active_doc else {}

    return render_template("mount.html",
        mounted_files=mounted_files,
        mount_entry=mount_entry,
        **nav_context()
    )

@app.route("/mount/do", methods=["POST"])
def mount_do():
    out, _ = capture(DC.cmd_doc_mount)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_mount"))

@app.route("/mount/commit", methods=["POST"])
def mount_commit():
    out, _ = capture(DC.cmd_doc_commit)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_mount"))

@app.route("/mount/discard", methods=["POST"])
def mount_discard():
    out, _ = capture(DC.cmd_doc_discard)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_mount"))

@app.route("/mount/edit-file")
def mount_edit_file():
    """Edit a mounted .txt file directly."""
    active_doc = DC._get_active_doc()
    rel_path   = request.args.get("path", "")
    if not active_doc or not rel_path:
        flash("Invalid request.", "error")
        return redirect(url_for("panel_mount"))

    mount_state = DC._load_mount_state()
    if active_doc not in mount_state:
        flash("Document is not mounted.", "error")
        return redirect(url_for("panel_mount"))

    mounted_dir = DC._doc_mounted_dir(active_doc)
    file_path   = (mounted_dir / rel_path).resolve()

    # Security: must stay inside mounted_dir
    if not str(file_path).startswith(str(mounted_dir.resolve())):
        flash("Access denied.", "error")
        return redirect(url_for("panel_mount"))

    if not file_path.exists():
        flash("File not found.", "error")
        return redirect(url_for("panel_mount"))

    content = file_path.read_text(encoding="utf-8")

    return render_template("mount_file_editor.html",
        rel_path=rel_path,
        filename=file_path.name,
        category=file_path.parent.name,
        content=content,
        **nav_context()
    )

@app.route("/mount/save-file", methods=["POST"])
def mount_save_file():
    active_doc = DC._get_active_doc()
    rel_path   = request.form.get("rel_path", "")
    content    = request.form.get("content", "")

    if not active_doc or not rel_path:
        flash("Invalid request.", "error")
        return redirect(url_for("panel_mount"))

    mounted_dir = DC._doc_mounted_dir(active_doc)
    file_path   = (mounted_dir / rel_path).resolve()

    if not str(file_path).startswith(str(mounted_dir.resolve())):
        flash("Access denied.", "error")
        return redirect(url_for("panel_mount"))

    file_path.write_text(content, encoding="utf-8")
    flash(f"Saved: {rel_path}", "success")
    return redirect(url_for("mount_edit_file", path=rel_path))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — COMPILE & EXPORT panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/compile")
def panel_compile():
    active_doc = DC._get_active_doc()
    compiled_output = None
    compiled_path   = None

    if active_doc:
        compiled_file = DC._doc_compiled_dir(active_doc) / f"{active_doc}.md"
        if compiled_file.exists():
            compiled_output = compiled_file.read_text(encoding="utf-8")
            compiled_path   = str(compiled_file)

    docs     = DC._list_doc_names()
    doc_rows = [{"idx": i, "name": n} for i, n in enumerate(docs, 1)]

    return render_template("compile.html",
        compiled_output=compiled_output,
        compiled_path=compiled_path,
        doc_rows=doc_rows,
        **nav_context()
    )

@app.route("/compile/do", methods=["POST"])
def compile_do():
    out, _ = capture(DC.cmd_doc_compile)
    flash(out, "success" if "Error" not in out and "Warning" not in out else "error")
    return redirect(url_for("panel_compile"))

@app.route("/compile/export", methods=["POST"])
def compile_export():
    idx    = request.form.get("idx", "").strip()
    fmt    = request.form.get("format", "md").strip()
    out, _ = capture(DC.cmd_export_doc, idx, fmt)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_compile"))

@app.route("/compile/download/<doc_name>/<fmt>")
def compile_download(doc_name, fmt):
    """Serve the exported file as a download."""
    valid_exts = {"md": "text/markdown", "txt": "text/plain", "json": "application/json"}
    if fmt not in valid_exts:
        flash("Invalid format.", "error")
        return redirect(url_for("panel_compile"))

    file_path = DC._doc_compiled_dir(doc_name) / f"{doc_name}_export.{fmt}"
    if not file_path.exists():
        flash("Export file not found. Run export first.", "error")
        return redirect(url_for("panel_compile"))

    content = file_path.read_text(encoding="utf-8")
    return Response(
        content,
        mimetype=valid_exts[fmt],
        headers={"Content-Disposition": f"attachment; filename={file_path.name}"}
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — FIND & STATS panel
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/tools")
def panel_tools():
    active_doc, cats, chunks = load_active_doc_data()
    snapshots = []
    if active_doc:
        snap_dir = DC.DOC_PROJECT_DIR / active_doc / "Snapshots"
        if snap_dir.exists():
            snapshots = sorted(
                [f.name for f in snap_dir.iterdir() if f.suffix == ".zip"],
                reverse=True
            )
    doc_rows = [{"idx": i, "name": n} for i, n in enumerate(DC._list_doc_names(), 1)]
    return render_template("tools.html",
        snapshots=snapshots,
        doc_rows=doc_rows,
        **nav_context()
    )

@app.route("/tools/find", methods=["POST"])
def tools_find():
    query = request.form.get("query", "").strip()
    if not query:
        flash("Search text is required.", "error")
        return redirect(url_for("panel_tools"))
    out, _ = capture(DC.cmd_doc_find, query)
    return render_template("tools_find_result.html",
        query=query,
        result=out,
        **nav_context()
    )

@app.route("/tools/stats")
def tools_stats():
    out, _ = capture(DC.cmd_doc_stats)
    return render_template("tools_stats_result.html",
        result=out,
        **nav_context()
    )

@app.route("/tools/snapshot", methods=["POST"])
def tools_snapshot():
    out, _ = capture(DC.cmd_doc_snapshot)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_tools"))

@app.route("/tools/restore-snapshot", methods=["POST"])
def tools_restore_snapshot():
    filename   = request.form.get("filename", "").strip()
    active_doc = DC._get_active_doc()
    if not active_doc or not filename:
        flash("No active doc or filename.", "error")
        return redirect(url_for("panel_tools"))
    snap_path = DC.DOC_PROJECT_DIR / active_doc / "Snapshots" / filename
    out, _    = capture(DC.cmd_doc_restore_snapshot, str(snap_path))
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_tools"))

@app.route("/tools/lock", methods=["POST"])
def tools_lock():
    idx = request.form.get("idx", "").strip() or None
    out, _ = capture(DC.cmd_doc_lock, idx)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_tools"))

@app.route("/tools/unlock", methods=["POST"])
def tools_unlock():
    idx = request.form.get("idx", "").strip() or None
    out, _ = capture(DC.cmd_doc_unlock, idx)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_tools"))

@app.route("/tools/import-file", methods=["POST"])
def tools_import_file():
    file_path  = request.form.get("file_path", "").strip()
    delimiter  = request.form.get("delimiter", "---").strip()
    category   = request.form.get("category", "").strip()
    label_pfx  = request.form.get("label_prefix", "").strip() or None
    if not file_path or not category:
        flash("File path and category are required.", "error")
        return redirect(url_for("panel_tools"))
    out, _ = capture(DC.cmd_doc_import_file, file_path, delimiter, category, label_pfx)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_chunks"))

@app.route("/tools/merge", methods=["POST"])
def tools_merge():
    idx_list    = request.form.get("idx_list", "").strip()
    output_name = request.form.get("output_name", "").strip()
    if not idx_list or not output_name:
        flash("Doc index list and output name are required.", "error")
        return redirect(url_for("panel_tools"))
    out, _ = capture(DC.cmd_doc_merge, idx_list, output_name)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_tools"))

# ── Chunk tag + status routes (called from chunk editor) ──────────────────────

@app.route("/chunks/tag", methods=["POST"])
def chunk_tag():
    chunk_id = request.form.get("chunk_id", "").strip()
    tags     = request.form.get("tags", "").strip()
    content  = request.form.get("content", None)
    # Save any in-progress editor content first so it isn't lost on this redirect.
    if content is not None:
        capture(DC.cmd_doc_chunk_write, chunk_id, content)
    out, _   = capture(DC.cmd_doc_chunk_tag, chunk_id, tags)
    flash("Tags updated." if "Error" not in out else out,
          "success" if "Error" not in out else "error")
    return redirect(url_for("chunk_edit", chunk_id=chunk_id))

@app.route("/chunks/set-status", methods=["POST"])
def chunk_set_status():
    chunk_id = request.form.get("chunk_id", "").strip()
    status   = request.form.get("status", "draft").strip()
    content  = request.form.get("content", None)
    # Save any in-progress editor content first so it isn't lost on this redirect.
    if content is not None:
        capture(DC.cmd_doc_chunk_write, chunk_id, content)
    out, _   = capture(DC.cmd_doc_chunk_set_status, chunk_id, status)
    flash("Status updated." if "Error" not in out else out,
          "success" if "Error" not in out else "error")
    return redirect(url_for("chunk_edit", chunk_id=chunk_id))

@app.route("/chunks/rename-label", methods=["POST"])
def chunk_rename_label():
    chunk_id  = request.form.get("chunk_id", "").strip()
    new_label = request.form.get("new_label", "").strip()
    content   = request.form.get("content", None)
    if not new_label:
        flash("New label is required.", "error")
        return redirect(url_for("chunk_edit", chunk_id=chunk_id))
    # Save any in-progress editor content first so it isn't lost on this redirect.
    if content is not None:
        capture(DC.cmd_doc_chunk_write, chunk_id, content)
    out, _ = capture(DC.cmd_doc_chunk_rename_label, chunk_id, new_label)
    flash("Label renamed." if "Error" not in out else out,
          "success" if "Error" not in out else "error")
    return redirect(url_for("chunk_edit", chunk_id=chunk_id))

# ── Filtered compile route ────────────────────────────────────────────────────

@app.route("/compile/filtered", methods=["POST"])
def compile_filtered():
    filter_tag    = request.form.get("filter_tag", "").strip() or None
    filter_status = request.form.get("filter_status", "").strip() or None
    out, _ = capture(DC.cmd_doc_compile_filtered, filter_tag, filter_status)
    flash(out, "success" if "Error" not in out else "error")
    return redirect(url_for("panel_compile"))

# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5050"))
    app.run(host=host, port=port, debug=DEBUG_MODE)

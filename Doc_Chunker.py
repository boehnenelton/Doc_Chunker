#!/usr/bin/env python3
"""
Doc_Chunker.py
Document Chunker & Manager — BEJSON 104db Document System + Project Chunker
Version:       2.3.0
Date:          2026-07-22
Author:        Elton Boehnen
Contact:       eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: d9799926-cc05-4a47-894d-a89909452469

Changelog:
  v2.0.0 — Added Document Management System (MODE 2).
  v2.1.0 — Renamed to Doc_Chunker. Added duplicate-doc, rename-doc, export-doc.
  v2.2.0 — Tier 1: diff on chunk save, --doc-find, --doc-stats.
           Tier 2: chunk tags + status fields in schema, --doc-chunk-tag,
           --doc-chunk-set-status, --doc-compile-filtered, --doc-merge,
           --doc-import-file, --doc-lock, --doc-unlock, --doc-snapshot,
           --doc-restore-snapshot.
  v2.2.1 — Updated lib imports to new lib_bejson_* naming scheme (Core/Utility families).
           Fixed OSError ENAMETOOLONG crash in cmd_doc_chunk_write when chunk content
           was passed as a long text string (Android PATH_MAX guard added).
  v2.3.0 — Fixed aliasing bug in _shift_chunk_pos (chunk move up/down): reading
           swap positions from `siblings` mid-loop returned already-mutated values
           since `siblings` rows are the same objects as `values` rows, causing
           both chunks to collapse onto the same index_pos instead of swapping.
           Now snapshots both original positions before mutating either row.
           Added cmd_doc_chunk_rename_label (relabel an existing chunk without
           touching content/tags/status). Added cmd_doc_archive_delete (zips the
           full doc dir to Document_Project_Archive/, then removes it from
           Document_Project/, clearing any active-doc/mount-state reference).
"""
import os
import sys
import json
import argparse
import time
import uuid
import shutil
import difflib
import zipfile
from pathlib import Path
from datetime import datetime, timezone

# ── Self-locate ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "lib"))

try:
    import lib_bejson_Core_bejson_core as BEJSONCore
    import lib_bejson_Utility_bejson_utility as Utility
    import lib_bejson_Core_bejson_validator as Validator
except ImportError:
    print("CRITICAL: Local libraries not found in lib/")
    sys.exit(1)

# ── Global paths ───────────────────────────────────────────────────────────────
PROJECTS_DIR      = BASE_DIR / "Projects"
HISTORY_FILE      = BASE_DIR / "chunk_history.104a.bejson"
REGISTRY_FILE     = BASE_DIR / "project_registry.104a.bejson"
DOC_PROJECT_DIR   = BASE_DIR / "Document_Project"
PERSIST_DIR       = BASE_DIR / "data" / "persist"
MOUNTED_STATE_FILE = PERSIST_DIR / "mounted.json"

# Active document selection (in-session state file)
ACTIVE_DOC_FILE   = BASE_DIR / "data" / "active_doc.txt"

# Mount TTL in seconds (1 hour)
MOUNT_TTL_SECONDS = 3600

# ── Schema definitions ─────────────────────────────────────────────────────────
HISTORY_FIELDS = [
    {"name": "timestamp",    "type": "string"},
    {"name": "project_name", "type": "string"},
    {"name": "version",      "type": "string"},
    {"name": "file_path",    "type": "string"}
]

REGISTRY_FIELDS = [
    {"name": "project_name",  "type": "string"},
    {"name": "original_path", "type": "string"},
    {"name": "last_chunked",  "type": "string"}
]

# 104db document schema — two record types in one file
DOC_SCHEMA_RECORD_TYPES = ["Document_Categories", "Chunks"]

DOC_SCHEMA_FIELDS = [
    # Discriminator — required first field in every 104db record
    {"name": "Record_Type_Parent",    "type": "string"},
    # Document_Categories fields
    {"name": "category_name",         "type": "string",  "Record_Type_Parent": "Document_Categories"},
    {"name": "category_index_pos",    "type": "integer", "Record_Type_Parent": "Document_Categories"},
    # Document_Categories — locked flag (boolean stored as string "true"/"false" for 104db compat)
    {"name": "category_locked",       "type": "string",  "Record_Type_Parent": "Document_Categories"},
    # Chunks fields
    {"name": "chunk_id",              "type": "string",  "Record_Type_Parent": "Chunks"},
    {"name": "chunk_label",           "type": "string",  "Record_Type_Parent": "Chunks"},
    {"name": "chunk_content",         "type": "string",  "Record_Type_Parent": "Chunks"},
    {"name": "parent_category",       "type": "string",  "Record_Type_Parent": "Chunks"},
    {"name": "chunk_index_pos",       "type": "integer", "Record_Type_Parent": "Chunks"},
    # Tier 2 additions
    {"name": "chunk_tags",            "type": "string",  "Record_Type_Parent": "Chunks"},
    {"name": "chunk_status",          "type": "string",  "Record_Type_Parent": "Chunks"},
]

# Valid chunk status values
CHUNK_STATUS_VALUES = ("draft", "review", "final", "skip")
# Default status for new chunks
CHUNK_STATUS_DEFAULT = "draft"

# Field index map — positional access by name
_DOC_FIELD_NAMES = [f["name"] for f in DOC_SCHEMA_FIELDS]
def _fi(name):
    return _DOC_FIELD_NAMES.index(name)

# Null-padded empty rows for each record type
def _cat_row(category_name, category_index_pos):
    row = [None] * len(DOC_SCHEMA_FIELDS)
    row[_fi("Record_Type_Parent")] = "Document_Categories"
    row[_fi("category_name")]      = category_name
    row[_fi("category_index_pos")] = category_index_pos
    return row

def _chunk_row(chunk_id, chunk_label, chunk_content, parent_category, chunk_index_pos,
               chunk_tags=None, chunk_status=None):
    row = [None] * len(DOC_SCHEMA_FIELDS)
    row[_fi("Record_Type_Parent")] = "Chunks"
    row[_fi("chunk_id")]           = chunk_id
    row[_fi("chunk_label")]        = chunk_label
    row[_fi("chunk_content")]      = chunk_content
    row[_fi("parent_category")]    = parent_category
    row[_fi("chunk_index_pos")]    = chunk_index_pos
    row[_fi("chunk_tags")]         = chunk_tags or ""
    row[_fi("chunk_status")]       = chunk_status or CHUNK_STATUS_DEFAULT
    return row

def _cat_is_locked(cat_row):
    """Return True if the category/doc is locked."""
    locked_val = cat_row[_fi("category_locked")] if len(cat_row) > _fi("category_locked") else None
    return locked_val == "true"

DEFAULT_CONFIG = {
    "extensions": Utility.DEFAULT_EXTENSIONS,
    "exclude_dirs": Utility.DEFAULT_EXCLUDES,
    "evade_mime": True
}

# ── Utilities ──────────────────────────────────────────────────────────────────
def get_timestamp():
    return Utility.bejson_utility_get_timestamp()

def now_unix():
    return int(time.time())

def short_id():
    return str(uuid.uuid4())[:8]

def atomic_write_json(path, data):
    path = Path(path)
    tmp  = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def safe_name(name):
    return name.strip().replace(" ", "_")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A — STALE MOUNT CLEANUP (runs at startup)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_mount_state():
    if not MOUNTED_STATE_FILE.exists():
        return {}
    try:
        return json.loads(MOUNTED_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_mount_state(state):
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(MOUNTED_STATE_FILE, state)

def _discard_mount_files(doc_name):
    mounted_dir = DOC_PROJECT_DIR / doc_name / "Mounted"
    if mounted_dir.exists():
        shutil.rmtree(mounted_dir)
        mounted_dir.mkdir(parents=True, exist_ok=True)

def cleanup_stale_mounts():
    """
    Called at startup. Checks mounted.json for entries older than MOUNT_TTL_SECONDS.
    Any stale mount has its Mounted/ directory silently wiped and is removed from state.
    """
    state = _load_mount_state()
    if not state:
        return

    now = now_unix()
    stale_keys = []
    for doc_name, entry in state.items():
        age = now - entry.get("mounted_at", 0)
        if age > MOUNT_TTL_SECONDS:
            stale_keys.append(doc_name)

    for doc_name in stale_keys:
        _discard_mount_files(doc_name)
        del state[doc_name]

    if stale_keys:
        _save_mount_state(state)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B — ORIGINAL PROJECT CHUNKER (preserved exactly)
# ═══════════════════════════════════════════════════════════════════════════════

def get_next_version(project_root):
    if not project_root.exists():
        return "v1"
    versions = []
    for d in project_root.iterdir():
        if d.is_dir() and d.name.startswith("v"):
            try:
                versions.append(int(d.name[1:]))
            except:
                pass
    if not versions:
        return "v1"
    return f"v{max(versions) + 1}"

def save_to_registry(project_name, original_path):
    registry = []
    if REGISTRY_FILE.exists():
        try:
            doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
            registry = doc.get("Values", [])
        except:
            pass
    found = False
    for i, row in enumerate(registry):
        if row[0] == project_name:
            registry[i][1] = str(original_path)
            registry[i][2] = get_timestamp()
            found = True
            break
    if not found:
        registry.append([project_name, str(original_path), get_timestamp()])
    doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, registry)
    BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)

def save_to_history(project_name, version, file_path):
    history = []
    if HISTORY_FILE.exists():
        try:
            doc = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
            history = doc.get("Values", [])
        except:
            pass
    history.insert(0, [get_timestamp(), project_name, version, str(file_path)])
    history = history[:100]
    doc = BEJSONCore.bejson_core_create_104a("ChunkHistory", HISTORY_FIELDS, history)
    BEJSONCore.bejson_core_atomic_write(str(HISTORY_FILE), doc)

def list_chunk_index():
    if not REGISTRY_FILE.exists():
        print("No project registry found.")
        return
    try:
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if not values:
            print("Registry is empty.")
            return
        print(f"\n{'ID':<4} | {'Project Name':<25} | {'Source Path'}")
        print("-" * 100)
        for i, row in enumerate(values, 1):
            name, path, _ = row
            print(f"{i:<4} | {name:<25} | {path}")
    except Exception as e:
        print(f"Error reading registry: {e}")

def list_unchunk_index():
    if not HISTORY_FILE.exists():
        print("No chunk history found.")
        return
    try:
        doc = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
        values = doc.get("Values", [])
        if not values:
            print("History is empty.")
            return
        print(f"\n{'ID':<4} | {'Timestamp':<20} | {'Project':<20} | {'Ver':<6} | {'Chunk Path'}")
        print("-" * 120)
        for i, row in enumerate(values, 1):
            if len(row) == 4:
                ts, proj, ver, path = row
            else:
                ts, proj, path = row
                ver = "legacy"
            print(f"{i:<4} | {ts:<20} | {proj:<20} | {ver:<6} | {path}")
    except Exception as e:
        print(f"Error reading history: {e}")

def resolve_registry_id(index_str):
    if not REGISTRY_FILE.exists():
        return None
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            return values[idx][0]
    except:
        pass
    return None

def resolve_registry_path(index_str):
    if not REGISTRY_FILE.exists():
        return None
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            return values[idx][1]
    except:
        pass
    return None

def resolve_history_path(index_str):
    if not HISTORY_FILE.exists():
        return None
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(HISTORY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            return values[idx][-1]
    except:
        pass
    return None

def expell_project(index_str):
    if not REGISTRY_FILE.exists():
        print("Error: No project registry found.")
        return
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            removed = values.pop(idx)
            print(f"[*] Expelling project: {removed[0]} (Registry entry removed, files preserved)")
            doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, values)
            BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)
        else:
            print(f"Error: Project ID {index_str} not found.")
    except Exception as e:
        print(f"Error expelling project: {e}")

def delete_project(index_str):
    if not REGISTRY_FILE.exists():
        print("Error: No project registry found.")
        return
    try:
        idx = int(index_str) - 1
        doc = BEJSONCore.bejson_core_load_file(str(REGISTRY_FILE))
        values = doc.get("Values", [])
        if 0 <= idx < len(values):
            removed = values.pop(idx)
            project_name = removed[0]
            print(f"[*] Deleting project: {project_name}")
            doc = BEJSONCore.bejson_core_create_104a("ProjectRegistry", REGISTRY_FIELDS, values)
            BEJSONCore.bejson_core_atomic_write(str(REGISTRY_FILE), doc)
            project_root = PROJECTS_DIR / project_name
            if project_root.exists():
                shutil.rmtree(project_root)
                print(f"[*] Deleted project files at {project_root}")
            else:
                print(f"Warning: Project folder not found at {project_root}")
        else:
            print(f"Error: Project ID {index_str} not found.")
    except Exception as e:
        print(f"Error deleting project: {e}")

def get_versions(index_str):
    project_name = resolve_registry_id(index_str)
    if not project_name:
        print(f"Error: Project ID {index_str} not found.")
        return
    project_root = PROJECTS_DIR / project_name
    if not project_root.exists():
        print(f"No versioned files found for project: {project_name}")
        return
    versions = sorted(
        [d.name for d in project_root.iterdir() if d.is_dir() and d.name.startswith("v")],
        key=lambda x: int(x[1:]) if x[1:].isdigit() else 0
    )
    if not versions:
        print(f"No versions found for {project_name}")
        return
    print(f"\nVersions for project: {project_name}")
    print("-" * 30)
    for v in versions:
        print(f"  - {v}")

def delete_version(index_str, version_str):
    project_name = resolve_registry_id(index_str)
    if not project_name:
        print(f"Error: Project ID {index_str} not found.")
        return
    version_dir = PROJECTS_DIR / project_name / version_str
    if version_dir.exists() and version_dir.is_dir():
        print(f"[*] Deleting version {version_str} for project {project_name}...")
        shutil.rmtree(version_dir)
        print("[*] Success.")
    else:
        print(f"Error: Version {version_str} not found for project {project_name} at {version_dir}")

def run_chunk(target_dir):
    target_path = Path(target_dir).resolve()
    if not target_path.is_dir():
        print(f"Error: {target_dir} is not a directory.")
        return
    project_name = target_path.name.replace(" ", "_")
    project_root = PROJECTS_DIR / project_name
    version      = get_next_version(project_root)
    version_dir  = project_root / version
    version_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Mode: CHUNK (104db)")
    print(f"[*] Project: {project_name} ({version})")
    print(f"[*] Target: {target_path}")
    doc = Utility.bejson_utility_create_cli_chunk(
        target_dir=str(target_path),
        project_name=project_name,
        version=version
    )
    print("[*] Validating BEJSON structure...")
    res = Validator.validate_bejson(doc)
    if not res.valid:
        print("\n[ERROR] BEJSON Validation Failed:")
        for err in res.errors:
            print(f"  - {err}")
        return
    ext = ".104db.bejson"
    if DEFAULT_CONFIG.get("evade_mime"):
        ext += ".txt"
    out_file = version_dir / f'Chunked_{Utility.bejson_utility_sanitize_name(project_name)}_{version}{ext}'
    if Utility.bejson_utility_save_chunk(str(out_file), doc):
        print(f"\n[SUCCESS] Project chunked into {out_file}")
        print(f"[*] Total Records: {len(doc['Values'])}")
        save_to_registry(project_name, target_path)
        save_to_history(project_name, version, out_file)
    else:
        print(f"\n[ERROR] Failed to save BEJSON chunk.")

def run_unchunk(bejson_file, destination=None):
    input_path = Path(bejson_file).resolve()
    if not input_path.exists():
        print(f"Error: File {bejson_file} not found.")
        return
    print(f"[*] Mode: UNCHUNK")
    print(f"[*] Source: {input_path}")
    try:
        print("[*] Validating BEJSON structure...")
        res = Validator.validate_bejson(str(input_path), is_file=True)
        if not res.valid:
            print("\n[ERROR] BEJSON Validation Failed:")
            for err in res.errors:
                print(f"  - {err}")
            return
        doc = BEJSONCore.bejson_core_load_file(str(input_path))
        if doc.get("Format_Version") != "104db":
            print("Error: Input is not a valid BEJSON 104db file.")
            return
        fields   = [f["name"] for f in doc["Fields"]]
        pname_idx = fields.index("project_name")
        fpath_idx = fields.index("file_path")
        cont_idx  = fields.index("content")
        bin_idx   = fields.index("is_binary")
        meta_rows = [r for r in doc["Values"] if r[0] == "ProjectMeta"]
        proj_name = meta_rows[0][pname_idx] if meta_rows else "RestoredProject"
        if destination:
            out_dir = Path(destination).resolve()
        else:
            ts_slug = get_timestamp().replace(":", "").replace("-", "")
            out_dir = Path.cwd() / "Restored_Projects" / proj_name / ts_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        file_rows = [r for r in doc["Values"] if r[0] == "FileContent"]
        for row in file_rows:
            rel_path = row[fpath_idx]
            content  = row[cont_idx]
            binary   = row[bin_idx]
            if rel_path:
                target_file = out_dir / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if binary:
                    target_file.touch()
                else:
                    target_file.write_text(content, encoding="utf-8")
                print(f"  [>] {rel_path}")
        print(f"\n[SUCCESS] Project rebuilt at {out_dir}")
    except Exception as e:
        print(f"\n[ERROR] Unchunking failed: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION C — DOCUMENT MANAGEMENT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════
#
# Directory layout:
#   Document_Project/
#     (Doc_Name)/
#       Schema/
#         (Doc_Name).104db.bejson   ← single schema file, FORM 1
#       Mounted/
#         (Category_Name)/
#           (Chunk_Label)-(Chunk_ID).txt   ← FORM 2, one file per chunk
#       Compiled/
#         (Doc_Name).md              ← FORM 3, final compiled Markdown
#
# data/persist/mounted.json  ← mount state: {doc_name: {mounted_at, file_sizes}}
#
# ─────────────────────────────────────────────────────────────────────────────

def _doc_schema_path(doc_name):
    return DOC_PROJECT_DIR / doc_name / "Schema" / f"{doc_name}.104db.bejson"

def _doc_mounted_dir(doc_name):
    return DOC_PROJECT_DIR / doc_name / "Mounted"

def _doc_compiled_dir(doc_name):
    return DOC_PROJECT_DIR / doc_name / "Compiled"

def _load_doc_schema(doc_name):
    schema_path = _doc_schema_path(doc_name)
    if not schema_path.exists():
        print(f"Error: No schema found for document project '{doc_name}'.")
        print(f"       Expected: {schema_path}")
        return None
    return BEJSONCore.bejson_core_load_file(str(schema_path))

def _save_doc_schema(doc_name, values):
    schema_path = _doc_schema_path(doc_name)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "Format":         "BEJSON",
        "Format_Version": "104db",
        "Format_Creator": "Elton Boehnen",
        "Records_Type":   DOC_SCHEMA_RECORD_TYPES,
        "Fields":         DOC_SCHEMA_FIELDS,
        "Values":         values,
    }
    BEJSONCore.bejson_core_atomic_write(str(schema_path), doc)

def _get_active_doc():
    ACTIVE_DOC_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ACTIVE_DOC_FILE.exists():
        name = ACTIVE_DOC_FILE.read_text(encoding="utf-8").strip()
        if name and (DOC_PROJECT_DIR / name).exists():
            return name
    return None

def _set_active_doc(doc_name):
    ACTIVE_DOC_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_DOC_FILE.write_text(doc_name, encoding="utf-8")

def _require_active_doc():
    name = _get_active_doc()
    if not name:
        print("Error: No active document project selected. Run --doc-list then --doc-sel IDX.")
        return None
    return name

def _list_doc_names():
    if not DOC_PROJECT_DIR.exists():
        return []
    return sorted([d.name for d in DOC_PROJECT_DIR.iterdir() if d.is_dir()])

def _get_categories(values):
    return [r for r in values if r[_fi("Record_Type_Parent")] == "Document_Categories"]

def _get_chunks(values):
    return [r for r in values if r[_fi("Record_Type_Parent")] == "Chunks"]

def _sorted_cats(values):
    cats = _get_categories(values)
    return sorted(cats, key=lambda r: (r[_fi("category_index_pos")] or 0))

def _sorted_chunks_in_cat(values, category_name):
    chunks = [r for r in _get_chunks(values) if r[_fi("parent_category")] == category_name]
    return sorted(chunks, key=lambda r: (r[_fi("chunk_index_pos")] or 0))

def _chunk_filename(chunk_label, chunk_id):
    safe_label = chunk_label.strip().replace(" ", "_").replace("/", "-")
    return f"{safe_label}-{chunk_id}.txt"

# ── Project Management ─────────────────────────────────────────────────────────

def cmd_doc_new(doc_name):
    doc_name = safe_name(doc_name)
    doc_dir  = DOC_PROJECT_DIR / doc_name

    if doc_dir.exists():
        print(f"Error: Document project '{doc_name}' already exists.")
        return

    (doc_dir / "Schema").mkdir(parents=True, exist_ok=True)
    (doc_dir / "Mounted").mkdir(parents=True, exist_ok=True)
    (doc_dir / "Compiled").mkdir(parents=True, exist_ok=True)

    # Empty schema — no categories, no chunks yet
    _save_doc_schema(doc_name, [])
    _set_active_doc(doc_name)

    print(f"[*] Document project created: {doc_name}")
    print(f"    Schema/   → {doc_dir / 'Schema'}")
    print(f"    Mounted/  → {doc_dir / 'Mounted'}")
    print(f"    Compiled/ → {doc_dir / 'Compiled'}")
    print(f"[*] Active doc set to: {doc_name}")

def cmd_doc_list():
    docs   = _list_doc_names()
    active = _get_active_doc()
    state  = _load_mount_state()

    if not docs:
        print("No document projects found.")
        return

    print(f"\n{'ID':<4} {'Name':<30} {'Cats':<6} {'Chunks':<8} {'Mounted':<10} Status")
    print("─" * 75)
    for i, name in enumerate(docs, 1):
        doc = _load_doc_schema(name)
        values   = doc.get("Values", []) if doc else []
        cat_cnt  = len(_get_categories(values))
        chk_cnt  = len(_get_chunks(values))
        mounted  = "yes" if name in state else "no"
        active_flag = " ← active" if name == active else ""
        print(f"{i:<4} {name:<30} {cat_cnt:<6} {chk_cnt:<8} {mounted:<10}{active_flag}")

def cmd_doc_sel(idx_str):
    docs = _list_doc_names()
    try:
        doc_name = docs[int(idx_str) - 1]
    except (IndexError, ValueError):
        print(f"Error: Document ID {idx_str} not found. Run --doc-list first.")
        return
    _set_active_doc(doc_name)
    print(f"[*] Active document: {doc_name}")

# ── Category Management ────────────────────────────────────────────────────────

def cmd_doc_cat_list():
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    if not cats:
        print(f"No categories in '{doc_name}'. Use --doc-cat-add NAME.")
        return

    print(f"\nCategories in: {doc_name}")
    print(f"{'Pos':<5} Category Name")
    print("─" * 40)
    for r in cats:
        print(f"{r[_fi('category_index_pos')]:<5} {r[_fi('category_name')]}")

def cmd_doc_cat_add(category_name):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    # Check name not already used
    existing_names = [r[_fi("category_name")] for r in cats]
    if category_name in existing_names:
        print(f"Error: Category '{category_name}' already exists.")
        return

    next_pos = max((r[_fi("category_index_pos")] or 0 for r in cats), default=0) + 1
    values.append(_cat_row(category_name, next_pos))
    _save_doc_schema(doc_name, values)
    print(f"[*] Category added: '{category_name}' at position {next_pos}")

def cmd_doc_cat_del(idx_str):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    try:
        target_cat_row = cats[int(idx_str) - 1]
    except (IndexError, ValueError):
        print(f"Error: Category index {idx_str} not found.")
        return

    cat_name = target_cat_row[_fi("category_name")]
    orphaned_chunks = _sorted_chunks_in_cat(values, cat_name)
    if orphaned_chunks:
        print(f"Error: Category '{cat_name}' has {len(orphaned_chunks)} chunk(s). Delete or reassign them first.")
        return

    values = [r for r in values if not (
        r[_fi("Record_Type_Parent")] == "Document_Categories" and
        r[_fi("category_name")] == cat_name
    )]
    # Renumber remaining categories
    remaining_cats = _sorted_cats(values)
    for i, r in enumerate(remaining_cats):
        r[_fi("category_index_pos")] = i + 1

    _save_doc_schema(doc_name, values)
    print(f"[*] Category deleted: '{cat_name}'. Positions renumbered.")

def cmd_doc_cat_sel(idx_str):
    """Print the category name at index — used by Flask or scripting to resolve IDX→name."""
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    cats = _sorted_cats(doc.get("Values", []))
    try:
        cat_row = cats[int(idx_str) - 1]
        print(cat_row[_fi("category_name")])
    except (IndexError, ValueError):
        print(f"Error: Category index {idx_str} not found.")

def _shift_cat_pos(idx_str, direction):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    try:
        idx = int(idx_str) - 1
    except ValueError:
        print("Error: Index must be an integer.")
        return

    if idx < 0 or idx >= len(cats):
        print(f"Error: Category index {idx_str} out of range.")
        return

    swap_idx = idx + direction
    if swap_idx < 0 or swap_idx >= len(cats):
        print("Error: Already at boundary — cannot move further.")
        return

    # Swap positions
    pos_a = cats[idx][_fi("category_index_pos")]
    pos_b = cats[swap_idx][_fi("category_index_pos")]
    cats[idx][_fi("category_index_pos")]      = pos_b
    cats[swap_idx][_fi("category_index_pos")] = pos_a

    _save_doc_schema(doc_name, values)
    direction_label = "up" if direction == -1 else "down"
    print(f"[*] Category '{cats[idx][_fi('category_name')]}' moved {direction_label}.")

def cmd_doc_cat_inc_idx_pos(idx_str):
    _shift_cat_pos(idx_str, -1)  # lower index = earlier in doc = "up"

def cmd_doc_cat_dec_idx_pos(idx_str):
    _shift_cat_pos(idx_str, +1)

# ── Chunk Management ───────────────────────────────────────────────────────────

def cmd_doc_chunk_list():
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    if not cats:
        print(f"No categories yet in '{doc_name}'. Add one with --doc-cat-add.")
        return

    print(f"\nChunks in: {doc_name}")
    for cat_row in cats:
        cat_name = cat_row[_fi("category_name")]
        chunks   = _sorted_chunks_in_cat(values, cat_name)
        print(f"\n  [{cat_row[_fi('category_index_pos')]}] {cat_name}  ({len(chunks)} chunk(s))")
        print(f"  {'Pos':<5} {'ID':<10} {'Label'}")
        print(f"  {'─'*45}")
        for c in chunks:
            preview = (c[_fi("chunk_content")] or "")[:50].replace("\n", " ")
            if len(c[_fi("chunk_content")] or "") > 50:
                preview += "…"
            print(f"  {c[_fi('chunk_index_pos')]:<5} {c[_fi('chunk_id')]:<10} {c[_fi('chunk_label')]}")
            print(f"       {preview}")

def cmd_doc_chunk_sel(chunk_id):
    """Print full content of a chunk by ID."""
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    chunks = _get_chunks(doc.get("Values", []))
    for c in chunks:
        if c[_fi("chunk_id")] == chunk_id:
            print(f"\n── Chunk: {c[_fi('chunk_label')]} [{chunk_id}] ──")
            print(f"   Category: {c[_fi('parent_category')]}")
            print(f"   Position: {c[_fi('chunk_index_pos')]}")
            print("─" * 50)
            print(c[_fi("chunk_content")] or "(empty)")
            print("─" * 50)
            return
    print(f"Error: Chunk ID '{chunk_id}' not found.")

def cmd_doc_chunk_add(category_name, label=None):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    # Verify category exists
    cat_names = [r[_fi("category_name")] for r in _get_categories(values)]
    if category_name not in cat_names:
        print(f"Error: Category '{category_name}' not found. Run --doc-cat-list.")
        return

    if _assert_not_locked(doc_name, "--doc-chunk-add"):
        return

    existing_chunks_in_cat = _sorted_chunks_in_cat(values, category_name)
    next_pos  = max((c[_fi("chunk_index_pos")] or 0 for c in existing_chunks_in_cat), default=0) + 1
    chunk_id  = short_id()
    chunk_label = label or f"Chunk_{next_pos}"

    values.append(_chunk_row(chunk_id, chunk_label, "", category_name, next_pos,
                             chunk_tags="", chunk_status=CHUNK_STATUS_DEFAULT))
    _save_doc_schema(doc_name, values)
    print(f"[*] Chunk added: '{chunk_label}' [{chunk_id}] → category '{category_name}' at position {next_pos}")
    print(f"    Use --doc-chunk-write {chunk_id} to write content.")

def cmd_doc_chunk_write(chunk_id, content_or_file):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    # Resolve content — guard against OSError ENAMETOOLONG on Android when
    # content_or_file is chunk body text rather than a file path.
    # Only attempt the filesystem check if the string is short enough to be a
    # valid path (≤4096 chars) and contains no newlines.
    content = content_or_file
    content_could_be_filepath = (
        len(content_or_file) <= 4096
        and "\n" not in content_or_file
        and "\r" not in content_or_file
    )
    if content_could_be_filepath:
        maybe_path = Path(content_or_file)
        try:
            if maybe_path.exists() and maybe_path.is_file():
                content = maybe_path.read_text(encoding="utf-8")
                print(f"[*] Reading content from file: {maybe_path}")
        except OSError:
            pass  # Not a valid path; treat content_or_file as literal content

    _doc_chunk_write_with_diff(doc_name, chunk_id, content)
    preview = content[:60].replace("\n", " ")
    print(f"[*] Chunk '{chunk_id}' written ({len(content)} chars): {preview}…")

def cmd_doc_chunk_del(chunk_id):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    if _assert_not_locked(doc_name, "--doc-chunk-del"):
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    original_len = len(values)
    values = [r for r in values if not (
        r[_fi("Record_Type_Parent")] == "Chunks" and r[_fi("chunk_id")] == chunk_id
    )]

    if len(values) == original_len:
        print(f"Error: Chunk ID '{chunk_id}' not found.")
        return

    _save_doc_schema(doc_name, values)
    print(f"[*] Chunk '{chunk_id}' deleted.")

def cmd_doc_chunk_set_parent_cat(chunk_id, new_category):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    # Verify target category exists
    cat_names = [r[_fi("category_name")] for r in _get_categories(values)]
    if new_category not in cat_names:
        print(f"Error: Category '{new_category}' not found.")
        return

    for i, r in enumerate(values):
        if r[_fi("Record_Type_Parent")] == "Chunks" and r[_fi("chunk_id")] == chunk_id:
            old_cat = values[i][_fi("parent_category")]
            values[i][_fi("parent_category")] = new_category
            _save_doc_schema(doc_name, values)
            print(f"[*] Chunk '{chunk_id}' moved: '{old_cat}' → '{new_category}'")
            return

    print(f"Error: Chunk ID '{chunk_id}' not found.")

def _shift_chunk_pos(chunk_id, direction):
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    # Find target chunk
    target_idx = None
    for i, r in enumerate(values):
        if r[_fi("Record_Type_Parent")] == "Chunks" and r[_fi("chunk_id")] == chunk_id:
            target_idx = i
            break
    if target_idx is None:
        print(f"Error: Chunk ID '{chunk_id}' not found.")
        return

    cat_name = values[target_idx][_fi("parent_category")]
    siblings = _sorted_chunks_in_cat(values, cat_name)

    sib_ids  = [s[_fi("chunk_id")] for s in siblings]
    sib_pos  = sib_ids.index(chunk_id)
    swap_pos = sib_pos + direction

    if swap_pos < 0 or swap_pos >= len(siblings):
        print("Error: Already at boundary within category.")
        return

    swap_chunk_id = sib_ids[swap_pos]

    # Capture original positions BEFORE mutating anything. `siblings` holds
    # references to the same row objects as `values` (not copies), so reading
    # from `siblings` mid-loop after one of the two rows has already been
    # mutated returns the NEW value instead of the original — corrupting the
    # swap (both rows could end up with the same position). Snapshot first.
    original_target_pos = siblings[sib_pos][_fi("chunk_index_pos")]
    original_swap_pos    = siblings[swap_pos][_fi("chunk_index_pos")]

    # Swap index positions
    for i, r in enumerate(values):
        if r[_fi("Record_Type_Parent")] == "Chunks":
            if r[_fi("chunk_id")] == chunk_id:
                values[i][_fi("chunk_index_pos")] = original_swap_pos
            elif r[_fi("chunk_id")] == swap_chunk_id:
                values[i][_fi("chunk_index_pos")] = original_target_pos

    _save_doc_schema(doc_name, values)
    direction_label = "up" if direction == -1 else "down"
    print(f"[*] Chunk '{chunk_id}' moved {direction_label} within '{cat_name}'.")

def cmd_doc_chunk_inc_idx_pos(chunk_id):
    _shift_chunk_pos(chunk_id, -1)

def cmd_doc_chunk_dec_idx_pos(chunk_id):
    _shift_chunk_pos(chunk_id, +1)

# ── Mount / Commit / Discard ───────────────────────────────────────────────────

def cmd_doc_mount():
    doc_name = _require_active_doc()
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Error: '{doc_name}' is already mounted.")
        print(f"       Run --doc-commit or --doc-discard first.")
        return

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    mounted_dir = _doc_mounted_dir(doc_name)
    # Clear and recreate Mounted/
    if mounted_dir.exists():
        shutil.rmtree(mounted_dir)
    mounted_dir.mkdir(parents=True, exist_ok=True)

    cats         = _sorted_cats(values)
    file_sizes   = {}
    total_files  = 0

    for cat_row in cats:
        cat_name   = cat_row[_fi("category_name")]
        cat_dir    = mounted_dir / cat_name
        cat_dir.mkdir(parents=True, exist_ok=True)
        chunks     = _sorted_chunks_in_cat(values, cat_name)

        for chunk_row in chunks:
            chunk_id      = chunk_row[_fi("chunk_id")]
            chunk_label   = chunk_row[_fi("chunk_label")]
            chunk_content = chunk_row[_fi("chunk_content")] or ""
            filename      = _chunk_filename(chunk_label, chunk_id)
            chunk_file    = cat_dir / filename
            chunk_file.write_text(chunk_content, encoding="utf-8")
            file_sizes[f"{cat_name}/{filename}"] = len(chunk_content)
            total_files += 1
            print(f"  [>] {cat_name}/{filename}")

    # Write mount state
    state[doc_name] = {
        "mounted_at": now_unix(),
        "file_sizes": file_sizes,
    }
    _save_mount_state(state)
    print(f"\n[*] Mounted {total_files} chunk file(s) → {mounted_dir}")
    print(f"[*] Mount will auto-discard after {MOUNT_TTL_SECONDS // 60} minutes of inactivity.")
    print(f"[*] Run --doc-commit to save changes or --doc-discard to abandon.")

def cmd_doc_commit():
    doc_name = _require_active_doc()
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name not in state:
        print(f"Error: '{doc_name}' is not currently mounted.")
        return

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    mounted_dir = _doc_mounted_dir(doc_name)
    if not mounted_dir.exists():
        print(f"Error: Mounted directory not found at {mounted_dir}")
        return

    updated_count = 0
    errors        = []

    chunks = _get_chunks(values)
    for i, r in enumerate(values):
        if r[_fi("Record_Type_Parent")] != "Chunks":
            continue

        chunk_id    = r[_fi("chunk_id")]
        chunk_label = r[_fi("chunk_label")]
        cat_name    = r[_fi("parent_category")]
        filename    = _chunk_filename(chunk_label, chunk_id)
        chunk_file  = mounted_dir / cat_name / filename

        if not chunk_file.exists():
            errors.append(f"Missing file: {cat_name}/{filename} for chunk '{chunk_id}'")
            continue

        new_content = chunk_file.read_text(encoding="utf-8")
        if new_content != (r[_fi("chunk_content")] or ""):
            values[i][_fi("chunk_content")] = new_content
            updated_count += 1

    if errors:
        print(f"[!] {len(errors)} error(s) during commit:")
        for e in errors:
            print(f"    - {e}")
        print("Commit aborted. Fix errors and retry.")
        return

    _save_doc_schema(doc_name, values)

    # Clean up mounted files and state
    shutil.rmtree(mounted_dir)
    mounted_dir.mkdir(parents=True, exist_ok=True)
    del state[doc_name]
    _save_mount_state(state)

    print(f"[SUCCESS] Committed {updated_count} changed chunk(s) back to schema.")
    print(f"[*] Mounted files cleared.")

def cmd_doc_discard():
    doc_name = _require_active_doc()
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name not in state:
        print(f"Error: '{doc_name}' is not currently mounted.")
        return

    _discard_mount_files(doc_name)
    del state[doc_name]
    _save_mount_state(state)
    print(f"[*] Mounted files for '{doc_name}' discarded. Schema unchanged.")

# ── Compile ────────────────────────────────────────────────────────────────────

def cmd_doc_compile():
    doc_name = _require_active_doc()
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Warning: '{doc_name}' is currently mounted with uncommitted changes.")
        print(f"         Run --doc-commit first, or --doc-discard to abandon.")
        return

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    if not cats:
        print(f"No categories in '{doc_name}'. Nothing to compile.")
        return

    lines = []

    # ── TOC ───────────────────────────────────────────────────────────────────
    lines.append(f"# {doc_name.replace('_', ' ')}")
    lines.append(f"*Compiled: {get_timestamp()}*")
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")
    for cat_row in cats:
        cat_name = cat_row[_fi("category_name")]
        anchor   = cat_name.lower().replace(" ", "-").replace("_", "-")
        lines.append(f"- [{cat_name}](#{anchor})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Body ──────────────────────────────────────────────────────────────────
    total_chunks = 0
    for cat_row in cats:
        cat_name = cat_row[_fi("category_name")]
        chunks   = _sorted_chunks_in_cat(values, cat_name)

        lines.append(f"## {cat_name}")
        lines.append("")

        if not chunks:
            lines.append("*(No chunks in this category.)*")
            lines.append("")
            continue

        for chunk_row in chunks:
            chunk_status = chunk_row[_fi("chunk_status")] or CHUNK_STATUS_DEFAULT
            if chunk_status == "skip":
                continue
            content = chunk_row[_fi("chunk_content")] or ""
            if content.strip():
                lines.append(content.strip())
                lines.append("")
                total_chunks += 1
            else:
                label = chunk_row[_fi("chunk_label")]
                lines.append(f"*[Empty chunk: {label}]*")
                lines.append("")

        lines.append("---")
        lines.append("")

    compiled_text = "\n".join(lines)
    compiled_dir  = _doc_compiled_dir(doc_name)
    out_file      = compiled_dir / f"{doc_name}.md"
    out_file.write_text(compiled_text, encoding="utf-8")

    print(f"[SUCCESS] Compiled {total_chunks} chunk(s) across {len(cats)} category/categories.")
    print(f"          Output: {out_file}")



# ═══════════════════════════════════════════════════════════════════════════════
# SECTION D — TIER 1 FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_doc_find(search_text):
    """Search all chunk content in the active doc for search_text. Prints matches."""
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values       = doc.get("Values", [])
    search_lower = search_text.lower()
    matches      = 0

    print(f"\nSearching '{doc_name}' for: {search_text}")
    print("─" * 60)

    for cat_row in _sorted_cats(values):
        cat_name = cat_row[_fi("category_name")]
        for chunk_row in _sorted_chunks_in_cat(values, cat_name):
            content = chunk_row[_fi("chunk_content")] or ""
            if search_lower in content.lower():
                chunk_label = chunk_row[_fi("chunk_label")]
                chunk_id    = chunk_row[_fi("chunk_id")]
                chunk_pos   = chunk_row[_fi("chunk_index_pos")]
                # Print matching lines with context
                for line_num, line in enumerate(content.splitlines(), 1):
                    if search_lower in line.lower():
                        print(f"  [{cat_name}] pos {chunk_pos} · {chunk_label} [{chunk_id}]")
                        print(f"  Line {line_num}: {line.strip()}")
                        print()
                        matches += 1

    if matches == 0:
        print(f"  No matches found for '{search_text}'.")
    else:
        print(f"─ {matches} match(es) found.")


def cmd_doc_stats():
    """Print word count and structural stats for the active doc."""
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)
    chunks = _get_chunks(values)

    total_chars  = 0
    total_words  = 0
    empty_chunks = []
    chunk_sizes  = []

    for chunk_row in chunks:
        content      = chunk_row[_fi("chunk_content")] or ""
        char_count   = len(content)
        word_count   = len(content.split()) if content.strip() else 0
        total_chars += char_count
        total_words += word_count
        chunk_sizes.append((char_count, chunk_row[_fi("chunk_label")]))
        if not content.strip():
            empty_chunks.append(chunk_row[_fi("chunk_label")])

    longest  = max(chunk_sizes, key=lambda x: x[0]) if chunk_sizes else (0, "—")
    shortest = min(chunk_sizes, key=lambda x: x[0]) if chunk_sizes else (0, "—")

    print(f"\n── Stats: {doc_name} ──")
    print(f"  Categories : {len(cats)}")
    print(f"  Chunks     : {len(chunks)}")
    print(f"  Empty      : {len(empty_chunks)}")
    print(f"  Total chars: {total_chars:,}")
    print(f"  Total words: {total_words:,}")
    print(f"  Longest    : {longest[1]} ({longest[0]:,} chars)")
    print(f"  Shortest   : {shortest[1]} ({shortest[0]:,} chars)")
    if empty_chunks:
        print(f"  Empty chunks: {', '.join(empty_chunks)}")


def _doc_chunk_write_with_diff(doc_name, chunk_id, new_content):
    """Write content to chunk. Prints unified diff of old vs new. Returns True on success."""
    doc = _load_doc_schema(doc_name)
    if not doc:
        return False
    values = doc.get("Values", [])

    for i, row in enumerate(values):
        if row[_fi("Record_Type_Parent")] == "Chunks" and row[_fi("chunk_id")] == chunk_id:
            old_content = row[_fi("chunk_content")] or ""
            if old_content != new_content:
                diff = list(difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile="before",
                    tofile="after",
                    n=2
                ))
                if diff:
                    print("[*] Content diff:")
                    for diff_line in diff[:40]:   # cap at 40 lines
                        print("   " + diff_line.rstrip())
                    if len(diff) > 40:
                        print(f"   ... ({len(diff) - 40} more lines)")
            values[i][_fi("chunk_content")] = new_content
            _save_doc_schema(doc_name, values)
            return True

    print(f"Error: Chunk ID '{chunk_id}' not found.")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION E — TIER 2 FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Tags ──────────────────────────────────────────────────────────────────────

def cmd_doc_chunk_tag(chunk_id, tags_str):
    """Set tags on a chunk. tags_str is comma-separated. Pass empty string to clear."""
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    for i, row in enumerate(values):
        if row[_fi("Record_Type_Parent")] == "Chunks" and row[_fi("chunk_id")] == chunk_id:
            old_tags = values[i][_fi("chunk_tags")] or ""
            values[i][_fi("chunk_tags")] = tags_str.strip()
            _save_doc_schema(doc_name, values)
            print(f"[*] Chunk '{chunk_id}' tags: '{old_tags}' → '{tags_str.strip()}'")
            return

    print(f"Error: Chunk ID '{chunk_id}' not found.")


def cmd_doc_chunk_rename_label(chunk_id, new_label):
    """Rename (relabel) an existing chunk. Does not touch content, tags, or status."""
    new_label = new_label.strip()
    if not new_label:
        print("Error: New label cannot be empty.")
        return
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    for i, row in enumerate(values):
        if row[_fi("Record_Type_Parent")] == "Chunks" and row[_fi("chunk_id")] == chunk_id:
            old_label = values[i][_fi("chunk_label")]
            values[i][_fi("chunk_label")] = new_label
            _save_doc_schema(doc_name, values)
            print(f"[*] Chunk '{chunk_id}' relabeled: '{old_label}' → '{new_label}'")
            return

    print(f"Error: Chunk ID '{chunk_id}' not found.")


def cmd_doc_chunk_set_status(chunk_id, status):
    """Set status on a chunk: draft | review | final | skip"""
    status = status.strip().lower()
    if status not in CHUNK_STATUS_VALUES:
        print(f"Error: Invalid status '{status}'. Valid: {', '.join(CHUNK_STATUS_VALUES)}")
        return
    doc_name = _require_active_doc()
    if not doc_name:
        return
    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    for i, row in enumerate(values):
        if row[_fi("Record_Type_Parent")] == "Chunks" and row[_fi("chunk_id")] == chunk_id:
            old_status = values[i][_fi("chunk_status")] or CHUNK_STATUS_DEFAULT
            values[i][_fi("chunk_status")] = status
            _save_doc_schema(doc_name, values)
            print(f"[*] Chunk '{chunk_id}' status: '{old_status}' → '{status}'")
            return

    print(f"Error: Chunk ID '{chunk_id}' not found.")


def cmd_doc_compile_filtered(filter_tag=None, filter_status=None):
    """
    Compile only chunks matching a tag and/or status filter.
    Outputs to Compiled/<doc_name>_filtered_<tag|status>.md
    Chunks with status 'skip' are always excluded.
    """
    doc_name = _require_active_doc()
    if not doc_name:
        return
    if not filter_tag and not filter_status:
        print("Error: Provide --tag, --status, or both to filter by.")
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Warning: '{doc_name}' is currently mounted. Commit first.")
        return

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    lines = []
    suffix_parts = []
    if filter_tag:
        suffix_parts.append(filter_tag)
    if filter_status:
        suffix_parts.append(filter_status)
    suffix = "_".join(suffix_parts)

    lines.append(f"# {doc_name.replace('_', ' ')} (filtered: {suffix})")
    lines.append(f"*Compiled: {get_timestamp()}*")
    lines.append("")

    total_included = 0
    total_skipped  = 0

    for cat_row in cats:
        cat_name       = cat_row[_fi("category_name")]
        chunks_in_cat  = _sorted_chunks_in_cat(values, cat_name)
        section_lines  = []

        for chunk_row in chunks_in_cat:
            chunk_status = chunk_row[_fi("chunk_status")] or CHUNK_STATUS_DEFAULT
            chunk_tags   = chunk_row[_fi("chunk_tags")] or ""
            tag_list     = [t.strip() for t in chunk_tags.split(",") if t.strip()]

            # Always skip status=skip
            if chunk_status == "skip":
                total_skipped += 1
                continue
            # Tag filter
            if filter_tag and filter_tag not in tag_list:
                total_skipped += 1
                continue
            # Status filter
            if filter_status and chunk_status != filter_status:
                total_skipped += 1
                continue

            content = chunk_row[_fi("chunk_content")] or ""
            if content.strip():
                section_lines.append(content.strip())
                section_lines.append("")
                total_included += 1

        if section_lines:
            lines.append(f"## {cat_name}")
            lines.append("")
            lines.extend(section_lines)
            lines.append("---")
            lines.append("")

    compiled_text = "\n".join(lines)
    compiled_dir  = _doc_compiled_dir(doc_name)
    out_file      = compiled_dir / f"{doc_name}_filtered_{suffix}.md"
    out_file.write_text(compiled_text, encoding="utf-8")

    print(f"[SUCCESS] Filtered compile: {total_included} included, {total_skipped} skipped.")
    print(f"          Output: {out_file}")


# ── Multi-doc merge ───────────────────────────────────────────────────────────

def cmd_doc_merge(doc_idx_list_str, output_name):
    """
    Merge compiled outputs from multiple docs (by index, comma-separated) into one file.
    Triggers compile on each source doc if compiled output is missing.
    Output: Document_Project/<output_name>/Compiled/<output_name>_merged.md
    """
    idx_parts = [p.strip() for p in doc_idx_list_str.split(",") if p.strip()]
    if not idx_parts:
        print("Error: Provide at least one doc index.")
        return

    docs       = _list_doc_names()
    source_docs = []
    for idx_str in idx_parts:
        try:
            name = docs[int(idx_str) - 1]
            source_docs.append(name)
        except (IndexError, ValueError):
            print(f"Error: Doc index '{idx_str}' not found.")
            return

    output_name = safe_name(output_name)
    out_dir     = DOC_PROJECT_DIR / output_name / "Compiled"
    out_dir.mkdir(parents=True, exist_ok=True)

    merged_lines = [f"# {output_name.replace('_', ' ')} — Merged"]
    merged_lines.append(f"*Sources: {', '.join(source_docs)}*")
    merged_lines.append(f"*Merged: {get_timestamp()}*")
    merged_lines.append("")
    merged_lines.append("---")
    merged_lines.append("")

    for source_name in source_docs:
        compiled_file = _doc_compiled_dir(source_name) / f"{source_name}.md"
        if not compiled_file.exists():
            print(f"[*] No compiled output for '{source_name}' — compiling now...")
            prev_active = _get_active_doc()
            _set_active_doc(source_name)
            cmd_doc_compile()
            if prev_active:
                _set_active_doc(prev_active)

        if compiled_file.exists():
            source_text = compiled_file.read_text(encoding="utf-8")
            merged_lines.append(f"<!-- Source: {source_name} -->")
            merged_lines.append(source_text.strip())
            merged_lines.append("")
            merged_lines.append("---")
            merged_lines.append("")
            print(f"  [+] Merged: {source_name}")
        else:
            print(f"  [!] Could not compile '{source_name}' — skipped.")

    out_file = out_dir / f"{output_name}_merged.md"
    out_file.write_text("\n".join(merged_lines), encoding="utf-8")
    print(f"[SUCCESS] Merged {len(source_docs)} doc(s) → {out_file}")


# ── Import from file ──────────────────────────────────────────────────────────

def cmd_doc_import_file(file_path_str, delimiter, category_name, label_prefix=None):
    """
    Split an existing text file on delimiter and create one chunk per segment.
    Appends chunks to category_name in the active doc.
    """
    doc_name = _require_active_doc()
    if not doc_name:
        return

    input_file = Path(file_path_str).resolve()
    if not input_file.exists():
        print(f"Error: File not found: {file_path_str}")
        return

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])

    cat_names = [r[_fi("category_name")] for r in _get_categories(values)]
    if category_name not in cat_names:
        print(f"Error: Category '{category_name}' not found. Add it first.")
        return

    raw_text = input_file.read_text(encoding="utf-8")

    # Resolve delimiter escape sequences
    resolved_delimiter = delimiter.replace("\n", "\n").replace("\t", "\t")
    if resolved_delimiter == "\n\n":
        segments = [s.strip() for s in raw_text.split("\n\n") if s.strip()]
    else:
        segments = [s.strip() for s in raw_text.split(resolved_delimiter) if s.strip()]

    if not segments:
        print(f"Error: No segments found using delimiter '{delimiter}'.")
        return

    existing_in_cat = _sorted_chunks_in_cat(values, category_name)
    next_pos        = max((c[_fi("chunk_index_pos")] or 0 for c in existing_in_cat), default=0) + 1
    prefix          = label_prefix or input_file.stem

    created = 0
    for i, segment in enumerate(segments):
        chunk_id    = short_id()
        chunk_label = f"{prefix}_{i + 1}"
        values.append(_chunk_row(chunk_id, chunk_label, segment, category_name, next_pos + i))
        print(f"  [+] Chunk {next_pos + i}: {chunk_label} ({len(segment)} chars)")
        created += 1

    _save_doc_schema(doc_name, values)
    print(f"[SUCCESS] Imported {created} chunk(s) from '{input_file.name}' into '{category_name}'.")


# ── Doc locking ───────────────────────────────────────────────────────────────

def _get_doc_lock_state(doc_name):
    """Check if the doc-level lock file exists."""
    return (DOC_PROJECT_DIR / doc_name / ".locked").exists()

def cmd_doc_lock(idx_str=None):
    """Lock the active (or indexed) doc — blocks add/delete/reorder chunk operations."""
    doc_name = _resolve_doc_by_idx(idx_str) if idx_str else _require_active_doc()
    if not doc_name:
        return
    lock_file = DOC_PROJECT_DIR / doc_name / ".locked"
    lock_file.touch()
    print(f"[*] Doc '{doc_name}' locked. Compile still allowed. Use --doc-unlock to reverse.")

def cmd_doc_unlock(idx_str=None):
    """Unlock the active (or indexed) doc."""
    doc_name = _resolve_doc_by_idx(idx_str) if idx_str else _require_active_doc()
    if not doc_name:
        return
    lock_file = DOC_PROJECT_DIR / doc_name / ".locked"
    if lock_file.exists():
        lock_file.unlink()
        print(f"[*] Doc '{doc_name}' unlocked.")
    else:
        print(f"[*] Doc '{doc_name}' was not locked.")

def _assert_not_locked(doc_name, operation="This operation"):
    """Returns True (blocked) if doc is locked, prints error. Returns False if safe to proceed."""
    if _get_doc_lock_state(doc_name):
        print(f"Error: Doc '{doc_name}' is locked. {operation} is blocked. Run --doc-unlock first.")
        return True
    return False


# ── Snapshots ─────────────────────────────────────────────────────────────────

def cmd_doc_snapshot():
    """
    Take a timestamped zip snapshot of Schema/ and Compiled/ for the active doc.
    Saved to: Document_Project/<doc_name>/Snapshots/<doc_name>_snapshot_<timestamp>.zip
    """
    doc_name = _require_active_doc()
    if not doc_name:
        return

    snapshot_dir = DOC_PROJECT_DIR / doc_name / "Snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_name = f"{doc_name}_snapshot_{ts}.zip"
    zip_path = snapshot_dir / zip_name

    doc_root = DOC_PROJECT_DIR / doc_name
    included = 0

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in ("Schema", "Compiled"):
            folder_path = doc_root / folder
            if folder_path.exists():
                for file_path in folder_path.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(doc_root)
                        zf.write(str(file_path), str(arcname))
                        included += 1

    print(f"[SUCCESS] Snapshot saved: {zip_path}")
    print(f"          {included} file(s) archived.")


def cmd_doc_restore_snapshot(snapshot_file_str):
    """
    Restore a snapshot zip into the active doc's Schema/ and Compiled/ directories.
    WARNING: overwrites current schema.
    """
    doc_name = _require_active_doc()
    if not doc_name:
        return

    snapshot_path = Path(snapshot_file_str).resolve()
    if not snapshot_path.exists():
        print(f"Error: Snapshot file not found: {snapshot_file_str}")
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Error: '{doc_name}' is currently mounted. Commit or discard before restoring.")
        return

    doc_root = DOC_PROJECT_DIR / doc_name

    with zipfile.ZipFile(str(snapshot_path), "r") as zf:
        zf.extractall(str(doc_root))

    print(f"[SUCCESS] Snapshot restored from: {snapshot_path}")
    print(f"          Extracted into: {doc_root}")

# ── Doc Project Utilities — duplicate, rename, export ─────────────────────────

def _resolve_doc_by_idx(idx_str):
    """Resolve a doc index string to a doc name. Returns None on failure."""
    docs = _list_doc_names()
    try:
        return docs[int(idx_str) - 1]
    except (IndexError, ValueError):
        print(f"Error: Document index {idx_str} not found. Run --doc-list first.")
        return None

def cmd_duplicate_doc(idx_str, new_name):
    source_name = _resolve_doc_by_idx(idx_str)
    if not source_name:
        return

    new_name = safe_name(new_name)
    new_dir  = DOC_PROJECT_DIR / new_name

    if new_dir.exists():
        print(f"Error: A document project named '{new_name}' already exists.")
        return

    source_dir = DOC_PROJECT_DIR / source_name

    # Block duplicate while source is mounted — mounted files would carry over
    state = _load_mount_state()
    if source_name in state:
        print(f"Error: '{source_name}' is currently mounted. Commit or discard before duplicating.")
        return

    shutil.copytree(str(source_dir), str(new_dir))

    # The Mounted/ dir in the copy should always start empty
    new_mounted = new_dir / "Mounted"
    if new_mounted.exists():
        shutil.rmtree(new_mounted)
    new_mounted.mkdir(parents=True, exist_ok=True)

    # Rename the schema file inside Schema/ to match the new doc name
    old_schema_file = new_dir / "Schema" / f"{source_name}.104db.bejson"
    new_schema_file = new_dir / "Schema" / f"{new_name}.104db.bejson"
    if old_schema_file.exists():
        old_schema_file.rename(new_schema_file)

    # Rename compiled output file if it exists
    old_compiled = new_dir / "Compiled" / f"{source_name}.md"
    new_compiled  = new_dir / "Compiled" / f"{new_name}.md"
    if old_compiled.exists():
        old_compiled.rename(new_compiled)

    _set_active_doc(new_name)
    print(f"[*] Duplicated '{source_name}' → '{new_name}'")
    print(f"[*] Active doc set to: {new_name}")


def cmd_rename_doc(idx_str, new_name):
    source_name = _resolve_doc_by_idx(idx_str)
    if not source_name:
        return

    new_name = safe_name(new_name)

    if source_name == new_name:
        print("Error: New name is the same as the current name.")
        return

    new_dir = DOC_PROJECT_DIR / new_name
    if new_dir.exists():
        print(f"Error: A document project named '{new_name}' already exists.")
        return

    state = _load_mount_state()
    if source_name in state:
        print(f"Error: '{source_name}' is currently mounted. Commit or discard before renaming.")
        return

    source_dir = DOC_PROJECT_DIR / source_name

    # Rename the directory
    source_dir.rename(new_dir)

    # Rename the schema file inside Schema/
    old_schema_file = new_dir / "Schema" / f"{source_name}.104db.bejson"
    new_schema_file = new_dir / "Schema" / f"{new_name}.104db.bejson"
    if old_schema_file.exists():
        old_schema_file.rename(new_schema_file)

    # Rename compiled output file if it exists
    old_compiled = new_dir / "Compiled" / f"{source_name}.md"
    new_compiled  = new_dir / "Compiled" / f"{new_name}.md"
    if old_compiled.exists():
        old_compiled.rename(new_compiled)

    # Update active doc pointer if it was pointing at the renamed doc
    active = _get_active_doc()
    if active == source_name:
        _set_active_doc(new_name)
        print(f"[*] Active doc updated to: {new_name}")

    print(f"[*] Renamed '{source_name}' → '{new_name}'")


def cmd_doc_archive_delete(idx_str):
    """
    Archive a managed document project (full zip of Schema/Compiled/Mounted/Snapshots)
    to Document_Project_Archive/, then permanently remove it from Document_Project/,
    clearing any active-doc pointer or mount-state entry that referenced it.
    """
    doc_name = _resolve_doc_by_idx(idx_str)
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Error: '{doc_name}' is currently mounted. Commit or discard before deleting.")
        return

    doc_root = DOC_PROJECT_DIR / doc_name

    archive_dir = BASE_DIR / "Document_Project_Archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = archive_dir / f"{doc_name}_archived_{ts}.zip"

    included = 0
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in doc_root.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(doc_root)
                zf.write(str(file_path), str(arcname))
                included += 1

    shutil.rmtree(str(doc_root))

    # Clear active-doc pointer if it pointed at the now-deleted doc
    if _get_active_doc() == doc_name:
        ACTIVE_DOC_FILE.write_text("", encoding="utf-8")
        print(f"[*] Active doc cleared (was '{doc_name}').")

    # Belt-and-suspenders: strip any stale mount-state entry
    if doc_name in state:
        del state[doc_name]
        _save_mount_state(state)

    print(f"[SUCCESS] '{doc_name}' archived to: {zip_path} ({included} file(s))")
    print(f"          Removed from Document_Project/.")


def cmd_export_doc(idx_str, export_format):
    """
    Export a document project's compiled content to a chosen format.
    Formats:
      md   — Markdown (same as compiled output, copy to cwd)
      txt  — Plain text, section headers as === underlines, no Markdown syntax
      json — JSON array, one object per chunk: {category, label, position, content}
    The exported file is placed in the doc's Compiled/ directory alongside the .md.
    """
    VALID_FORMATS = ("md", "txt", "json")

    export_format = export_format.strip().lower()
    if export_format not in VALID_FORMATS:
        print(f"Error: Unknown format '{export_format}'. Valid options: {', '.join(VALID_FORMATS)}")
        return

    doc_name = _resolve_doc_by_idx(idx_str)
    if not doc_name:
        return

    state = _load_mount_state()
    if doc_name in state:
        print(f"Warning: '{doc_name}' has uncommitted mounted changes — export will reflect last committed schema state.")

    doc = _load_doc_schema(doc_name)
    if not doc:
        return
    values = doc.get("Values", [])
    cats   = _sorted_cats(values)

    if not cats:
        print(f"No categories in '{doc_name}'. Nothing to export.")
        return

    compiled_dir = _doc_compiled_dir(doc_name)
    compiled_dir.mkdir(parents=True, exist_ok=True)

    if export_format == "md":
        # Re-use the existing .md if present, otherwise compile fresh to temp
        source_md = compiled_dir / f"{doc_name}.md"
        if not source_md.exists():
            print(f"[*] No compiled .md found — running compile first.")
            cmd_doc_compile()
        out_file = compiled_dir / f"{doc_name}_export.md"
        shutil.copy2(str(source_md), str(out_file))
        print(f"[SUCCESS] Exported Markdown → {out_file}")

    elif export_format == "txt":
        lines = []
        title = doc_name.replace("_", " ")
        lines.append(title)
        lines.append("=" * len(title))
        lines.append(f"Exported: {get_timestamp()}")
        lines.append("")

        # Plain-text TOC
        lines.append("TABLE OF CONTENTS")
        lines.append("-" * 40)
        for i, cat_row in enumerate(cats, 1):
            lines.append(f"  {i}. {cat_row[_fi('category_name')]}")
        lines.append("")

        for cat_row in cats:
            cat_name = cat_row[_fi("category_name")]
            chunks   = _sorted_chunks_in_cat(values, cat_name)
            lines.append("")
            lines.append(cat_name)
            lines.append("=" * len(cat_name))
            lines.append("")
            for chunk_row in chunks:
                content = chunk_row[_fi("chunk_content")] or ""
                if content.strip():
                    lines.append(content.strip())
                    lines.append("")

        out_file = compiled_dir / f"{doc_name}_export.txt"
        out_file.write_text("\n".join(lines), encoding="utf-8")
        print(f"[SUCCESS] Exported plain text → {out_file}")

    elif export_format == "json":
        records = []
        for cat_row in cats:
            cat_name = cat_row[_fi("category_name")]
            chunks   = _sorted_chunks_in_cat(values, cat_name)
            for chunk_row in chunks:
                records.append({
                    "category":        cat_name,
                    "category_pos":    cat_row[_fi("category_index_pos")],
                    "chunk_id":        chunk_row[_fi("chunk_id")],
                    "chunk_label":     chunk_row[_fi("chunk_label")],
                    "chunk_pos":       chunk_row[_fi("chunk_index_pos")],
                    "chunk_content":   chunk_row[_fi("chunk_content")] or "",
                })
        out_file = compiled_dir / f"{doc_name}_export.json"
        out_file.write_text(
            json.dumps({"doc_name": doc_name, "exported": get_timestamp(), "chunks": records}, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"[SUCCESS] Exported JSON ({len(records)} chunk(s)) → {out_file}")

# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # Always run stale mount cleanup on startup
    cleanup_stale_mounts()

    parser = argparse.ArgumentParser(
        description="Doc_Chunker v2.2.0 — Document Chunker & Manager",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)

    # ── MODE 1: Project chunker (original, unchanged) ──────────────────────────
    group.add_argument("--chunk",              metavar="DIR",           help="Chunk a directory into BEJSON 104db")
    group.add_argument("--chunk-index",        metavar="ID",            help="Chunk a registered project by numeric ID")
    group.add_argument("--unchunk",            metavar="FILE",          help="Unchunk a BEJSON 104db file")
    group.add_argument("--unchunk-index",      metavar="ID",            help="Unchunk a historical chunk by numeric ID")
    group.add_argument("--list-chunk-index",   action="store_true",     help="List all registered projects")
    group.add_argument("--list-project-index", action="store_true",     help="Alias for --list-chunk-index")
    group.add_argument("--list-unchunk-index", action="store_true",     help="List all historical chunks with numeric IDs")
    group.add_argument("--expell-project",     metavar="ID",            help="Remove a project from registry (files kept)")
    group.add_argument("--delete-project",     metavar="ID",            help="Remove a project and delete all chunk files")
    group.add_argument("--get-versions",       metavar="ID",            help="List all versions for a project ID")
    group.add_argument("--delete-version",     nargs=2, metavar=("ID", "VER"), help="Delete a specific version for a project ID")

    # ── MODE 2: Document management ────────────────────────────────────────────
    # Project management
    group.add_argument("--doc-new",            metavar="NAME",          help="Create a new document project")
    group.add_argument("--doc-list",           action="store_true",     help="List all document projects")
    group.add_argument("--doc-sel",            metavar="IDX",           help="Select active document project by index")
    group.add_argument("--doc-mount",          action="store_true",     help="Mount active doc — explode schema to text files")
    group.add_argument("--doc-discard",        action="store_true",     help="Discard mounted changes, restore schema state")
    group.add_argument("--doc-commit",         action="store_true",     help="Commit mounted edits back into the schema")
    group.add_argument("--doc-compile",        action="store_true",     help="Compile active doc → Markdown with TOC")
    group.add_argument("--duplicate-doc",      nargs=2, metavar=("IDX", "NEWNAME"),
                                                                         help="Duplicate a doc project by index to a new name")
    group.add_argument("--rename-doc",         nargs=2, metavar=("IDX", "NEWNAME"),
                                                                         help="Rename a doc project by index")
    group.add_argument("--export-doc",         nargs=2, metavar=("IDX", "FORMAT"),
                                                                         help="Export doc by index (FORMAT: md, txt, json)")
    # Category management
    group.add_argument("--doc-cat-list",       action="store_true",     help="List categories in active doc")
    group.add_argument("--doc-cat-sel",        metavar="IDX",           help="Print category name at index (for scripting)")
    group.add_argument("--doc-cat-add",        metavar="NAME",          help="Add a new category to active doc")
    group.add_argument("--doc-cat-del",        metavar="IDX",           help="Delete a category by index (must be empty)")
    group.add_argument("--doc-cat-inc-idx-pos",metavar="IDX",           help="Move category at IDX one position earlier")
    group.add_argument("--doc-cat-dec-idx-pos",metavar="IDX",           help="Move category at IDX one position later")
    # Chunk management
    group.add_argument("--doc-chunk-list",     action="store_true",     help="List all chunks in active doc, grouped by category")
    group.add_argument("--doc-chunk-sel",      metavar="CHUNK_ID",      help="Print full content of chunk by ID")
    group.add_argument("--doc-chunk-add",      metavar="CATEGORY",      help="Add a new chunk to a category")
    group.add_argument("--doc-chunk-write",    metavar="CHUNK_ID",      help="Write content to a chunk (use --content)")
    group.add_argument("--doc-chunk-del",      metavar="CHUNK_ID",      help="Delete a chunk by ID")
    group.add_argument("--doc-chunk-set-parent-cat", nargs=2, metavar=("CHUNK_ID", "CATEGORY"),
                                                                         help="Move chunk to a different category")
    group.add_argument("--doc-chunk-inc-idx-pos", metavar="CHUNK_ID",   help="Move chunk one position up within its category")
    group.add_argument("--doc-chunk-dec-idx-pos", metavar="CHUNK_ID",   help="Move chunk one position down within its category")

    # ── Tier 1 + Tier 2 commands ──────────────────────────────────────────────
    group.add_argument("--doc-find",          metavar="TEXT",          help="Search all chunks in active doc for text")
    group.add_argument("--doc-stats",         action="store_true",     help="Print word count and stats for active doc")
    group.add_argument("--doc-chunk-tag",     metavar="CHUNK_ID",      help="Set tags on a chunk (use --tags)")
    group.add_argument("--doc-chunk-set-status", metavar="CHUNK_ID",   help="Set chunk status: draft|review|final|skip")
    group.add_argument("--doc-compile-filtered", action="store_true",  help="Compile filtered chunks (use --tag and/or --status)")
    group.add_argument("--doc-merge",         nargs=2, metavar=("IDX_LIST", "OUTPUT_NAME"),
                                                                         help="Merge compiled docs (comma-sep IDX list) into one")
    group.add_argument("--doc-import-file",   metavar="FILE",          help="Import text file as chunks (use --delimiter, --category)")
    group.add_argument("--doc-lock",          metavar="IDX",           nargs="?", const="",
                                                                         help="Lock doc by index (or active if omitted)")
    group.add_argument("--doc-unlock",        metavar="IDX",           nargs="?", const="",
                                                                         help="Unlock doc by index (or active if omitted)")
    group.add_argument("--doc-snapshot",      action="store_true",     help="Snapshot active doc schema+compiled to zip")
    group.add_argument("--doc-restore-snapshot", metavar="FILE",       help="Restore a snapshot zip into active doc")

    # ── Shared options ─────────────────────────────────────────────────────────
    parser.add_argument("--dest",      metavar="DIR",           help="Custom destination for --unchunk")
    parser.add_argument("--label",     metavar="LABEL",         help="Chunk label for --doc-chunk-add")
    parser.add_argument("--content",   metavar="TEXT_OR_FILE",  help="Content or file path for --doc-chunk-write")
    parser.add_argument("--tags",      metavar="TAGS",          help="Comma-separated tags for --doc-chunk-tag")
    parser.add_argument("--status",    metavar="STATUS",        help="Chunk status for --doc-chunk-set-status or --doc-compile-filtered")
    parser.add_argument("--tag",       metavar="TAG",           help="Single tag to filter by in --doc-compile-filtered")
    parser.add_argument("--delimiter", metavar="DELIM",         help="Delimiter for --doc-import-file (e.g. --- or \\n\\n)")
    parser.add_argument("--category",  metavar="CATEGORY",      help="Target category for --doc-import-file")

    args = parser.parse_args()

    # ── MODE 1 routing ─────────────────────────────────────────────────────────
    if args.list_chunk_index or args.list_project_index:
        list_chunk_index()
    elif args.list_unchunk_index:
        list_unchunk_index()
    elif args.chunk:
        run_chunk(args.chunk)
    elif args.chunk_index:
        source_path = resolve_registry_path(args.chunk_index)
        if source_path:
            run_chunk(source_path)
        else:
            print(f"Error: Project ID {args.chunk_index} not found in registry.")
    elif args.unchunk:
        run_unchunk(args.unchunk, args.dest)
    elif args.unchunk_index:
        chunk_path = resolve_history_path(args.unchunk_index)
        if chunk_path:
            run_unchunk(chunk_path, args.dest)
        else:
            print(f"Error: Chunk ID {args.unchunk_index} not found in history.")
    elif args.expell_project:
        expell_project(args.expell_project)
    elif args.delete_project:
        delete_project(args.delete_project)
    elif args.get_versions:
        get_versions(args.get_versions)
    elif args.delete_version:
        delete_version(args.delete_version[0], args.delete_version[1])

    # ── MODE 2 routing ─────────────────────────────────────────────────────────
    elif args.doc_new:
        cmd_doc_new(args.doc_new)
    elif args.doc_list:
        cmd_doc_list()
    elif args.doc_sel:
        cmd_doc_sel(args.doc_sel)
    elif args.doc_mount:
        cmd_doc_mount()
    elif args.doc_discard:
        cmd_doc_discard()
    elif args.doc_commit:
        cmd_doc_commit()
    elif args.doc_compile:
        cmd_doc_compile()
    elif args.duplicate_doc:
        cmd_duplicate_doc(args.duplicate_doc[0], args.duplicate_doc[1])
    elif args.rename_doc:
        cmd_rename_doc(args.rename_doc[0], args.rename_doc[1])
    elif args.export_doc:
        cmd_export_doc(args.export_doc[0], args.export_doc[1])
    elif args.doc_cat_list:
        cmd_doc_cat_list()
    elif args.doc_cat_sel:
        cmd_doc_cat_sel(args.doc_cat_sel)
    elif args.doc_cat_add:
        cmd_doc_cat_add(args.doc_cat_add)
    elif args.doc_cat_del:
        cmd_doc_cat_del(args.doc_cat_del)
    elif args.doc_cat_inc_idx_pos:
        cmd_doc_cat_inc_idx_pos(args.doc_cat_inc_idx_pos)
    elif args.doc_cat_dec_idx_pos:
        cmd_doc_cat_dec_idx_pos(args.doc_cat_dec_idx_pos)
    elif args.doc_chunk_list:
        cmd_doc_chunk_list()
    elif args.doc_chunk_sel:
        cmd_doc_chunk_sel(args.doc_chunk_sel)
    elif args.doc_chunk_add:
        cmd_doc_chunk_add(args.doc_chunk_add, args.label)
    elif args.doc_chunk_write:
        if not args.content:
            print("Error: --doc-chunk-write requires --content TEXT_OR_FILE")
        else:
            cmd_doc_chunk_write(args.doc_chunk_write, args.content)
    elif args.doc_chunk_del:
        cmd_doc_chunk_del(args.doc_chunk_del)
    elif args.doc_chunk_set_parent_cat:
        cmd_doc_chunk_set_parent_cat(args.doc_chunk_set_parent_cat[0], args.doc_chunk_set_parent_cat[1])
    elif args.doc_chunk_inc_idx_pos:
        cmd_doc_chunk_inc_idx_pos(args.doc_chunk_inc_idx_pos)
    elif args.doc_chunk_dec_idx_pos:
        cmd_doc_chunk_dec_idx_pos(args.doc_chunk_dec_idx_pos)

    # ── Tier 1 routing ────────────────────────────────────────────────────────
    elif args.doc_find:
        cmd_doc_find(args.doc_find)
    elif args.doc_stats:
        cmd_doc_stats()

    # ── Tier 2 routing ────────────────────────────────────────────────────────
    elif args.doc_chunk_tag:
        if not args.tags and args.tags != "":
            print("Error: --doc-chunk-tag requires --tags COMMA_SEPARATED_TAGS")
        else:
            cmd_doc_chunk_tag(args.doc_chunk_tag, args.tags or "")
    elif args.doc_chunk_set_status:
        if not args.status:
            print("Error: --doc-chunk-set-status requires --status STATUS")
        else:
            cmd_doc_chunk_set_status(args.doc_chunk_set_status, args.status)
    elif args.doc_compile_filtered:
        cmd_doc_compile_filtered(filter_tag=args.tag, filter_status=args.status)
    elif args.doc_merge:
        cmd_doc_merge(args.doc_merge[0], args.doc_merge[1])
    elif args.doc_import_file:
        if not args.delimiter or not args.category:
            print("Error: --doc-import-file requires --delimiter DELIM and --category NAME")
        else:
            cmd_doc_import_file(args.doc_import_file, args.delimiter, args.category, args.label)
    elif args.doc_lock is not None:
        cmd_doc_lock(args.doc_lock if args.doc_lock else None)
    elif args.doc_unlock is not None:
        cmd_doc_unlock(args.doc_unlock if args.doc_unlock else None)
    elif args.doc_snapshot:
        cmd_doc_snapshot()
    elif args.doc_restore_snapshot:
        cmd_doc_restore_snapshot(args.doc_restore_snapshot)

if __name__ == "__main__":
    main()

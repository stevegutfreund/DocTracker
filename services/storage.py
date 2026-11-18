#!/usr/bin/env python3
"""
JSON storage service for DocTracker.

Data format – a JSON array where each element is one document:
    {
        "id":           "a1b2c3d4e5f6",        # random, stable
        "person":       "Alice",
        "doc_type":     "Passport",
        "country":      "Israel",
        "number_last4": "4821",                # never the full number
        "issue_date":   "2019-03-14" | "",     # ISO dates
        "expiry_date":  "2029-03-13" | "",     # "" = does not expire
        "links": [                             # Drive links to the scans
            {"label": "Card", "url": "https://drive.google.com/file/d/..."},
            {"label": "ספח",  "url": "https://drive.google.com/file/d/..."}
        ],
        "notes":        "",
        "appointment": {                       # renewal appointment, or {}
            "date": "2027-01-17", "time": "09:24",
            "place": "רשות האוכלוסין וההגירה", "notes": ""
        }
    }

Older records with a single "drive_url" are converted to "links" on load.
"""

import json
import os
import uuid
from typing import List, Optional

# Resolve paths relative to this file so the app can be run from any CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
DOCS_FILE = os.path.join(DATA_DIR, "documents.json")
TYPES_FILE = os.path.join(DATA_DIR, "types.json")

# Used until the user edits the type list for the first time.  "travel"
# marks the types the trip check looks at; "links" are the labels the add
# form pre-fills for that type's scan links.
DEFAULT_TYPES = [
    {"name": "Passport",          "icon": "🛂", "travel": True,  "links": ["Scan"]},
    {"name": "ID card",           "icon": "🪪", "travel": False, "links": ["Card", "ספח", "Card + ספח"]},
    {"name": "Driver's licence",  "icon": "🚗", "travel": False, "links": ["Front", "Back"]},
    {"name": "Visa",              "icon": "🛃", "travel": False, "links": ["Scan"]},
    {"name": "Residence permit",  "icon": "🏠", "travel": False, "links": ["Scan"]},
    {"name": "Birth certificate", "icon": "👶", "travel": False, "links": ["Scan"]},
    {"name": "Other",             "icon": "📄", "travel": False, "links": ["Scan"]},
]
_DEFAULT_LINKS = {t["name"]: t["links"] for t in DEFAULT_TYPES}

FIELDS = (
    "person",
    "doc_type",
    "country",
    "number_last4",
    "issue_date",
    "expiry_date",
    "links",
    "notes",
    "appointment",
)


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _normalize(doc: dict) -> dict:
    """Upgrade an old single-link record to the "links" list."""
    if not isinstance(doc.get("links"), list):
        url = doc.get("drive_url", "")
        doc["links"] = [{"label": "Scan", "url": url}] if url else []
    doc.pop("drive_url", None)
    if not isinstance(doc.get("appointment"), dict):
        doc["appointment"] = {}
    return doc


def _blank(field: str):
    return {"links": [], "appointment": {}}.get(field, "")


def load_documents() -> List[dict]:
    """Return all documents.  Returns [] if the file is missing or malformed."""
    _ensure_data_dir()
    if not os.path.exists(DOCS_FILE):
        return []
    try:
        with open(DOCS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        return [_normalize(d) for d in data if isinstance(d, dict) and d.get("id")]
    except (json.JSONDecodeError, OSError):
        return []


def save_documents(docs: List[dict]) -> None:
    """Persist the document list (atomic-ish write)."""
    _ensure_data_dir()
    tmp = DOCS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(docs, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, DOCS_FILE)


def get_document(doc_id: str) -> Optional[dict]:
    return next((d for d in load_documents() if d["id"] == doc_id), None)


def add_document(fields: dict) -> dict:
    doc = {"id": uuid.uuid4().hex[:12]}
    doc.update({k: fields.get(k, _blank(k)) for k in FIELDS})
    docs = load_documents()
    docs.append(doc)
    save_documents(docs)
    return doc


def update_document(doc_id: str, fields: dict) -> bool:
    docs = load_documents()
    for doc in docs:
        if doc["id"] == doc_id:
            doc.update({k: fields.get(k, _blank(k)) for k in FIELDS})
            save_documents(docs)
            return True
    return False


def delete_document(doc_id: str) -> bool:
    docs = load_documents()
    remaining = [d for d in docs if d["id"] != doc_id]
    if len(remaining) == len(docs):
        return False
    save_documents(remaining)
    return True


# ---------------------------------------------------------------------------
# Document types – an ordered list, edited on the Types page
# ---------------------------------------------------------------------------

def load_types() -> List[dict]:
    """Return the type list in display order (the defaults if never edited)."""
    try:
        with open(TYPES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        types = [
            {
                "name": t["name"],
                "icon": t.get("icon", ""),
                "travel": bool(t.get("travel")),
                "links": [str(l) for l in t["links"]] if isinstance(t.get("links"), list)
                         else _DEFAULT_LINKS.get(t["name"], ["Scan"]),
            }
            for t in data
            if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
        ]
        if types:
            return types
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return [{**t, "links": list(t["links"])} for t in DEFAULT_TYPES]


def save_types(types: List[dict]) -> None:
    _ensure_data_dir()
    tmp = TYPES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(types, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, TYPES_FILE)


def rename_type_in_documents(old: str, new: str) -> int:
    """Point every document of type *old* at *new*.  Returns how many changed."""
    docs = load_documents()
    changed = 0
    for doc in docs:
        if doc.get("doc_type") == old:
            doc["doc_type"] = new
            changed += 1
    if changed:
        save_documents(docs)
    return changed

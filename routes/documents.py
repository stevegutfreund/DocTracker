#!/usr/bin/env python3
"""Routes for DocTracker: overview, document CRUD, types, trip check, reminders."""

import re
from datetime import date
from itertools import zip_longest

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from services import storage
from services.expiry import (
    REMINDER_OFFSETS,
    STATUSES,
    build_ics,
    enrich_all,
    group_by_type,
    overview,
    parse_date,
    summary,
    trip_check,
)

docs_bp = Blueprint("docs", __name__)

DRIVE_URL_RE = re.compile(r"^https://(drive|docs)\.google\.com/\S+$")
MAX_LINKS = 8


def _people(docs):
    return sorted({d["person"] for d in docs if d.get("person")}, key=str.casefold)


def _countries(docs):
    return sorted({d["country"] for d in docs if d.get("country")}, key=str.casefold)


def _places(docs):
    places = {(d.get("appointment") or {}).get("place", "") for d in docs}
    places.add("רשות האוכלוסין וההגירה")
    return sorted(p for p in places if p)


@docs_bp.app_context_processor
def inject_type_icons():
    """Every template can show a type's icon via type_icons[doc.doc_type]."""
    return {"type_icons": {t["name"]: t["icon"] for t in storage.load_types()}}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@docs_bp.route("/")
def index():
    docs = storage.load_documents()
    return render_template(
        "overview.html",
        ov=overview(docs, date.today(), storage.load_types()),
        statuses=STATUSES,
    )


@docs_bp.route("/api/summary")
def api_summary():
    """Counts only (no names or numbers), e.g. for a dashboard tile."""
    return jsonify(summary(storage.load_documents(), date.today()))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@docs_bp.route("/documents")
def list_documents():
    docs = storage.load_documents()
    types = storage.load_types()
    items = enrich_all(docs, date.today())

    person = request.args.get("person", "")
    doc_type = request.args.get("type", "")
    status = request.args.get("status", "")
    group = request.args.get("group", "")
    if person:
        items = [d for d in items if d["person"] == person]
    if doc_type:
        items = [d for d in items if d["doc_type"] == doc_type]
    if status:
        items = [d for d in items if d["status"] == status]

    groups = None
    if group == "type":
        groups = [g for g in group_by_type(items, types) if g["docs"]]

    return render_template(
        "documents/list.html",
        items=items,
        groups=groups,
        people=_people(docs),
        doc_types=[t["name"] for t in types],
        statuses=STATUSES,
        f={"person": person, "type": doc_type, "status": status, "group": group},
    )


def _read_form():
    """Validate the form.  Returns (fields, errors, notices)."""
    form = request.form
    errors, notices = [], []
    fields = {k: form.get(k, "").strip() for k in storage.FIELDS if k not in ("links", "appointment")}

    if not fields["person"]:
        errors.append("Person is required.")
    if fields["doc_type"] not in {t["name"] for t in storage.load_types()}:
        errors.append("Choose a document type.")

    for key, label in (("issue_date", "Issue date"), ("expiry_date", "Expiry date")):
        if fields[key] and parse_date(fields[key]) is None:
            errors.append(f"{label} is not a valid date.")
    issue, expiry = parse_date(fields["issue_date"]), parse_date(fields["expiry_date"])
    if issue and expiry and issue > expiry:
        errors.append("Issue date is after the expiry date.")

    # Never store a full document number, even if one is pasted in.
    number = re.sub(r"[^0-9A-Za-z]", "", fields["number_last4"])
    if len(number) > 4:
        notices.append("Only the last 4 characters of the number were kept.")
    fields["number_last4"] = number[-4:]

    # Link rows arrive as parallel lists; rows without a URL are dropped.
    links = []
    for label, url in zip_longest(form.getlist("link_label"), form.getlist("link_url"), fillvalue=""):
        label, url = label.strip()[:30], url.strip()
        if not url:
            continue
        links.append({"label": label or "Scan", "url": url})
        if not DRIVE_URL_RE.match(url):
            errors.append(f"The \"{label or 'Scan'}\" link must be a Google Drive link (https://drive.google.com/…).")
    if len(links) > MAX_LINKS:
        errors.append(f"At most {MAX_LINKS} links per document.")
    fields["links"] = links

    appt = {
        "date": form.get("appt_date", "").strip(),
        "time": form.get("appt_time", "").strip(),
        "place": form.get("appt_place", "").strip()[:80],
        "notes": form.get("appt_notes", "").strip()[:200],
    }
    if appt["date"]:
        if parse_date(appt["date"]) is None:
            errors.append("The appointment date is not a valid date.")
        if appt["time"] and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", appt["time"]):
            errors.append("The appointment time must look like 09:24.")
        fields["appointment"] = appt
    else:
        fields["appointment"] = {}

    return fields, errors, notices


def _render_form(doc, errors=(), status_code=200):
    docs = storage.load_documents()
    types = storage.load_types()
    type_links = {t["name"]: t["links"] for t in types}
    # A new document starts with one empty row per label its type suggests
    # (e.g. Card / ספח / Card + ספח for an ID card), plus a spare row.
    rows = list(doc.get("links") or [])
    if not rows:
        rows = [{"label": l, "url": ""} for l in type_links.get(doc.get("doc_type"), [])]
    rows.append({"label": "", "url": ""})
    return render_template(
        "documents/form.html",
        doc=doc,
        link_rows=rows,
        type_links=type_links,
        errors=errors,
        people=_people(docs),
        countries=_countries(docs),
        places=_places(docs),
        doc_types=types,
    ), status_code


@docs_bp.route("/documents/new", methods=["GET", "POST"])
def new_document():
    if request.method == "POST":
        fields, errors, notices = _read_form()
        if errors:
            return _render_form(fields, errors, 400)
        storage.add_document(fields)
        for n in notices:
            flash(n, "notice")
        flash(f"Added {fields['person']}'s {fields['doc_type']}.", "ok")
        if request.form.get("again"):
            return redirect(url_for("docs.new_document", person=fields["person"], type=fields["doc_type"]))
        return redirect(url_for("docs.list_documents"))

    types = storage.load_types()
    default_type = request.args.get("type") or types[0]["name"]
    return _render_form({"person": request.args.get("person", ""), "doc_type": default_type})


@docs_bp.route("/documents/<doc_id>/edit", methods=["GET", "POST"])
def edit_document(doc_id):
    doc = storage.get_document(doc_id)
    if doc is None:
        abort(404)
    if request.method == "POST":
        fields, errors, notices = _read_form()
        if errors:
            return _render_form({**fields, "id": doc_id}, errors, 400)
        storage.update_document(doc_id, fields)
        for n in notices:
            flash(n, "notice")
        flash(f"Saved {fields['person']}'s {fields['doc_type']}.", "ok")
        return redirect(url_for("docs.list_documents"))
    return _render_form(doc)


@docs_bp.route("/documents/<doc_id>/delete", methods=["POST"])
def delete_document(doc_id):
    if storage.delete_document(doc_id):
        flash("Document removed.", "ok")
    return redirect(url_for("docs.list_documents"))


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

def _type_fields():
    return {
        "name": re.sub(r"\s+", " ", request.form.get("name", "")).strip()[:40],
        "icon": request.form.get("icon", "").strip()[:4],
        "travel": bool(request.form.get("travel")),
        "links": [l.strip()[:30] for l in request.form.get("links", "").split(",") if l.strip()][:MAX_LINKS]
                 or ["Scan"],
    }


@docs_bp.route("/types")
def list_types():
    types = storage.load_types()
    usage = {}
    for d in storage.load_documents():
        usage[d.get("doc_type")] = usage.get(d.get("doc_type"), 0) + 1
    return render_template("types.html", types=types, usage=usage)


@docs_bp.route("/types/add", methods=["POST"])
def add_type():
    fields = _type_fields()
    types = storage.load_types()
    if not fields["name"]:
        flash("A type needs a name.", "error")
    elif any(t["name"].casefold() == fields["name"].casefold() for t in types):
        flash(f"There is already a type called {fields['name']}.", "error")
    else:
        types.append(fields)
        storage.save_types(types)
        flash(f"Added the type {fields['name']}.", "ok")
    return redirect(url_for("docs.list_types"))


@docs_bp.route("/types/<int:idx>/edit", methods=["POST"])
def edit_type(idx):
    types = storage.load_types()
    if not 0 <= idx < len(types):
        abort(404)
    fields = _type_fields()
    old = types[idx]["name"]
    if not fields["name"]:
        flash("A type needs a name.", "error")
    elif any(i != idx and t["name"].casefold() == fields["name"].casefold() for i, t in enumerate(types)):
        flash(f"There is already a type called {fields['name']}.", "error")
    else:
        types[idx] = fields
        storage.save_types(types)
        moved = storage.rename_type_in_documents(old, fields["name"]) if old != fields["name"] else 0
        note = f" ({moved} document{'s' if moved != 1 else ''} updated)" if moved else ""
        flash(f"Saved {fields['name']}{note}.", "ok")
    return redirect(url_for("docs.list_types"))


@docs_bp.route("/types/<int:idx>/move", methods=["POST"])
def move_type(idx):
    types = storage.load_types()
    target = idx + (1 if request.form.get("dir") == "down" else -1)
    if 0 <= idx < len(types) and 0 <= target < len(types):
        types[idx], types[target] = types[target], types[idx]
        storage.save_types(types)
    return redirect(url_for("docs.list_types"))


@docs_bp.route("/types/<int:idx>/delete", methods=["POST"])
def delete_type(idx):
    types = storage.load_types()
    if not 0 <= idx < len(types):
        abort(404)
    name = types[idx]["name"]
    used = sum(d.get("doc_type") == name for d in storage.load_documents())
    if used:
        flash(f"{name} is used by {used} document{'s' if used != 1 else ''}. "
              "Change their type first, or rename this one.", "error")
    elif len(types) == 1:
        flash("Keep at least one type.", "error")
    else:
        types.pop(idx)
        storage.save_types(types)
        flash(f"Deleted the type {name}.", "ok")
    return redirect(url_for("docs.list_types"))


# ---------------------------------------------------------------------------
# Trip check
# ---------------------------------------------------------------------------

@docs_bp.route("/trip")
def trip():
    docs = storage.load_documents()
    people = _people(docs)
    travel_types = [t["name"] for t in storage.load_types() if t["travel"]]
    depart = parse_date(request.args.get("depart", ""))
    ret = parse_date(request.args.get("return", ""))
    chosen = request.args.getlist("who") or people

    results, error = None, None
    if depart or ret:
        if not (depart and ret):
            error = "Enter both dates."
        elif ret < depart:
            error = "The return date is before the departure date."
        else:
            results = trip_check(docs, depart, ret, chosen, date.today(), set(travel_types))

    return render_template(
        "trip.html",
        people=people,
        chosen=chosen,
        depart=request.args.get("depart", ""),
        ret=request.args.get("return", ""),
        results=results,
        error=error,
        travel_types=travel_types,
    )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@docs_bp.route("/reminders")
def reminders():
    return render_template("reminders.html", offsets=REMINDER_OFFSETS)


@docs_bp.route("/reminders.ics")
def reminders_ics():
    valid = {m for m, _ in REMINDER_OFFSETS}
    offsets = sorted({int(m) for m in request.args.getlist("m") if m.isdigit() and int(m) in valid},
                     reverse=True) or [9, 3, 0]
    # The form always sends "sent"; a bare /reminders.ics link includes appointments.
    appointments = "appts" in request.args or "sent" not in request.args
    body = build_ics(storage.load_documents(), date.today(), offsets, appointments)
    return Response(
        body,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=document-expiry.ics"},
    )

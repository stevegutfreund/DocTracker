#!/usr/bin/env python3
"""
Expiry logic for DocTracker: status classification, overview stats, the trip
check, and the .ics reminder export.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, List, Optional

from dateutil.relativedelta import relativedelta

# Calendar event UIDs keep the app's original name, so re-importing the
# .ics updates events already in a calendar instead of duplicating them.
UID_DOMAIN = "famdocs.local"

# Ordered most-urgent first.  "serious" uses 6 months because many countries
# refuse entry on a passport with less than 6 months of validity left.
STATUSES = {
    "expired": {"label": "Expired",         "icon": "✕", "rank": 0},
    "serious": {"label": "Under 6 months",  "icon": "!", "rank": 1},
    "warning": {"label": "Under 12 months", "icon": "◷", "rank": 2},
    "good":    {"label": "Valid",           "icon": "✓", "rank": 3},
    "none":    {"label": "No expiry",       "icon": "–", "rank": 4},
}


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except (TypeError, ValueError):
        return None


def fmt_date(value) -> str:
    """'2029-03-13' or a date → '13 Mar 2029'."""
    d = parse_date(value) if isinstance(value, str) else value
    return d.strftime("%d %b %Y").lstrip("0") if d else "—"


def _span(a: date, b: date) -> str:
    """Largest-unit description of the gap between two dates (a <= b)."""
    rd = relativedelta(b, a)
    if rd.years:
        months = f" {rd.months} mo" if rd.months else ""
        return f"{rd.years} yr{'s' if rd.years > 1 else ''}{months}"
    if rd.months:
        return f"{rd.months} month{'s' if rd.months > 1 else ''}"
    days = (b - a).days
    return f"{days} day{'s' if days != 1 else ''}"


def relative(expiry: Optional[date], today: date) -> str:
    if expiry is None:
        return ""
    if expiry == today:
        return "expires today"
    if expiry < today:
        return f"expired {_span(expiry, today)} ago"
    return f"in {_span(today, expiry)}"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(expiry: Optional[date], today: date) -> str:
    if expiry is None:
        return "none"
    if expiry < today:
        return "expired"
    if expiry < today + relativedelta(months=6):
        return "serious"
    if expiry < today + relativedelta(months=12):
        return "warning"
    return "good"


def _appointment(doc: dict, today: date) -> Optional[dict]:
    """The document's renewal appointment, or None if none is booked."""
    a = doc.get("appointment") or {}
    when = parse_date(a.get("date", ""))
    if when is None:
        return None
    if when == today:
        rel = "today"
    elif when > today:
        rel = f"in {_span(today, when)}"
    else:
        rel = f"{_span(when, today)} ago"
    return {**a, "when": when, "past": when < today, "relative": rel}


def enrich(doc: dict, today: date) -> dict:
    expiry = parse_date(doc.get("expiry_date", ""))
    status = classify(expiry, today)
    return {
        "appt": _appointment(doc, today),
        **doc,
        "expiry": expiry,
        "issue": parse_date(doc.get("issue_date", "")),
        "status": status,
        "status_info": STATUSES[status],
        "days_left": (expiry - today).days if expiry else None,
        "relative": relative(expiry, today),
    }


def sort_key(d: dict):
    return (d["expiry"] is None, d["expiry"] or date.max, d.get("person", ""))


def enrich_all(docs: Iterable[dict], today: date) -> List[dict]:
    return sorted((enrich(d, today) for d in docs), key=sort_key)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def group_by_type(items: List[dict], types: List[dict]) -> List[dict]:
    """Group enriched docs by type, in the type list's order.  Types with no
    documents are kept (count 0); a doc_type missing from the list – e.g. the
    type was deleted – gets its own group at the end."""
    groups = {t["name"]: {**t, "docs": []} for t in types}
    for d in items:
        groups.setdefault(d["doc_type"], {"name": d["doc_type"], "icon": "", "travel": False, "docs": []})
        groups[d["doc_type"]]["docs"].append(d)
    result = []
    for g in groups.values():
        counts = {k: 0 for k in STATUSES}
        for d in g["docs"]:
            counts[d["status"]] += 1
        result.append({**g, "count": len(g["docs"]), "counts": counts})
    return result


def _group_slots(appointments: List[dict]) -> List[dict]:
    """Merge appointments sharing date, time and place into one slot (a
    family usually books together).  Input is already sorted by time."""
    slots = []
    for d in appointments:
        a = d["appt"]
        key = (a["when"], a.get("time", ""), a.get("place", ""))
        if slots and slots[-1]["key"] == key:
            slots[-1]["docs"].append(d)
        else:
            slots.append({"key": key, "appt": a, "docs": [d]})
    return slots


def overview(docs: List[dict], today: date, types: List[dict]) -> dict:
    items = enrich_all(docs, today)

    counts = {k: 0 for k in STATUSES}
    for d in items:
        counts[d["status"]] += 1

    attention = [d for d in items if d["status"] in ("expired", "serious", "warning")]
    upcoming = [d for d in items if d["status"] == "good"][:3]

    # Renewals per year, from this year to the last expiry on file.
    by_year = defaultdict(list)
    for d in items:
        if d["expiry"] and d["expiry"] >= today:
            by_year[d["expiry"].year].append(d)
    years = []
    if by_year:
        peak = max(len(v) for v in by_year.values())
        for y in range(today.year, max(by_year) + 1):
            group = by_year.get(y, [])
            years.append({
                "year": y,
                "count": len(group),
                "pct": round(100 * len(group) / peak),
                "docs": group,
            })

    appointments = sorted(
        (d for d in items if d["appt"] and not d["appt"]["past"]),
        key=lambda d: (d["appt"]["when"], d["appt"].get("time", ""), d["person"]),
    )
    # Appointment date has passed but the document still shows the old
    # details – it probably needs the renewed document's dates.
    appt_done = [d for d in items if d["appt"] and d["appt"]["past"]]

    people = defaultdict(list)
    for d in items:
        people[d["person"]].append(d)
    people_list = []
    for name in sorted(people, key=str.casefold):
        group = people[name]
        worst = min(group, key=lambda d: d["status_info"]["rank"])["status"]
        people_list.append({"name": name, "docs": group, "worst": worst})

    return {
        "total": len(items),
        "people_count": len(people),
        "counts": counts,
        "attention": attention,
        "upcoming": upcoming,
        "years": years,
        "people": people_list,
        "types": group_by_type(items, types),
        "appt_slots": _group_slots(appointments),
        "appt_done": appt_done,
    }


def summary(docs: List[dict], today: date) -> dict:
    """Counts only – safe to expose to the dashboard tile."""
    items = enrich_all(docs, today)
    future = [d["days_left"] for d in items if d["days_left"] is not None and d["days_left"] >= 0]
    return {
        "total": len(items),
        "expired": sum(d["status"] == "expired" for d in items),
        "under_6_months": sum(d["status"] == "serious" for d in items),
        "under_12_months": sum(d["status"] == "warning" for d in items),
        "next_expiry_days": min(future) if future else None,
        # Of the documents needing renewal, how many have an upcoming appointment.
        "booked": sum(d["status"] in ("expired", "serious") and bool(d["appt"]) and not d["appt"]["past"]
                      for d in items),
    }


# ---------------------------------------------------------------------------
# Trip check
# ---------------------------------------------------------------------------

def trip_check(docs: List[dict], depart: date, ret: date, people: List[str], today: date,
               travel_types: set) -> List[dict]:
    """Per person: is there a travel document (a type marked "travel", e.g.
    Passport) valid for 6 months past the return date?

    Measuring from the return date is the conservative reading of the
    6-month rule (some countries count from arrival instead).
    """
    needed = ret + relativedelta(months=6)
    items = enrich_all(docs, today)
    results = []
    for name in people:
        passports = [d for d in items if d["person"] == name and d["doc_type"] in travel_types]
        rows = []
        for p in passports:
            if p["expiry"] is None:
                verdict, note = "warning", "No expiry date on file"
            elif p["expiry"] < depart:
                verdict, note = "expired", "Expires before you leave"
            elif p["expiry"] <= ret:
                verdict, note = "expired", "Expires during the trip"
            elif p["expiry"] < needed:
                verdict, note = "serious", f"Only {_span(ret, p['expiry'])} left on return – many countries need 6"
            else:
                verdict, note = "good", f"{_span(ret, p['expiry'])} left on return"
            rows.append({**p, "verdict": verdict, "verdict_info": STATUSES[verdict], "note": note})

        # The person's best passport decides (dual nationals need only one).
        overall = max(rows, key=lambda r: STATUSES[r["verdict"]]["rank"])["verdict"] if rows else "expired"
        results.append({
            "name": name,
            "passports": rows,
            "overall": overall,
            "overall_info": STATUSES[overall],
        })
    return results


# ---------------------------------------------------------------------------
# Calendar export
# ---------------------------------------------------------------------------

REMINDER_OFFSETS = [
    (9, "9 months before"),
    (6, "6 months before"),
    (3, "3 months before"),
    (0, "On the expiry day"),
]


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def _appointment_event(d: dict, what: str, stamp: str) -> List[str]:
    a = d["appt"]
    if a.get("time"):
        start = datetime.combine(a["when"], time.fromisoformat(a["time"]))
        span = [f"DTSTART;TZID=Asia/Jerusalem:{start:%Y%m%dT%H%M%S}",
                f"DTEND;TZID=Asia/Jerusalem:{start + timedelta(minutes=30):%Y%m%dT%H%M%S}"]
    else:
        span = [f"DTSTART;VALUE=DATE:{a['when']:%Y%m%d}",
                f"DTEND;VALUE=DATE:{a['when'] + timedelta(days=1):%Y%m%d}"]
    lines = ["BEGIN:VEVENT", f"UID:{d['id']}-appt@{UID_DOMAIN}", f"DTSTAMP:{stamp}", *span,
             f"SUMMARY:{_ics_escape('Appointment: renew ' + what)}"]
    if a.get("place"):
        lines.append(f"LOCATION:{_ics_escape(a['place'])}")
    if a.get("notes"):
        lines.append(f"DESCRIPTION:{_ics_escape(a['notes'])}")
    lines += ["BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
              f"DESCRIPTION:{_ics_escape('Tomorrow: renew ' + what)}", "END:VALARM", "END:VEVENT"]
    return lines


def build_ics(docs: List[dict], today: date, offsets: List[int], appointments: bool = True) -> str:
    """Expiry reminders (all-day) plus upcoming renewal appointments, with
    stable UIDs so re-importing updates instead of duplicating.  Contains
    names, types, dates and places – never numbers or links."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DocTracker//Expiry reminders//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Document expiry",
    ]
    for d in enrich_all(docs, today):
        what = f"{d['person']}'s {d['doc_type']}" + (f" ({d['country']})" if d.get("country") else "")
        if appointments and d["appt"] and not d["appt"]["past"]:
            lines += _appointment_event(d, what, stamp)
        if d["expiry"] is None:
            continue
        for months in offsets:
            when = d["expiry"] - relativedelta(months=months)
            if when < today:
                continue
            summary = (f"{what} expires today" if months == 0
                       else f"Renew {what} – expires {fmt_date(d['expiry'])}")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{d['id']}-{months}m@{UID_DOMAIN}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{when:%Y%m%d}",
                f"DTEND;VALUE=DATE:{when + timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{_ics_escape(summary)}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

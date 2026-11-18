# DocTracker

Local tracker for documents and their expiry dates: passports, ID cards,
licences, visas, or anything else that has to be renewed.

```
python app.py        # http://127.0.0.1:5004  (also started by ..\dashboard\start-all.bat)
```

## What it stores

`data/documents.json`: one record per document with the person, type, issuing country,
issue and expiry dates, the **last 4 characters** of the number, labelled Google Drive
links to the scans (e.g. an Israeli ID card's *Card*, *ספח* and *Card + ספח*), and notes.
Each type sets which link labels the add form suggests. A document can also hold a
renewal appointment (date, time, place, notes), which appears on the Overview, the
dashboard card and the calendar export.

## What it deliberately does not do

- **It never reads the scans.** There is no Google login and no Drive API.
  Clicking "Open scan" opens the file in Drive under your own Google session.
- It never stores full document numbers. Longer input is cut to the last 4 characters.
- It only listens on `127.0.0.1`. It rejects requests addressed by any other host
  name (DNS rebinding) and writes coming from other websites (CSRF).
- Debug mode stays off.

## Pages

| Page | What it shows |
|---|---|
| Overview | Counts by status, what needs attention, expiries by year, a card per person |
| Overview → By type | One card per type, with its count and status breakdown |
| Documents | Filterable table (optionally grouped by type), add/edit/delete |
| Types | Add, rename, reorder and delete types (icon + "travel document" setting). Saved in `data/types.json`. Renaming updates the documents that use it; a type in use can't be deleted |
| Trip check | Does each traveller's travel document (Passport by default) have 6+ months left after the return date? |
| Reminders | `.ics` download (9/6/3 months before, plus the expiry day) to import into Google Calendar |
| `/api/summary` | Counts only (no names or numbers), e.g. for a dashboard tile |

Status thresholds: **expired**, **under 6 months**, **under 12 months**, **valid**, **no expiry**.

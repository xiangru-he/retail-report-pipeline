"""
Step 11 — load the hand-entered monthly figures.

INPUT   data/reference/monthly_context.csv
OUTPUT  rows in monthly_context

    python step11_load_monthly_context.py             load everything
    python step11_load_monthly_context.py --check     check only, write nothing
    python step11_load_monthly_context.py 2026-05     load, then verify that
                                                      month specifically

WHY A CSV RATHER THAN A FORM OR A SQL SNIPPET
---------------------------------------------
Foot traffic, campaign notes and the like never touch the POS — somebody types
them in. The first version was an INSERT statement edited by hand each month,
which meant only the most recent month survived: to reissue an older report
you had to remember what you'd typed at the time. A CSV with one row per month
keeps the lot, and re-running any month is just reading a row.

That also makes the CSV the single source of truth. Editing the table directly
leaves the two disagreeing, with no way to tell which is right.

EVERY ROW IS WRITTEN, NOT JUST THE CURRENT MONTH
------------------------------------------------
The load is an upsert over the whole file, so correcting January's foot traffic
and reissuing any month later picks the correction up automatically.
"""
import os
import re
import sys

import pandas as pd

import db
from config import STORE_CODE, describe, reference_path

CSV_PATH = reference_path("monthly_context.csv")
PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

REQUIRED_COLUMNS = [
    "period", "foot_traffic", "miniprogram_leads", "miniprogram_completion_rate",
    "study_tour_flag", "study_tour_note", "activity_description",
]


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def load_rows(path=CSV_PATH):
    """Read the CSV into {period: {...}}. Malformed rows are reported, not
    silently dropped."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(
            f"{os.path.relpath(path)} is missing columns {missing}\n"
            f"  found  : {list(df.columns)}\n"
            f"  needed : {','.join(REQUIRED_COLUMNS)}")

    rows = {}
    for lineno, record in enumerate(df.to_dict("records"), start=2):
        period = _clean(record.get("period"))
        if not period:
            continue
        if not PERIOD_RE.match(period):
            print(f"!! line {lineno}: period {period!r} isn't YYYY-MM — skipped")
            continue
        rows[period] = {
            "period": period,
            "foot_traffic": _clean(record.get("foot_traffic")),
            "miniprogram_leads": _clean(record.get("miniprogram_leads")),
            "miniprogram_completion_rate": _clean(record.get("miniprogram_completion_rate")),
            "study_tour_flag": (_clean(record.get("study_tour_flag")) or "no").lower(),
            "study_tour_note": _clean(record.get("study_tour_note")),
            "activity_description": _clean(record.get("activity_description")),
        }
    return rows


def periods_to_check():
    """Which months this run cares about.

    A month given on the command line wins (that's the report case). Otherwise
    fall back to config.MONTHS (the import case) — using MONTHS while building
    a report would check whichever month was last *imported*, not the one being
    reported, and complain about the wrong thing.
    """
    for arg in sys.argv[1:]:
        if PERIOD_RE.match(arg):
            return [arg]
    from config import MONTHS
    return [period for _prefix, period in MONTHS]


def check():
    """Report what's missing without writing. Exit 2 means a person has to act."""
    if not os.path.exists(CSV_PATH):
        print(f"x {os.path.relpath(CSV_PATH)} doesn't exist.")
        print("  This file is required — foot traffic and campaign notes aren't "
              "in the POS, they have to be entered by hand.")
        print(f"  Header: {','.join(REQUIRED_COLUMNS)}")
        return 2

    rows = periods_to_check()
    have = load_rows()
    missing = [p for p in rows if p not in have]
    incomplete = [p for p in rows if p in have and not have[p]["foot_traffic"]]

    if not missing and not incomplete:
        # Say what was found, not just that nothing was wrong. A silent pass
        # and a step that never ran look identical in a terminal, and the
        # first question anyone asks is "did it skip me?".
        print(f"OK — {os.path.relpath(CSV_PATH)} already covers {rows}, "
              "nothing to fill in:")
        for period in rows:
            row = have[period]
            note = row["activity_description"] or "no campaign recorded"
            print(f"    {period}  foot traffic {row['foot_traffic']}, "
                  f"leads {row['miniprogram_leads']}  |  {note[:60]}")
        return 0

    print(f"\n{os.path.relpath(CSV_PATH)} needs attention:")
    for p in missing:
        print(f"  - no row for {p}")
    for p in incomplete:
        print(f"  - {p} exists but foot_traffic is blank")
    print("\n  Add a line in this shape (save as CSV, not xlsx):")
    print(f"    {','.join(REQUIRED_COLUMNS)}")
    print('    2026-05,244,96,63,no,,"Autumn promo; new honey range"')
    print("\n  completion_rate is a percentage as a whole number (63 = 63%)")
    return 2


def upsert(conn, rows):
    cursor = conn.cursor()
    cursor.execute("SELECT store_id FROM dim_store WHERE store_code = %s", (STORE_CODE,))
    store = cursor.fetchone()
    if store is None:
        raise SystemExit(f"store_code {STORE_CODE!r} is not in dim_store")
    store_id = store[0]

    written, skipped = 0, []
    for period, row in sorted(rows.items()):
        cursor.execute("SELECT date_id FROM dim_date WHERE period = %s", (period,))
        found = cursor.fetchone()
        if not found:
            skipped.append(period)
            continue
        cursor.execute("""
            INSERT INTO monthly_context
                (date_id, store_id, foot_traffic, miniprogram_leads,
                 miniprogram_completion_rate, study_tour_flag, study_tour_note,
                 activity_description)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                foot_traffic = VALUES(foot_traffic),
                miniprogram_leads = VALUES(miniprogram_leads),
                miniprogram_completion_rate = VALUES(miniprogram_completion_rate),
                study_tour_flag = VALUES(study_tour_flag),
                study_tour_note = VALUES(study_tour_note),
                activity_description = VALUES(activity_description)
        """, (found[0], store_id, row["foot_traffic"], row["miniprogram_leads"],
              row["miniprogram_completion_rate"], row["study_tour_flag"],
              row["study_tour_note"], row["activity_description"]))
        written += 1
        print(f"  {period}  foot traffic {row['foot_traffic']}, "
              f"leads {row['miniprogram_leads']}")

    conn.commit()
    cursor.close()
    if skipped:
        print(f"\n!! dim_date has no row for {skipped} — import that month's "
              "sales first, then run this again")
    return written


def main():
    if "--check" in sys.argv:
        return check()

    print(describe())
    if not os.path.exists(CSV_PATH):
        print(f"x {os.path.relpath(CSV_PATH)} doesn't exist")
        return 1

    rows = load_rows()
    if not rows:
        print(f"x no usable rows in {os.path.relpath(CSV_PATH)}")
        return 1

    conn = db.connect()
    written = upsert(conn, rows)
    conn.close()
    print(f"\n{written} month(s) written to monthly_context")

    # Re-check afterwards. --check only runs during import; a report built with
    # --resume skips it entirely, and without this the report would quietly
    # come out with blank operating figures.
    absent = [p for p in periods_to_check() if p not in rows]
    if absent:
        print("\n" + "!" * 64)
        print(f"{absent} has no row in {os.path.relpath(CSV_PATH)}")
        print("The report will still build, but foot traffic / campaign notes "
              "will show as blank.")
        print("!" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

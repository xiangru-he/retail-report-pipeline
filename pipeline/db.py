"""
db.py — database access, and the "what do we already know" lookup.

THE IDEA
--------
`dim_product` is not just storage, it's the pipeline's memory. A SKU's
classification (category, tier, shipping mode) is decided once and never
changes, so any SKU already in that table needs no work at all on later runs:
no rule evaluation, no keyword check, no question for the operator.

That's what makes the monthly effort shrink. Month one, every SKU is new and
somebody has to classify the brands. By month four the table holds a few
hundred SKUs and the only thing left to look at is what genuinely just
appeared.

The earlier design kept this memory in CSVs regenerated from each month's
spreadsheet. That quietly lost information: a CSV rebuilt from March's file
only contains brands that sold in March, so a brand that skipped a month came
back looking brand new. A table only ever grows.

This module only reads. Writing is the load steps' job.
"""
import os
import sys

from config import DB_CONFIG, DB_PASSWORD


def get_password():
    """Resolve the DB password: environment first, then an interactive prompt.

    Never call getpass() unconditionally — in a non-interactive context
    (a scheduled run, a subprocess, redirected stdin) it blocks forever with
    no output at all. Failing fast with a message is far easier to diagnose.
    """
    if DB_PASSWORD is not None:
        return DB_PASSWORD
    if not sys.stdin.isatty():
        raise RuntimeError(
            "No MYSQL_PASSWORD in the environment and this isn't an interactive "
            "terminal, so there's no way to ask. Set it in .env or export it."
        )
    from getpass import getpass
    return getpass("MySQL password: ")


def connect():
    import mysql.connector
    return mysql.connector.connect(password=get_password(), **DB_CONFIG)


def rpt_period(conn=None):
    """Which month the report is for.

    Kept in the database rather than passed to each step, because every SQL
    query already joins to report_config. One row, one value, no way to end up
    with a deck whose charts are on different months.
    """
    own = conn is None
    conn = conn or connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT rpt_period FROM report_config LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        if not row:
            raise SystemExit("report_config is empty — run sql/schema.sql")
        return row[0]
    finally:
        if own:
            conn.close()


def set_rpt_period(period, conn=None):
    """Point the report at a different month.

    Upsert on a fixed id so the table can never hold two rows — two rows would
    make `LIMIT 1` pick one arbitrarily, and the report would be for whichever
    month happened to sort first.
    """
    own = conn is None
    conn = conn or connect()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO report_config (config_id, rpt_period) VALUES (1, %s)
            ON DUPLICATE KEY UPDATE rpt_period = VALUES(rpt_period)
        """, (period,))
        conn.commit()
        cursor.close()
        return period
    finally:
        if own:
            conn.close()


def load_known_skus(conn=None):
    """Every SKU the database has already classified.

    Returns {sku_code: {brand, category, tier, shipping_channel, product_type}}
    """
    own = conn is None
    conn = conn or connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT sku_code, brand, category, tier, shipping_channel, product_type
            FROM dim_product
        """)
        known = {
            str(sku): {
                "brand": brand,
                "category": category,
                "tier": tier,
                "shipping_channel": shipping,
                "product_type": ptype,
            }
            for sku, brand, category, tier, shipping, ptype in cur.fetchall()
        }
        cur.close()
        return known
    finally:
        if own:
            conn.close()


def load_known_skus_safe():
    """Same, but returns ({}, reason) instead of raising when the database
    isn't reachable.

    Being unable to reach the DB is not an error for the classification steps —
    they simply fall back to classifying everything from scratch, which gives
    the same answers, just without the shortcut. Offline work on the CSVs
    shouldn't be blocked by a database that happens to be down.
    """
    try:
        return load_known_skus(), None
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def brands_in(known_skus):
    """Category counts per brand: {'fernvale': {'milk_powder': 8, 'supplement': 2}}

    Used to spot brands that span categories — the reason SKU-level overrides
    exist in the first place.
    """
    out = {}
    for info in known_skus.values():
        brand = str(info["brand"]).strip().lower()
        out.setdefault(brand, {})
        out[brand][info["category"]] = out[brand].get(info["category"], 0) + 1
    return out


if __name__ == "__main__":
    # Quick health check: how much does the database remember so far?
    known, err = load_known_skus_safe()
    if err:
        raise SystemExit(f"Could not reach the database: {err}")

    by_brand = brands_in(known)
    print(f"dim_product holds {len(known)} SKUs across {len(by_brand)} brands")

    multi = {b: c for b, c in by_brand.items() if len(c) > 1}
    print("\nBrands spanning more than one category "
          "(new SKUs here need a closer look):")
    for brand, counts in sorted(multi.items()):
        print(f"  {brand:<22} {counts}")
    if not multi:
        print("  (none)")

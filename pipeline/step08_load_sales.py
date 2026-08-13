"""
Step 08 — load dim_product and fact_sales into MySQL.

INPUT   data/work/dim_product.csv, data/work/fact_sales.csv
OUTPUT  rows in dim_product, fact_sales (and dim_date, filled in as needed)

SAFE TO RE-RUN. Both loads are upserts keyed on the natural key, so importing
the same month twice overwrites rather than duplicates.

dim_date IS FILLED IN AUTOMATICALLY
-----------------------------------
It used to be seeded by hand with the months that existed at the time. The
first month past that list failed the date_id lookup and the load aborted —
a clear error, but a chore that had to be remembered every quarter and was
easy to forget. Now the months present in fact_sales.csv are checked and any
that are missing get inserted, with year/quarter derived from the string.
"""
import pandas as pd

import db
from config import STORE_CODE, describe, work_path


def ensure_dim_date(cursor, conn, periods):
    """Insert any of these 'YYYY-MM' months that dim_date doesn't have yet."""
    cursor.execute("SELECT period FROM dim_date")
    existing = {row[0] for row in cursor.fetchall()}

    missing = []
    for period in sorted({str(p) for p in periods}):
        if period in existing:
            continue
        try:
            year, month = int(period[:4]), int(period[5:7])
        except (ValueError, IndexError):
            print(f"!! skipping unparseable period {period!r}")
            continue
        if not 1 <= month <= 12:
            print(f"!! skipping out-of-range period {period!r}")
            continue
        missing.append((period, year, month, (month - 1) // 3 + 1))

    if not missing:
        return
    cursor.executemany(
        "INSERT INTO dim_date (period, year, month, quarter) VALUES (%s,%s,%s,%s)",
        missing)
    conn.commit()
    print(f"dim_date: added {len(missing)} month(s) {[m[0] for m in missing]}")


def main():
    print(describe())
    dim = pd.read_csv(work_path("dim_product.csv"))
    fact = pd.read_csv(work_path("fact_sales.csv"))

    conn = db.connect()
    cursor = conn.cursor()

    # ---- dim_product -------------------------------------------------------
    # product_type is loaded separately in step 09, so it isn't touched here —
    # updating it to a default would wipe the previous run's classification.
    cursor.executemany("""
        INSERT INTO dim_product
            (sku_code, brand, product_desc, category, tier, shipping_channel)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            brand = VALUES(brand),
            product_desc = VALUES(product_desc),
            category = VALUES(category),
            tier = VALUES(tier),
            shipping_channel = VALUES(shipping_channel)
    """, list(dim[["sku_code", "brand", "product_desc",
                   "category", "tier", "shipping_channel"]]
              .itertuples(index=False, name=None)))
    conn.commit()
    print(f"\ndim_product: {len(dim)} rows written")

    # ---- lookups -----------------------------------------------------------
    cursor.execute("SELECT sku_id, sku_code FROM dim_product")
    sku_ids = {code: sid for sid, code in cursor.fetchall()}

    ensure_dim_date(cursor, conn, fact["period"].unique())

    cursor.execute("SELECT date_id, period FROM dim_date")
    date_ids = {period: did for did, period in cursor.fetchall()}

    cursor.execute("SELECT store_id FROM dim_store WHERE store_code = %s", (STORE_CODE,))
    row = cursor.fetchone()
    if row is None:
        raise SystemExit(f"store_code {STORE_CODE!r} is not in dim_store — "
                         "run sql/schema.sql first")
    store_id = row[0]

    # ---- fact_sales --------------------------------------------------------
    fact["sku_id"] = fact["sku_code"].map(sku_ids)
    fact["date_id"] = fact["period"].map(date_ids)
    fact["store_id"] = store_id

    unmatched = fact[fact["sku_id"].isna() | fact["date_id"].isna()]
    if len(unmatched):
        raise SystemExit(
            "Some fact rows don't map to dim_product / dim_date — aborting "
            "rather than loading a partial month:\n"
            + unmatched.head(10).to_string())

    cursor.executemany("""
        INSERT INTO fact_sales (sku_id, date_id, store_id, order_count, qty, amount)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            order_count = VALUES(order_count),
            qty = VALUES(qty),
            amount = VALUES(amount)
    """, list(fact[["sku_id", "date_id", "store_id", "order_count", "qty", "amount"]]
              .itertuples(index=False, name=None)))
    conn.commit()
    print(f"fact_sales: {len(fact)} rows written")

    # ---- reconciliation ----------------------------------------------------
    periods = tuple(fact["period"].unique())
    placeholders = ",".join(["%s"] * len(periods))
    cursor.execute(f"""
        SELECT SUM(f.amount) FROM fact_sales f
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period IN ({placeholders})
    """, periods)
    in_db = cursor.fetchone()[0] or 0

    print(f"\nReconciliation for {', '.join(periods)}")
    print(f"  in MySQL   {float(in_db):>12,.2f}")
    print(f"  in CSV     {fact['amount'].sum():>12,.2f}")
    if abs(float(in_db) - fact["amount"].sum()) > 0.01:
        print("  !! mismatch — check for duplicate rows before trusting the report")
    else:
        print("  match")

    cursor.execute("SELECT COUNT(*) FROM dim_product")
    print(f"\ndim_product now holds {cursor.fetchone()[0]} SKUs "
          "(this is the memory that shrinks future manual work)")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()

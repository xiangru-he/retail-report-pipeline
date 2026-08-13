"""
Step 10 — load fact_channel into MySQL.

INPUT   data/work/fact_channel.csv
OUTPUT  rows in fact_channel

Must run AFTER step 08, which is what creates any missing dim_date rows.
Running it first would fail the date_id lookup on a brand-new month.
"""
import pandas as pd

import db
from config import STORE_CODE, describe, work_path


def main():
    print(describe())
    fact = pd.read_csv(work_path("fact_channel.csv"))

    conn = db.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT date_id, period FROM dim_date")
    date_ids = {period: did for did, period in cursor.fetchall()}

    cursor.execute("SELECT store_id FROM dim_store WHERE store_code = %s", (STORE_CODE,))
    row = cursor.fetchone()
    if row is None:
        raise SystemExit(f"store_code {STORE_CODE!r} is not in dim_store")
    store_id = row[0]

    fact["date_id"] = fact["period"].map(date_ids)
    fact["store_id"] = store_id

    unmatched = fact[fact["date_id"].isna()]
    if len(unmatched):
        raise SystemExit(
            f"dim_date has no row for {sorted(set(unmatched['period']))}. "
            "Run step 08 first — it adds new months.")

    cursor.executemany("""
        INSERT INTO fact_channel
            (date_id, store_id, channel_code, channel_group, order_count, qty, amount)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            channel_group = VALUES(channel_group),
            order_count = VALUES(order_count),
            qty = VALUES(qty),
            amount = VALUES(amount)
    """, list(fact[["date_id", "store_id", "channel_code", "channel_group",
                    "order_count", "qty", "amount"]]
              .itertuples(index=False, name=None)))
    conn.commit()
    print(f"\nfact_channel: {len(fact)} rows written")

    cursor.execute("""
        SELECT d.period, c.channel_group, SUM(c.qty), SUM(c.amount)
        FROM fact_channel c JOIN dim_date d ON c.date_id = d.date_id
        GROUP BY d.period, c.channel_group ORDER BY d.period, c.channel_group
    """)
    print("\nLocal vs export, all months in the database")
    for period, group, qty, amount in cursor.fetchall():
        print(f"  {period}  {group:<7} {int(qty):>7,} units {float(amount):>12,.2f}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()

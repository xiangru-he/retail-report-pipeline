"""
Step 09 — write product_type onto the dim_product rows.

INPUT   data/work/product_types.csv
OUTPUT  dim_product.product_type updated

Must run AFTER step 08: this only updates rows that already exist, so a SKU
that hasn't been inserted yet would silently get no functional type.
"""
import pandas as pd

import db
from config import describe, work_path


def main():
    print(describe())
    types = pd.read_csv(work_path("product_types.csv"))

    conn = db.connect()
    cursor = conn.cursor()

    cursor.executemany(
        "UPDATE dim_product SET product_type = %s WHERE sku_code = %s",
        list(types[["product_type", "sku_code"]].itertuples(index=False, name=None)))
    conn.commit()
    print(f"\nproduct_type set on {cursor.rowcount} row(s)")

    # A SKU present in the CSV but not in dim_product means step 08 didn't run,
    # or ran on a different month's data.
    cursor.execute("SELECT sku_code FROM dim_product")
    in_db = {row[0] for row in cursor.fetchall()}
    missing = set(types["sku_code"]) - in_db
    if missing:
        print(f"!! {len(missing)} SKU(s) aren't in dim_product yet — "
              "run step 08 first")
        print(f"   e.g. {sorted(missing)[:5]}")

    cursor.execute("""
        SELECT product_type, COUNT(*) FROM dim_product
        WHERE category = 'supplement'
        GROUP BY product_type ORDER BY COUNT(*) DESC
    """)
    print("\nFunctional types now in the database")
    for name, n in cursor.fetchall():
        print(f"  {name:<18} {n:>4}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()

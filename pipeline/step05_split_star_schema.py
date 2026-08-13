"""
Step 05 — split the classified sheet into a dimension and a fact table.

INPUT   data/work/classified.csv
OUTPUT  data/work/dim_product.csv    one row per SKU: what the product IS
        data/work/fact_sales.csv     one row per (SKU, month): what it SOLD

WHY BOTHER
----------
classified.csv is a hybrid: product attributes sitting next to monthly figures
spread across columns (mar_order, mar_qty, mar_amt). Fine for a human to read,
wrong shape for storage — adding May would mean adding columns to a table that
already has rows.

Unpivoting into (sku, month) rows means new months arrive as new rows and the
schema never changes. That's the whole reason the monthly load is a two-line
upsert rather than a migration.

SPARSE BY DESIGN
----------------
A SKU with no sales in a month gets no row, rather than a row of zeros. SUM()
ignores a row that isn't there, which is the same answer, and it keeps the fact
table proportional to actual activity: February has roughly half the rows of
January because half the catalogue didn't move.
"""
import pandas as pd

from config import MONTHS, describe, work_path


def main():
    print(describe())
    df = pd.read_csv(work_path("classified.csv"))

    # ---- dimension: attributes only, no figures ---------------------------
    dim = df[["sku_code", "brand", "product_desc",
              "category", "tier", "shipping_channel"]].drop_duplicates("sku_code")
    dim.to_csv(work_path("dim_product.csv"), index=False, encoding="utf-8-sig")

    # ---- fact: one row per SKU per month ----------------------------------
    frames = []
    for prefix, period in MONTHS:
        chunk = df[["sku_code", f"{prefix}_order", f"{prefix}_qty", f"{prefix}_amt"]].copy()
        chunk.columns = ["sku_code", "order_count", "qty", "amount"]
        chunk["period"] = period
        # Blank in the source means "didn't sell", not "sold zero".
        chunk = chunk.dropna(subset=["order_count", "qty", "amount"], how="all")
        frames.append(chunk)

    fact = pd.concat(frames, ignore_index=True)
    fact = fact[["sku_code", "period", "order_count", "qty", "amount"]]
    fact.to_csv(work_path("fact_sales.csv"), index=False, encoding="utf-8-sig")

    print(f"\ndim_product.csv  {len(dim):>5} rows  (distinct SKUs)")
    print(f"fact_sales.csv   {len(fact):>5} rows  (SKU x month with activity)")

    # The unpivot must not lose or invent money.
    fact_total = fact["amount"].sum()
    source_total = df["total_amt"].sum()
    print(f"\nReconciliation")
    print(f"  fact_sales total    {fact_total:>12,.2f}")
    print(f"  classified total    {source_total:>12,.2f}")
    if abs(fact_total - source_total) > 0.01:
        print(f"  !! off by {fact_total - source_total:,.2f} — investigate before loading")
    else:
        print("  match")

    print("\nRows per month")
    for period, group in fact.groupby("period"):
        print(f"  {period}   {len(group):>5} rows   {group['amount'].sum():>12,.2f}")


if __name__ == "__main__":
    main()

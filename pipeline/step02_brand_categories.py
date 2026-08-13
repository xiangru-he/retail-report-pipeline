"""
Step 02 — maintain the brand -> category table, and flag brands nobody has
classified yet.

INPUT   data/work/products.csv
IN/OUT  data/reference/brand_categories.csv    (human-maintained, accumulates)

EXIT 0  nothing to do, carry on
EXIT 2  new brands found — a person has to fill them in before step 03

Category can't be inferred reliably from a product name, and getting it wrong
propagates into every chart, so unknown brands stop the run instead of being
guessed at.

TWO THINGS THIS FILE IS CAREFUL ABOUT
-------------------------------------
1. It never overwrites a classification you've already made. The first version
   rebuilt the `confirmed_category` column from a dictionary in the source
   code each run, which silently blanked every brand that had been filled in
   by hand — about 25 of them — so they had to be redone every month.

2. It keeps brands that had no sales this month, with n_sku = 0. Not every
   brand sells every month; if the table only held brands present in the
   current file it would shrink each run, and a brand that skipped a month
   would come back as "new" and get asked about again. Classification is a
   one-time decision and shouldn't be affected by monthly sales noise.
"""
import difflib
import os

import pandas as pd

from config import CATEGORIES, EXCLUDED_CATEGORY, describe, reference_path, work_path

BRAND_FILE = reference_path("brand_categories.csv")
VALID_VALUES = CATEGORIES + [EXCLUDED_CATEGORY]

COLUMNS = ["brand_variants", "n_sku", "total_amt",
           "sample_product", "confirmed_category"]


def load_previous():
    """Previously confirmed categories, keyed by every spelling variant seen.

    Returns (mapping, dataframe or None). `brand_variants` holds slash-joined
    spellings ("Solwave/SOLWAVE"), so each variant gets its own key.
    """
    if not os.path.exists(BRAND_FILE):
        return {}, None

    prev = pd.read_csv(BRAND_FILE)
    mapping = {}
    for _, row in prev.iterrows():
        category = str(row.get("confirmed_category", "")).strip()
        if not category or category.lower() == "nan":
            continue
        for variant in str(row["brand_variants"]).split("/"):
            mapping[variant.strip().lower()] = category
    return mapping, prev


def main():
    print(describe())
    products = pd.read_csv(work_path("products.csv"))
    products["brand_key"] = products["brand"].astype(str).str.lower().str.strip()

    grouped = products.groupby("brand_key").agg(
        brand_variants=("brand", lambda s: "/".join(sorted(set(s)))),
        n_sku=("sku_code", "count"),
        total_amt=("total_amt", "sum"),
        sample_product=("product_desc", "first"),
    ).reset_index()

    previous, prev_df = load_previous()
    grouped["confirmed_category"] = grouped["brand_key"].map(
        lambda key: previous.get(key, ""))

    new_brands = grouped[grouped["confirmed_category"] == ""].copy()
    grouped = grouped.drop(columns=["brand_key"]).sort_values(
        "total_amt", ascending=False)[COLUMNS]

    # Carry forward brands that didn't sell this month (see note 2 up top).
    if prev_df is not None:
        current = set()
        for variants in grouped["brand_variants"]:
            current.update(v.strip().lower() for v in str(variants).split("/"))

        carried = []
        for _, row in prev_df.iterrows():
            variants = {v.strip().lower() for v in str(row["brand_variants"]).split("/")}
            if variants & current:
                continue
            record = row.to_dict()
            record["n_sku"] = 0
            record["total_amt"] = 0.0
            carried.append(record)

        if carried:
            grouped = pd.concat(
                [grouped, pd.DataFrame(carried)[grouped.columns]], ignore_index=True)
            print(f"({len(carried)} brand(s) had no sales this month; "
                  "their classification is kept)")

    grouped.to_csv(BRAND_FILE, index=False, encoding="utf-8-sig")
    print(f"\n{len(grouped)} brands -> data/reference/brand_categories.csv")
    print(f"{len(previous)} reused a category confirmed earlier")

    if new_brands.empty:
        print("\nNo new brands. Nothing to decide here — carry on to step 03.")
        return 0

    print(f"\n{len(new_brands)} brand(s) have no category yet:")
    known_keys = list(previous.keys())
    for _, row in new_brands.sort_values("total_amt", ascending=False).iterrows():
        print(f"\n  - {row['brand_variants']}   "
              f"({row['n_sku']} SKUs, ${row['total_amt']:,.2f})")
        print(f"    example: {str(row['sample_product'])[:58]}")
        close = difflib.get_close_matches(row["brand_key"], known_keys, n=2, cutoff=0.8)
        if close:
            print(f"    looks close to {close} — is this a misspelling "
                  "of a brand you already have?")

    print(f"\nOpen data/reference/brand_categories.csv and fill in "
          f"confirmed_category for those {len(new_brands)} row(s).")
    print(f"Allowed values: {' / '.join(VALID_VALUES)}")
    print("Then run step 03.")
    return 2   # "needs a human" — run_import.py stops on this


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)

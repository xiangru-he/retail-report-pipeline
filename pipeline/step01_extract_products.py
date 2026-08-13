"""
Step 01 — parse the raw sales spreadsheet into one tidy row per SKU.

INPUT   data/raw/<period>.xlsx
OUTPUT  data/work/products.csv        real product lines, parsed
        data/work/excluded_rows.csv   freight / discount / gift lines

The POS export puts everything in the product-name column:

    [SKU1137] [Clearfield]Whole Milk Powder (800g){Standard Freight}
     ^code     ^brand      ^description            ^freight tag (optional)

so this step pulls those four pieces apart.

It deliberately does NOT decide export vs local here. That depends on the
SKU's *final* category, which isn't known until step 04 (a brand-level default
can be overridden per SKU). An earlier version decided it here from the brand
name alone and mislabelled a supplement line as in-store pickup purely because
the same brand also sells milk powder.

Rows that aren't products — freight charges, discounts, gift lines — are split
into their own file rather than dropped silently, so they can be eyeballed.
"""
import re

import pandas as pd

from config import (MONTHS, RAW_SALES_FILE, describe, raw_path, work_path)

# [code] [brand]rest-of-the-name
PRODUCT_PATTERN = re.compile(r"^\[([^\]]+)\]\s*\[([^\]]+)\]\s*(.*)$")
# {Express Freight} at the end of the description
FREIGHT_TAG_PATTERN = re.compile(r"\{([^}]+)\}")

# SKU codes that mean "this line isn't a product"
NON_PRODUCT_PREFIXES = ("IFFSHIP", "DIS", "FREEGIFT", "TOPUP", "EWALLET")


def extract_freight_tag(desc):
    m = FREIGHT_TAG_PATTERN.search(str(desc))
    return m.group(1) if m else ""


def main():
    print(describe())
    df = pd.read_excel(raw_path(RAW_SALES_FILE), header=None)

    # row 0-1 headers, row 2 store total, last row grand total
    body = df.iloc[3:-1].copy()

    # Column names follow config.MONTHS rather than being hard-coded, so the
    # same code reads a single-month file or a whole-quarter one.
    month_cols = []
    for prefix, _period in MONTHS:
        month_cols += [f"{prefix}_order", f"{prefix}_qty", f"{prefix}_amt"]
    total_cols = ["total_order", "total_qty", "total_amt"]

    # The export normally ends with a total block — for a single month that
    # block just repeats the month's figures. Sheets without it are accepted
    # too: the width depends on how the export was requested, which isn't
    # something the pipeline controls, and failing on it would mean editing
    # config to read a file that is perfectly readable.
    narrow = ["product_name"] + month_cols
    wide = narrow + total_cols

    if len(body.columns) == len(wide):
        body.columns = wide
    elif len(body.columns) == len(narrow):
        body.columns = narrow
        # Synthesise the block the downstream steps expect. For one month the
        # total *is* that month; for several it's their sum. Deriving it here
        # keeps steps 02-06 from each having to know which shape they were given.
        for suffix in ("order", "qty", "amt"):
            body[f"total_{suffix}"] = sum(
                pd.to_numeric(body[f"{prefix}_{suffix}"], errors="coerce").fillna(0)
                for prefix, _period in MONTHS)
        print(f"  no total block in the sheet — derived it from "
              f"{len(MONTHS)} month column set(s)")
    else:
        raise SystemExit(
            f"Column count mismatch: the sheet has {len(body.columns)} columns.\n"
            f"  configured : {[p for _, p in MONTHS]} ({len(MONTHS)} month(s))\n"
            f"  file       : {RAW_SALES_FILE}\n"
            f"  expected   : {len(narrow)} (no total block) "
            f"or {len(wide)} (with one)\n"
            "If the sheet covers a different set of months, set RPT_PERIOD or "
            "MONTHS to match it."
        )

    body["product_name"] = (body["product_name"].astype(str)
                            .str.replace(r"\s+", " ", regex=True).str.strip())

    parsed = body["product_name"].apply(
        lambda s: PRODUCT_PATTERN.match(s).groups()
        if PRODUCT_PATTERN.match(s) else (None, None, s))
    body["sku_code"] = parsed.apply(lambda t: t[0])
    body["brand_raw"] = parsed.apply(lambda t: t[1])
    body["product_desc"] = parsed.apply(lambda t: t[2])

    # No SKU code at all (single-bracket discount lines) counts as non-product too.
    is_non_product = (
        body["sku_code"].isna()
        | body["sku_code"].astype(str).str.startswith(NON_PRODUCT_PREFIXES)
    )
    excluded, kept = body[is_non_product].copy(), body[~is_non_product].copy()

    kept["brand"] = kept["brand_raw"].str.strip()
    kept["freight_tag"] = kept["product_desc"].apply(extract_freight_tag)
    # Strip the tag out of the description now that it lives in its own column.
    kept["product_desc"] = (kept["product_desc"]
                            .str.replace(FREIGHT_TAG_PATTERN, "", regex=True).str.strip())

    out_cols = (["sku_code", "brand", "product_desc", "freight_tag"]
                + month_cols + ["total_order", "total_qty", "total_amt"])
    kept[out_cols].sort_values(["brand", "sku_code"]).to_csv(
        work_path("products.csv"), index=False, encoding="utf-8-sig")
    excluded[["product_name", "total_order", "total_qty", "total_amt"]].to_csv(
        work_path("excluded_rows.csv"), index=False, encoding="utf-8-sig")

    print(f"\n{len(kept)} product rows  -> data/work/products.csv")
    print(f"{len(excluded)} non-product rows -> data/work/excluded_rows.csv")

    print(f"\nBrands seen: {kept['brand'].str.lower().str.strip().nunique()}")
    print("\nFreight tags (blank = in-store pickup):")
    tags = kept["freight_tag"].replace("", "(none)").value_counts()
    for tag, n in tags.items():
        print(f"  {tag:<20} {n:>4}")

    if len(excluded):
        print("\nExcluded lines:")
        for name in excluded["product_name"].head(8):
            print(f"  {str(name)[:66]}")


if __name__ == "__main__":
    main()

"""
Step 04 — settle each SKU's category, tier and shipping mode.

INPUT   data/work/products.csv
        data/reference/brand_categories.csv, sku_overrides.csv
        dim_product (if reachable)
OUTPUT  data/work/classified.csv
        data/work/excluded_products.csv

PRECEDENCE, HIGHEST FIRST
-------------------------
  1. already in dim_product   — settled on a previous run, reuse verbatim
  2. sku_overrides.csv        — a person decided this SKU is an exception
  3. brand default / rules    — brand_categories.csv for category,
                                tier_rules.py for premium vs regular

Rule 1 is what makes the monthly workload shrink. A SKU's classification never
changes once set, so re-deriving it would at best waste time and at worst
produce a different answer than the one already in the database and in every
report issued so far.

Rule 1 also means the database is authoritative, not the CSVs. If the database
can't be reached the step still runs — everything is derived from scratch,
which gives the same answers for the same inputs, just with no shortcut.

SHIPPING MODE
-------------
Only meaningful for milk powder: everything else is not_applicable. It's
derived from the freight tag, which is why it can't be decided in step 01 —
the category has to be final first.
"""
import os

import pandas as pd

import db
import tier_rules
from config import (CATEGORIES, EXCLUDED_CATEGORY, EXPORT_TAGS,
                    describe, reference_path, work_path)


def shipping_for(category, freight_tag):
    """export / local / not_applicable.

    A milk-powder line with no freight tag was collected in store; with a tag
    it was shipped. Unrecognised tags are passed through as other:<tag> so they
    show up in the sanity check instead of being quietly bucketed.
    """
    if category != "milk_powder":
        return "not_applicable"
    tag = "" if pd.isna(freight_tag) else str(freight_tag).strip()
    if tag == "":
        return "local"
    if tag in EXPORT_TAGS:
        return "export"
    return f"other:{tag}"


def main():
    print(describe())
    products = pd.read_csv(work_path("products.csv"))
    brands = pd.read_csv(reference_path("brand_categories.csv"))
    overrides = pd.read_csv(reference_path("sku_overrides.csv"))

    products["brand_key"] = products["brand"].astype(str).str.lower().str.strip()

    # ---- what the database already knows -----------------------------------
    known, db_error = db.load_known_skus_safe()
    if db_error:
        print(f"\n(database unavailable — classifying everything from scratch: "
              f"{db_error})")
    else:
        print(f"\ndim_product already classifies {len(known)} SKUs; reusing those")

    seen = products["sku_code"].astype(str).isin(known.keys())
    print(f"This month: {len(products)} SKUs — {seen.sum()} known, {(~seen).sum()} new")

    def from_db(row, field):
        return known.get(str(row["sku_code"]), {}).get(field)

    # ---- category ----------------------------------------------------------
    variant_to_category = {}
    for _, row in brands.iterrows():
        category = str(row.get("confirmed_category", "")).strip()
        category = "" if category.lower() == "nan" else category
        for variant in str(row["brand_variants"]).split("/"):
            variant_to_category[variant.strip().lower()] = category

    override_category = dict(zip(overrides["sku_code"].astype(str),
                                 overrides["override_category"])) if len(overrides) else {}

    def resolve_category(row):
        return (from_db(row, "category")
                or override_category.get(str(row["sku_code"]))
                or variant_to_category.get(row["brand_key"], ""))

    products["category"] = products.apply(resolve_category, axis=1)
    products["was_overridden"] = products["sku_code"].astype(str).isin(override_category)

    # ---- shipping mode (needs the final category) --------------------------
    products["shipping_channel"] = products.apply(
        lambda r: from_db(r, "shipping_channel")
        or shipping_for(r["category"], r["freight_tag"]), axis=1)

    # ---- tier --------------------------------------------------------------
    def resolve_tier(row):
        from_database = from_db(row, "tier")
        if from_database:
            return from_database
        tier, _reason = tier_rules.classify(
            row["brand"], row["product_desc"], row["freight_tag"])
        return tier

    products["tier"] = products.apply(resolve_tier, axis=1)

    # Brand spellings that were merged by similarity rather than matched
    # exactly. A wrong merge shifts the premium share with nothing else to
    # show for it, so it always gets printed.
    if tier_rules.fuzzy_matches:
        merges = sorted(set(tier_rules.fuzzy_matches))
        print(f"\n{len(merges)} brand spelling(s) matched by similarity — check these:")
        for raw, matched, ratio in merges:
            print(f"    {raw!r} treated as {matched!r} (ratio {ratio})")
        print("    If that's wrong, fix the spelling upstream or adjust "
              "FUZZY_THRESHOLD in tier_rules.py")

    if tier_rules.unknown_tags:
        print(f"\nFreight tags not seen before: {sorted(tier_rules.unknown_tags)}")
        print("    Add them to EXPORT_TAGS in config.py and tier_rules.py "
              "if they mean 'shipped'")

    # ---- split off non-products, sanity-check the rest ---------------------
    is_excluded = products["category"] == EXCLUDED_CATEGORY
    excluded, kept = products[is_excluded].copy(), products[~is_excluded].copy()

    unclassified = kept[~kept["category"].isin(CATEGORIES)]
    if len(unclassified):
        print(f"\n!! {len(unclassified)} SKU(s) have no valid category — "
              "fix before continuing:")
        print(unclassified[["sku_code", "brand", "product_desc", "category"]]
              .to_string(index=False))

    odd_shipping = kept[kept["shipping_channel"].str.startswith("other:")]
    if len(odd_shipping):
        print(f"\n!! {len(odd_shipping)} SKU(s) carry an unrecognised freight tag:")
        print(odd_shipping[["sku_code", "brand", "shipping_channel"]]
              .to_string(index=False))

    month_cols = [c for c in products.columns
                  if c.endswith(("_order", "_qty", "_amt")) and not c.startswith("total")]
    out_cols = (["sku_code", "brand", "product_desc", "category", "tier",
                 "shipping_channel", "was_overridden"]
                + month_cols + ["total_order", "total_qty", "total_amt"])

    kept[out_cols].sort_values(["category", "tier", "brand"]).to_csv(
        work_path("classified.csv"), index=False, encoding="utf-8-sig")
    excluded[["sku_code", "brand", "product_desc", "total_amt"]].to_csv(
        work_path("excluded_products.csv"), index=False, encoding="utf-8-sig")

    print(f"\n{len(kept)} SKUs -> data/work/classified.csv")
    if len(excluded):
        print(f"{len(excluded)} excluded -> data/work/excluded_products.csv")
    print(f"{products['was_overridden'].sum()} used a SKU-level override")

    print("\nRevenue by category")
    by_cat = kept.groupby("category")["total_amt"].sum().sort_values(ascending=False)
    for cat, amt in by_cat.items():
        print(f"  {cat:<14} {amt:>12,.2f}")
    print(f"  {'TOTAL':<14} {by_cat.sum():>12,.2f}")

    print("\nPremium vs regular (milk powder is reported as its own bucket, "
          "so its tier flag isn't meaningful on its own)")
    bucket = kept.apply(
        lambda r: "milk_powder" if r["category"] == "milk_powder" and not r["was_overridden"]
        else r["tier"], axis=1)
    for name, amt in kept.groupby(bucket)["total_amt"].sum().sort_values(
            ascending=False).items():
        print(f"  {name:<14} {amt:>12,.2f}")

    print("\nShipping mode (export/local should only appear on milk powder)")
    for name, amt in kept.groupby("shipping_channel")["total_amt"].sum().items():
        print(f"  {name:<16} {amt:>12,.2f}")


if __name__ == "__main__":
    main()

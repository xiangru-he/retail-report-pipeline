"""
Step 06 — sort supplements into functional types (fish oil, CoQ10, probiotic...).

INPUT   data/work/classified.csv
OUTPUT  data/work/product_types.csv     sku_code -> product_type

WHY A SECOND CLASSIFICATION
---------------------------
"Supplements" is 40% of revenue and far too coarse to act on. The question a
buyer actually asks is "how is fish oil doing against CoQ10", which needs a
level below category.

Scope is supplements only; everything else gets not_applicable, the same way
shipping mode only applies to milk powder.

OVERLAPS
--------
A combined formula can match several types (a CoQ10 + lecithin product). The
first match in TYPE_RULES wins, so the order of that list is the priority
order, not decoration.

Anything that doesn't match a listed type becomes other_supplement rather than
being forced into the nearest one — a mis-assigned SKU would distort exactly
the comparison this exists to support.
"""
import re

import pandas as pd

from config import describe, work_path

# Order matters: first match wins for combined formulas.
TYPE_RULES = [
    ("fish_oil",      [r"fish oil", r"omega"]),
    ("coq10",         [r"coq10", r"co-?enzyme q10"]),
    ("liver_support", [r"liver"]),
    ("probiotic",     [r"probiotic"]),
    ("calcium",       [r"calcium"]),
    ("magnesium",     [r"magnesium"]),
    ("propolis",      [r"propolis"]),
    ("joint_care",    [r"joint", r"glucosamine"]),
    ("multivitamin",  [r"multivitamin", r"multi-?vit"]),
    ("lecithin",      [r"lecithin"]),
    ("eye_care",      [r"lutein", r"eye health"]),
]
COMPILED = [(name, re.compile("|".join(pats), re.IGNORECASE))
            for name, pats in TYPE_RULES]

CATCH_ALL = "other_supplement"
NOT_APPLICABLE = "not_applicable"


def product_type_for(category, desc):
    if category != "supplement":
        return NOT_APPLICABLE
    for name, pattern in COMPILED:
        if pattern.search(str(desc)):
            return name
    return CATCH_ALL


def main():
    print(describe())
    df = pd.read_csv(work_path("classified.csv"))
    df["product_type"] = df.apply(
        lambda r: product_type_for(r["category"], r["product_desc"]), axis=1)

    df[["sku_code", "product_type"]].to_csv(
        work_path("product_types.csv"), index=False, encoding="utf-8-sig")
    print(f"\n{len(df)} SKUs -> data/work/product_types.csv")

    supplements = df[df["category"] == "supplement"]
    print(f"\nFunctional types across {len(supplements)} supplement SKUs")
    counts = supplements["product_type"].value_counts()
    for name, n in counts.items():
        revenue = supplements.loc[supplements["product_type"] == name, "total_amt"].sum()
        print(f"  {name:<18} {n:>4} SKUs   {revenue:>11,.2f}")

    catch_all = counts.get(CATCH_ALL, 0)
    if catch_all > len(supplements) * 0.4:
        print(f"\n  Note: {catch_all}/{len(supplements)} supplements fell through to "
              f"{CATCH_ALL}.")
        print("  If a real line keeps landing there, add it to TYPE_RULES — the "
              "point of this step is the comparison, and a big unnamed bucket "
              "weakens it.")


if __name__ == "__main__":
    main()

"""
Step 03 — flag SKUs whose product name disagrees with their brand's category.

INPUT   data/work/products.csv, data/reference/brand_categories.csv
OUTPUT  data/work/sku_review.csv        every SKU with a verdict
IN/OUT  data/reference/conflict_reviewed.csv   decisions you've already made

EXIT 0  nothing new to look at
EXIT 2  new conflicts — somebody has to decide before step 04

WHY
---
Category is assigned per brand, but brands don't respect category boundaries.
The real case that motivated this: a supplements brand also sold goat milk
powder, and those lines carried ~90% of the brand's revenue. Classified by
brand alone they landed in the wrong bucket and the category split was wrong
by thousands of dollars, with nothing anywhere to indicate a problem.

So every product name is scanned for category keywords and compared with the
brand's default. A disagreement is reported, never auto-resolved: the keyword
rules are a heuristic for *finding* candidates, not an authority.

MOST CONFLICTS ARE NOISE, AND THAT'S THE HARD PART
--------------------------------------------------
Propolis toothpaste contains "propolis" (a supplement word) but is skincare.
Immune-support milk powder contains "immune" but is milk powder. On the real
data ~26 of 28 conflicts were this kind of collision, and they recur every
single month — enough to bury the one or two that matter.

Two things stop that:
  · decisions recorded in conflict_reviewed.csv are not raised again
  · SKUs already in dim_product are skipped entirely — their classification
    was settled long ago and a keyword has no standing to reopen it

What's left is genuinely new product lines.
"""
import os
import re

import pandas as pd

import db
from config import CATEGORIES, EXCLUDED_CATEGORY, describe, reference_path, work_path

REVIEWED_FILE = reference_path("conflict_reviewed.csv")
BRAND_FILE = reference_path("brand_categories.csv")

# Deliberately crude. These exist to surface candidates for a human, so a false
# positive costs a glance while a false negative costs a wrong report.
KEYWORD_RULES = {
    "milk_powder": [r"milk powder", r"infant formula", r"goat milk", r"whole milk",
                    r"skim milk", r"formula stage"],
    "supplement": [r"vitamin", r"capsule", r"tablet", r"omega", r"fish oil",
                   r"propolis", r"probiotic", r"coq10", r"lecithin", r"glucosamine",
                   r"magnesium", r"multivitamin", r"lutein", r"immune", r"chewable"],
    "honey": [r"\bhoney\b", r"manuka", r"umf"],
    "skincare": [r"cream", r"lotion", r"serum", r"\bmask\b", r"toothpaste",
                 r"cleanser", r"ointment", r"moisturis"],
    "souvenir": [r"cushion", r"plush", r"\btoy\b", r"keyring", r"magnet",
                 r"slippers", r"blanket", r"souvenir", r"gift set"],
    "chocolate": [r"chocolate"],
}
COMPILED = {cat: re.compile("|".join(pats), re.IGNORECASE)
            for cat, pats in KEYWORD_RULES.items()}


def keyword_guess(desc):
    """Category suggested by the product name: a category, 'ambiguous:a+b',
    or "" when nothing matched.

    Empty string rather than None on purpose. Returning None means pandas
    decides what to store, and it doesn't decide the same way on every
    version — on one it stays None in an object column, on another it becomes
    a float NaN. Downstream then does `.startswith` on a float and the run
    dies several steps in. A sentinel of the same type as every other value
    removes the question.
    """
    hits = [cat for cat, pattern in COMPILED.items() if pattern.search(str(desc))]
    if not hits:
        return ""
    if len(hits) == 1:
        return hits[0]
    return "ambiguous:" + "+".join(sorted(hits))


def verdict(brand_category, guess):
    if brand_category == EXCLUDED_CATEGORY:
        return "excluded"
    if not brand_category:
        return "brand_not_classified"
    # Belt and braces: this reads values that have been through a DataFrame
    # and possibly a CSV round-trip, so anything non-string means "no match".
    if not isinstance(guess, str) or not guess:
        return "no_keyword_match"
    if guess.startswith("ambiguous"):
        return f"CONFLICT - name matches several categories ({guess}) vs brand={brand_category}"
    if guess == brand_category:
        return "match"
    return f"CONFLICT - name suggests {guess}, brand default is {brand_category}"


def main():
    print(describe())
    products = pd.read_csv(work_path("products.csv"))
    brands = pd.read_csv(BRAND_FILE)

    variant_to_category = {}
    for _, row in brands.iterrows():
        category = str(row.get("confirmed_category", "")).strip()
        category = "" if category.lower() == "nan" else category
        for variant in str(row["brand_variants"]).split("/"):
            variant_to_category[variant.strip().lower()] = category

    products["brand_key"] = products["brand"].astype(str).str.lower().str.strip()
    products["brand_category"] = products["brand_key"].map(variant_to_category).fillna("")
    products["keyword_guess"] = products["product_desc"].apply(keyword_guess)
    products["verdict"] = products.apply(
        lambda r: verdict(r["brand_category"], r["keyword_guess"]), axis=1)

    out_cols = ["sku_code", "brand", "product_desc", "freight_tag",
                "brand_category", "keyword_guess", "verdict", "total_amt"]
    products[out_cols].sort_values(["verdict", "brand"]).to_csv(
        work_path("sku_review.csv"), index=False, encoding="utf-8-sig")
    print(f"\n{len(products)} SKUs -> data/work/sku_review.csv")

    conflicts = products[products["verdict"].str.startswith("CONFLICT")]
    unclassified = products[products["verdict"] == "brand_not_classified"]

    # ---- what have we already settled? ------------------------------------
    reviewed = set()
    if os.path.exists(REVIEWED_FILE):
        rv = pd.read_csv(REVIEWED_FILE)
        if len(rv):
            reviewed = set(rv["sku_code"].astype(str))

    known_in_db, db_error = db.load_known_skus_safe()
    if db_error:
        print(f"(database unavailable, judging new-vs-old from "
              f"conflict_reviewed.csv only: {db_error})")
    else:
        print(f"({len(known_in_db)} SKUs already classified in dim_product — skipped)")

    # A SKU with an override has already been dealt with — the override is the
    # decision. Re-raising it every month would train you to ignore this list.
    overrides = set()
    override_file = reference_path("sku_overrides.csv")
    if os.path.exists(override_file):
        ov = pd.read_csv(override_file)
        if len(ov):
            overrides = set(ov["sku_code"].astype(str))

    settled = reviewed | set(known_in_db) | overrides
    is_new = ~conflicts["sku_code"].astype(str).isin(settled)
    new_conflicts = conflicts[is_new]

    print(f"\n{len(conflicts)} conflict(s), {len(conflicts) - len(new_conflicts)} "
          "already settled")

    if len(unclassified):
        print(f"{len(unclassified)} SKU(s) belong to a brand with no category — "
              "finish step 02 first")

    if new_conflicts.empty:
        print("\nNo new conflicts. Nothing to decide — carry on to step 04.")
        return 0

    print(f"\n{len(new_conflicts)} new conflict(s) need a decision:\n")
    print(new_conflicts[["sku_code", "brand", "product_desc",
                         "brand_category", "keyword_guess", "total_amt"]]
          .to_string(index=False))

    print("\nAsk: is this product *really* something other than its brand's category?")
    print("  · Just a word collision (propolis toothpaste, immune milk powder)")
    print(f"    -> add the sku_code to {os.path.relpath(REVIEWED_FILE)} "
          "with decision 'brand_default'")
    print("  · Genuinely a different category (a supplements brand's milk powder)")
    print("    -> add it to data/reference/sku_overrides.csv with the right category,")
    print("       and note it in conflict_reviewed.csv so it stops being raised")
    print(f"\nValid categories: {' / '.join(CATEGORIES)}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)

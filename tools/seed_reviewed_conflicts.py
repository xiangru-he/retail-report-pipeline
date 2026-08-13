"""
seed_reviewed_conflicts.py — one-off: pre-answer the demo's word-collision
conflicts so a fresh clone runs cleanly.

The keyword check in step 03 flags any product whose name mentions another
category. Most of those are collisions rather than mistakes — "Immune Support
Milk Powder" contains a supplement word but is milk powder, "Propolis
Toothpaste" is skincare. On real data 26 of 28 flags were this kind.

In normal use you answer each one once and it stops coming back. For the demo
those answers ship with the repo, otherwise the first thing a reviewer meets
is ten questions about products they've never heard of.

Deliberately not pre-answered:
  · the genuine misfile (a Fernvale supplement under a milk-powder brand) —
    that one is handled by sku_overrides.csv, which is the mechanism worth
    showing
  · anything from the brand that first appears in April — that month is meant
    to demonstrate the checkpoint firing

Run after regenerating the dataset:
    python tools/make_synthetic_data.py
    python tools/seed_reviewed_conflicts.py
"""
import os
import subprocess
import sys
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

REVIEWED = os.path.join(ROOT, "data", "reference", "conflict_reviewed.csv")
OVERRIDES = os.path.join(ROOT, "data", "reference", "sku_overrides.csv")

# Only these months are pre-answered. April is left alone on purpose.
SEED_MONTHS = ["2026-01", "2026-02", "2026-03"]


def conflicts_for(period):
    env = dict(os.environ, RPT_PERIOD=period,
               PYTHONPATH=os.path.join(ROOT, "pipeline"))
    for script in ("step01_extract_products.py", "step03_check_conflicts.py"):
        subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", script)],
                       cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    review = pd.read_csv(os.path.join(ROOT, "data", "work", "sku_review.csv"))
    return review[review["verdict"].str.startswith("CONFLICT")]


def main():
    overrides = set()
    if os.path.exists(OVERRIDES):
        ov = pd.read_csv(OVERRIDES)
        if len(ov):
            overrides = set(ov["sku_code"].astype(str))

    found = {}
    for period in SEED_MONTHS:
        for _, row in conflicts_for(period).iterrows():
            sku = str(row["sku_code"])
            if sku in overrides or sku in found:
                continue
            found[sku] = {
                "sku_code": sku,
                "brand": row["brand"],
                "product_desc": row["product_desc"],
                "decision": "brand_default",
                "reviewed_on": date.today().isoformat(),
                "note": f"name mentions {row['keyword_guess']}; "
                        f"the product is {row['brand_category']}",
            }

    out = pd.DataFrame(list(found.values()),
                       columns=["sku_code", "brand", "product_desc",
                                "decision", "reviewed_on", "note"])
    out.to_csv(REVIEWED, index=False, encoding="utf-8-sig")

    print(f"Pre-answered {len(out)} word-collision conflicts "
          f"across {', '.join(SEED_MONTHS)}")
    print(f"Left for the operator: {len(overrides)} genuine misfile(s) "
          "handled via sku_overrides.csv")
    if len(out):
        print()
        print(out[["sku_code", "brand", "product_desc"]].to_string(index=False))


if __name__ == "__main__":
    main()

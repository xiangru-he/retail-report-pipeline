"""
make_synthetic_data.py — generate the demo dataset shipped with this repo.

WHY THIS EXISTS
---------------
The pipeline was built for a real store. Its sales figures, SKU list and
supplier mix are the owner's commercial data and can't be published, so the
repo ships a synthetic dataset instead: same *shape*, same seasonal story,
invented numbers and invented brand names.

WHAT IS PRESERVED (so the demo still exercises every code path)
---------------------------------------------------------------
  · Four monthly files (Jan–Apr 2026), one Excel pair per month
  · The seasonal story: February collapses (Chinese New Year freight
    shutdown), March rebounds, April holds — this is what the narrative
    layer has to reason about
  · Category mix (supplements / milk powder / honey / skincare / souvenirs
    / chocolate) and roughly the real SKU-count-per-category ratios
  · The messy bits the pipeline exists to handle:
        - brand names with inconsistent casing  (Solwave / SOLWAVE)
        - a brand that spans two categories     (Fernvale: supplements + milk powder)
        - freight and discount rows that must be excluded
        - export vs local shipping tags in the product name
  · A brand appearing for the first time in April, so the "new brand needs
    a human decision" checkpoint actually triggers in the demo

WHAT IS FAKE
------------
  · Every number (drawn around the real shape, then jittered)
  · Every brand name, product name and the store name

HOW TO RUN
----------
    python tools/make_synthetic_data.py

Writes into data/raw/:
    2026-1.xlsx  2026-1p.xlsx      (sales detail / channel split)
    2026-2.xlsx  2026-2p.xlsx
    2026-3.xlsx  2026-3p.xlsx
    2026-4.xlsx  2026-4p.xlsx

Deterministic: same seed in, same files out.
"""
import os
import random

import numpy as np
import pandas as pd

SEED = 20260501
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")

STORE_NAME = "Kea Wellness - Central"

# ---------------------------------------------------------------------------
# Monthly totals. These follow the real store's shape:
#   Jan strong (pre-CNY export rush) → Feb collapse (freight shutdown during
#   the Chinese New Year holiday) → Mar rebound → Apr steady.
# The narrative layer has to spot and explain that February dip, so the demo
# data has to actually contain it.
# ---------------------------------------------------------------------------
MONTH_TARGETS = {
    #                orders  amount     local_qty  export_qty
    "2026-01": dict(orders=510, amount=88_500.0, local_qty=1100, export_qty=1265),
    "2026-02": dict(orders=285, amount=50_900.0, local_qty=1000, export_qty=759),
    "2026-03": dict(orders=440, amount=79_200.0, local_qty=1240, export_qty=1230),
    "2026-04": dict(orders=455, amount=80_600.0, local_qty=1265, export_qty=1300),
}

# Channel volumes above are set so the month-on-month movement matches the real
# store's, because that contrast is the whole point of the channel slide:
#
#     Jan -> Feb   export  -40.0%   local  -9.1%
#     Feb -> Mar   export  +62.1%   local +24.0%
#
# Export collapses during the Chinese New Year freight shutdown while local
# walk-in trade barely moves. A reader should be able to see from the chart
# alone that the two channels respond to completely different things — and the
# narrative layer has to arrive at that reading on its own.

# ---------------------------------------------------------------------------
# Invented brands. Category mix and SKU counts echo the real store, but every
# name here is made up.
#   is_premium_brand : the whole brand is "premium" (the store's own push list)
#   first_seen       : brand only appears from this month onward — used to make
#                      the "new brand" human checkpoint fire in the demo
# ---------------------------------------------------------------------------
BRANDS = [
    # ---- supplements ----
    ("Solwave",        "supplement", 22, True),
    ("Northlight",     "supplement", 18, True),
    ("Vireo Labs",     "supplement", 15, False),
    ("Baycrest",       "supplement", 14, False),
    ("Puriri Health",  "supplement", 12, False),
    ("Tasman Vitality","supplement", 11, False),
    ("Aroha Nutrition","supplement",  9, False),
    ("Kowhai Care",    "supplement",  8, False),
    ("Riverstone Bio", "supplement",  7, True),
    ("Halcyon",        "supplement",  6, False),
    # ---- milk powder ----
    ("Clearfield",     "milk_powder", 16, False),
    ("Ambervale",      "milk_powder", 12, False),
    ("Two Rivers",     "milk_powder",  9, False),
    ("Fernvale",       "milk_powder",  8, False),   # also sells supplements
    ("Highmoor",       "milk_powder",  6, False),
    ("Westbrook",      "milk_powder",  5, True),
    # ---- honey ----
    ("Manuka Ridge",   "honey",       14, True),
    ("Golden Vale",    "honey",       11, True),
    ("Hivewood",       "honey",        8, True),
    ("Beechline",      "honey",        5, False),
    # ---- skincare ----
    ("Lanolux",        "skincare",    13, True),
    ("Pounamu Skin",   "skincare",    11, True),
    ("Silverfern",     "skincare",     9, False),
    ("Cove & Clay",    "skincare",     8, False),
    ("Tui Botanicals", "skincare",     7, False),
    # ---- souvenirs ----
    ("Southern Craft", "souvenir",    24, True),
    ("Kiwiana Co",     "souvenir",    18, True),
    ("Harbour Wool",   "souvenir",    14, True),
    ("Piko Gifts",     "souvenir",    11, True),
    # ---- chocolate ----
    ("Cocoa Bay",      "chocolate",   13, True),
    ("Rata Confection","chocolate",    9, False),
]

# Brand that only shows up in April — triggers the "new brand, please classify"
# checkpoint when a reviewer runs the demo month by month.
NEW_BRAND_APRIL = ("Coastline Apiary", "honey", 3, False)

PRODUCT_WORDS = {
    "supplement": [
        ("Omega 3 Fish Oil {n}mg", [500, 1000, 1500]),
        ("CoQ10 {n}mg", [100, 150, 200]),
        ("Calcium + Vitamin D {n}s", [60, 120, 200]),
        ("Liver Support Complex {n}s", [30, 60, 90]),
        ("Probiotic Daily {n}s", [30, 60]),
        ("Joint Care Glucosamine {n}s", [90, 180]),
        ("Multivitamin Adult {n}s", [60, 120]),
        ("Lecithin {n}mg", [1200, 1500]),
        ("Eye Health Lutein {n}s", [30, 60]),
        ("Propolis Extract {n}s", [60, 120]),
        ("Magnesium Complex {n}s", [60, 90]),
    ],
    "milk_powder": [
        ("Whole Milk Powder ({n}g)", [800, 1000]),
        ("Skim Milk Powder ({n}g)", [800, 1000]),
        ("Immune Support Milk Powder ({n}g)", [900]),
        ("Digestion Support Milk Powder ({n}g)", [800]),
        ("Infant Formula Stage 1 ({n}g)", [900]),
        ("Infant Formula Stage 2 ({n}g)", [900]),
        ("Goat Milk Powder ({n}g)", [450, 800]),
    ],
    "honey": [
        ("Manuka Honey UMF 5+ ({n}g)", [250, 500]),
        ("Manuka Honey UMF 10+ ({n}g)", [250, 500]),
        ("Manuka Honey UMF 15+ ({n}g)", [250]),
        ("Clover Honey ({n}g)", [500, 1000]),
        ("Honey Gift Set ({n}g x4)", [250]),
    ],
    "skincare": [
        ("Lanolin Moisturising Cream ({n}ml)", [100, 150]),
        ("Night Repair Serum ({n}ml)", [30, 50]),
        ("Facial Cleanser ({n}ml)", [100, 150]),
        ("Hand Cream ({n}ml)", [50, 75]),
        ("Propolis Toothpaste ({n}g)", [100]),
        ("Sheep Placenta Cream ({n}ml)", [100]),
    ],
    "souvenir": [
        ("Wool Cushion Cover ({n}cm)", [40, 45]),
        ("Plush Kiwi Toy ({n}cm)", [15, 25]),
        ("Souvenir Keyring", [0]),
        ("Fridge Magnet Set", [0]),
        ("Sheepskin Slippers", [0]),
        ("Wool Throw Blanket", [0]),
    ],
    "chocolate": [
        ("Dark Chocolate Block {n}% ({n2}g)", [70, 85]),
        ("Milk Chocolate Block ({n}g)", [180, 250]),
        ("Chocolate Gift Pouch ({n}g)", [125, 180]),
    ],
}

# Rough price band per category, NZD. Keeps totals plausible.
PRICE_BAND = {
    "supplement": (18, 65),
    "milk_powder": (28, 130),
    "honey": (25, 140),
    "skincare": (8, 45),
    "souvenir": (6, 60),
    "chocolate": (5, 22),
}

EXPORT_TAGS = ["Express Freight", "Standard Freight", "15-Day Express"]

# Non-product rows the pipeline has to recognise and exclude. Keeping them in
# the demo data means step1's exclusion logic is actually exercised.
NOISE_ROWS = [
    ("[IFFSHIP01] [Freight]Free Shipping $0", 0.0),
    ("[IFFSHIP02] [Freight]Extra Charge $1", 27.75),
    ("[IFFSHIP07] [Freight]Overseas $8", 1_334.40),
    ("[DIS15] $5 off your order", -425.00),
    ("[DIS19] Free gift - fish oil", -207.20),
    ("[FREEGIFT] In-store gift", -34.66),
    ("[EWALLET001] [TOPUP]E-Wallet Payment", -24.90),
]


def build_catalogue(rng):
    """One row per SKU: code, brand (with casing noise), description, tags."""
    rows = []
    seq = 1000
    all_brands = BRANDS + [NEW_BRAND_APRIL]

    for brand, category, n_sku, is_premium in all_brands:
        templates = PRODUCT_WORDS[category]
        for i in range(n_sku):
            name_tpl, sizes = templates[i % len(templates)]
            size = rng.choice(sizes) if sizes else 0
            desc = name_tpl.replace("{n2}", str(rng.choice([180, 250])))
            desc = desc.replace("{n}", str(size)) if size else desc.replace(" ({n}g)", "")

            # Milk powder splits into "local pickup" (no freight tag) and
            # "export" (tagged in the product name) — the pipeline derives
            # shipping_channel from exactly this.
            tag = ""
            if category == "milk_powder" and rng.random() < 0.55:
                tag = rng.choice(EXPORT_TAGS)

            # Casing noise on some brands, mimicking the real export where the
            # same brand appears as both "Celifix" and "CELIFIX".
            shown_brand = brand
            if brand in ("Solwave", "Lanolux", "Kiwiana Co") and rng.random() < 0.3:
                shown_brand = brand.upper()

            seq += 1
            rows.append({
                "sku_code": f"SKU{seq}",
                "brand": shown_brand,
                "brand_key": brand,
                "category": category,
                "desc": desc,
                "tag": tag,
                "is_premium_brand": is_premium,
                "price": round(rng.uniform(*PRICE_BAND[category]), 2),
                "first_month": "2026-04" if brand == NEW_BRAND_APRIL[0] else "2026-01",
            })

    # One brand that genuinely spans two categories — the real store had this
    # (a supplement brand that also sells goat milk powder) and it's the reason
    # the SKU-level override mechanism exists.
    for i in range(2):
        seq += 1
        rows.append({
            "sku_code": f"SKU{seq}",
            "brand": "Fernvale",
            "brand_key": "Fernvale",
            "category": "supplement",          # brand default is milk_powder
            "desc": f"Kids Vitamin C Chewable {60 + i * 30}s",
            "tag": "",
            "is_premium_brand": False,
            "price": round(rng.uniform(*PRICE_BAND["supplement"]), 2),
            "first_month": "2026-01",
        })

    return pd.DataFrame(rows)


def product_name(row):
    """Rebuild the raw '[CODE] [Brand]Description【tag】' string that the
    store's POS export produces — step1 parses exactly this format."""
    # Freight tag is wrapped in {} so it can't be confused with the two
    # [..] groups that hold the SKU code and the brand. The real POS uses
    # CJK brackets 【】 for this; the English pipeline uses {}.
    tag = f"{{{row['tag']}}}" if row["tag"] else ""
    return f"[{row['sku_code']}] [{row['brand']}]{row['desc']}{tag}"


def month_sales(catalogue, period, target, rng):
    """Draw one month of per-SKU sales that add up close to the target."""
    active = catalogue[catalogue["first_month"] <= period].copy()

    # Not every SKU sells every month. February sells fewer lines too — the
    # store was effectively closed for export during the holiday.
    sell_rate = 0.42 if period == "2026-02" else 0.55
    active["sells"] = rng.random(len(active)) < sell_rate

    # Export-tagged milk powder is what actually collapses in February.
    if period == "2026-02":
        exp = active["tag"] != ""
        active.loc[exp, "sells"] &= rng.random(exp.sum()) < 0.35

    # A brand making its debut must actually sell in that month, otherwise
    # the "new brand needs classifying" checkpoint only fires by luck — with
    # three SKUs at a 55% sell rate it silently misses about one run in ten.
    active.loc[active["first_month"] == period, "sells"] = True

    sold = active[active["sells"]].copy()
    if sold.empty:
        sold = active.head(20).copy()

    weight = rng.uniform(0.4, 2.2, len(sold))
    raw_amt = sold["price"].to_numpy() * weight * rng.uniform(1, 6, len(sold))
    sold["amount"] = np.round(raw_amt * (target["amount"] / raw_amt.sum()), 2)

    # Unit counts are scaled to hit local_qty + export_qty exactly, so the
    # per-SKU sheet and the channel sheet agree on the month's total.
    target_qty = target["local_qty"] + target["export_qty"]
    raw_qty = np.maximum(1, sold["amount"] / sold["price"])
    sold["qty"] = np.maximum(1, np.round(raw_qty * target_qty / raw_qty.sum())).astype(int)

    order_w = rng.uniform(0.5, 1.5, len(sold))
    sold["orders"] = np.maximum(
        1, np.round(order_w * target["orders"] / order_w.sum())).astype(int)

    return sold[["sku_code", "brand", "desc", "tag", "orders", "qty", "amount"]]


def write_sales_excel(path, period_label, sold, catalogue, rng):
    """Write the wide single-month layout the store's system exports:
       row0 header, row1 sub-header, row2 store total, rows..., last row Total."""
    lines = []
    for _, r in sold.iterrows():
        cat_row = catalogue[catalogue["sku_code"] == r["sku_code"]].iloc[0]
        lines.append([product_name(cat_row), r["orders"], r["qty"], r["amount"]])

    for label, amt in NOISE_ROWS:
        jitter = round(amt * rng.uniform(0.8, 1.2), 2) if amt else 0.0
        lines.append([label, rng.integers(1, 6), rng.integers(0, 8), jitter])

    rng.shuffle(lines)
    tot_o = int(sum(x[1] for x in lines))
    tot_q = int(sum(x[2] for x in lines))
    tot_a = round(sum(x[3] for x in lines), 2)

    # Seven columns, matching the real export: product name, then the month's
    # order / quantity / amount, then a "Total" block. For a single-month
    # export the total block simply repeats the month — the system emits it
    # either way, so the synthetic file does too.
    out = [
        ["Column0", period_label, "Column2", "Column3", "Total", "Column5", "Column6"],
        [np.nan, "Order", "Product Quantity", "Total Price",
         "Order", "Product Quantity", "Total Price"],
        [STORE_NAME, tot_o, tot_q, tot_a, tot_o, tot_q, tot_a],
    ]
    for name, o, q, a in lines:
        out.append([name, o, q, a, o, q, a])
    out.append(["Total", tot_o, tot_q, tot_a, tot_o, tot_q, tot_a])

    pd.DataFrame(out).to_excel(path, index=False, header=False)
    return tot_o, tot_q, tot_a


def write_channel_excel(path, period_label, totals, period, target, rng):
    """Channel sheet: local (member + wholesale) vs export (GST-free + WeChat).

    Volumes come straight from MONTH_TARGETS so the month-on-month movement is
    designed rather than whatever falls out of the per-SKU draw.
    """
    tot_o, tot_q, tot_a = totals
    local_q, export_q = target["local_qty"], target["export_qty"]

    # Amount follows quantity, but export skews to higher-value goods
    # (milk powder), so it earns a bit more per unit than local trade.
    export_value_weight = 1.35
    export_a = tot_a * (export_q * export_value_weight) / (
        local_q + export_q * export_value_weight)
    local_a = tot_a - export_a

    local_o = max(1, int(round(tot_o * local_q / (local_q + export_q))))
    export_o = tot_o - local_o

    rows = [
        ["Member Price (NZD)",             round(local_o * 0.62),  round(local_q * 0.62),  round(local_a * 0.62, 2)],
        ["Wholesale (NZD)",                None,                   None,                   None],
        ["Export Price (GST Free) (NZD)",  round(export_o * 0.78), round(export_q * 0.78), round(export_a * 0.78, 2)],
        ["WeChat Pay (CNY) (NZD)",         None,                   None,                   None],
    ]
    # The two "remainder" channels absorb rounding so the columns still add up.
    rows[1][1:] = [local_o - rows[0][1], local_q - rows[0][2], round(local_a - rows[0][3], 2)]
    rows[3][1:] = [export_o - rows[2][1], export_q - rows[2][2], round(export_a - rows[2][3], 2)]

    for name, o, q, a in rows:
        assert o > 0 and q > 0 and a > 0, f"{name} came out non-positive: {o}/{q}/{a}"

    # This channel exists in the source system but has never been used.
    rows.append(["Courier Export (Free Shipping) (NZD)", np.nan, np.nan, np.nan])

    out = [
        ["Column0", period_label, "Column2", "Column3", "Total", "Column5", "Column6"],
        [np.nan, "Order", "Product Quantity", "Total Price",
         "Order", "Product Quantity", "Total Price"],
    ]
    for name, o, q, a in rows:
        out.append([name, o, q, a, o, q, a])
    out.append(["Total", tot_o, tot_q, tot_a, tot_o, tot_q, tot_a])

    pd.DataFrame(out).to_excel(path, index=False, header=False)


def write_reference_files(catalogue):
    """Seed the human-maintained files so the repo is runnable out of the box.

    Deliberately NOT seeded: the brand that first appears in April. Leaving it
    out is what makes the "new brand needs a decision" checkpoint actually fire
    when someone runs the demo month by month — otherwise that whole part of
    the design is invisible.
    """
    ref_dir = os.path.join(os.path.dirname(OUT_DIR), "reference")
    os.makedirs(ref_dir, exist_ok=True)

    # ---- brand -> category ------------------------------------------------
    rows = []
    for brand, category, _n, _prem in BRANDS:
        variants = sorted(set(catalogue.loc[catalogue["brand_key"] == brand, "brand"]))
        rows.append({
            "brand_variants": "/".join(variants) if variants else brand,
            "n_sku": int((catalogue["brand_key"] == brand).sum()),
            "total_amt": 0.0,
            "sample_product": catalogue.loc[
                catalogue["brand_key"] == brand, "desc"].iloc[0],
            "confirmed_category": category,
        })
    pd.DataFrame(rows).to_csv(os.path.join(ref_dir, "brand_categories.csv"),
                              index=False, encoding="utf-8-sig")

    # ---- SKU-level category exceptions ------------------------------------
    # Fernvale's brand default is milk_powder, but it also sells two supplement
    # lines. This is exactly the case the override mechanism exists for.
    odd = catalogue[(catalogue["brand_key"] == "Fernvale")
                    & (catalogue["category"] == "supplement")]
    pd.DataFrame([{
        "sku_code": r.sku_code,
        "override_category": "supplement",
        "reason": "Fernvale defaults to milk_powder; this line is a supplement",
    } for r in odd.itertuples()]).to_csv(
        os.path.join(ref_dir, "sku_overrides.csv"), index=False, encoding="utf-8-sig")

    # ---- reviewed keyword conflicts (starts empty) -------------------------
    pd.DataFrame(columns=["sku_code", "brand", "product_desc",
                          "decision", "reviewed_on", "note"]).to_csv(
        os.path.join(ref_dir, "conflict_reviewed.csv"),
        index=False, encoding="utf-8-sig")

    # ---- monthly operating context ----------------------------------------
    # None of this comes from the POS; the store manager types it in each month.
    # February is quiet for the same reason exports stop — the holiday.
    context = [
        ("2026-01", 268, 94, 61, "no", "",
         "Summer bundle: 3 for 10% off across premium supplements"),
        ("2026-02", 176, 51, 47, "no", "",
         "Chinese New Year gift packs, in-store only"),
        ("2026-03", 231, 88, 59, "no", "",
         "Premium supplements 3 for 10% off, buy 5 get 1 free, free shipping"),
        ("2026-04", 244, 96, 63, "yes", "12-14 Apr, tour group of 30",
         "Autumn health check promo; new honey range launch"),
    ]
    pd.DataFrame(context, columns=[
        "period", "foot_traffic", "miniprogram_leads", "miniprogram_completion_rate",
        "study_tour_flag", "study_tour_note", "activity_description",
    ]).to_csv(os.path.join(ref_dir, "monthly_context.csv"),
              index=False, encoding="utf-8-sig")

    print("\nSeeded reference files in data/reference/")
    print(f"  brand_categories.csv   {len(rows)} brands "
          "(Coastline Apiary left out on purpose - it appears in April)")
    print(f"  sku_overrides.csv      {len(odd)} SKU-level exceptions")
    print("  monthly_context.csv    4 months")
    print("  conflict_reviewed.csv  empty")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(SEED)
    random.seed(SEED)

    catalogue = build_catalogue(rng)
    print(f"Catalogue: {len(catalogue)} SKUs across "
          f"{catalogue['brand_key'].nunique()} brands\n")

    month_names = {"2026-01": "January 2026", "2026-02": "February 2026",
                   "2026-03": "March 2026", "2026-04": "April 2026"}

    print(f"{'month':<10}{'orders':>8}{'qty':>9}{'amount':>14}   note")
    print("-" * 62)
    for period, target in MONTH_TARGETS.items():
        stem = f"{period[:4]}-{int(period[5:7])}"
        sold = month_sales(catalogue, period, target, rng)

        totals = write_sales_excel(
            os.path.join(OUT_DIR, f"{stem}.xlsx"), month_names[period],
            sold, catalogue, rng)
        write_channel_excel(
            os.path.join(OUT_DIR, f"{stem}p.xlsx"), month_names[period],
            totals, period, target, rng)

        note = {"2026-02": "Chinese New Year - export freight paused",
                "2026-03": "rebound",
                "2026-04": "new brand appears (Coastline Apiary)"}.get(period, "")
        print(f"{period:<10}{totals[0]:>8,}{totals[1]:>9,}{totals[2]:>14,.2f}   {note}")

    write_reference_files(catalogue)
    print(f"\nWrote 8 spreadsheets to {os.path.relpath(OUT_DIR)}/")


if __name__ == "__main__":
    main()

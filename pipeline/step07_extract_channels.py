"""
Step 07 — read the channel spreadsheet into one row per (channel, month).

INPUT   data/raw/<period>p.xlsx
OUTPUT  data/work/fact_channel.csv

This file is store-wide and one level up from the SKU sheet: five payment /
fulfilment channels, no product detail. It answers a different question —
how much of the month went out the door versus over the counter.

Local vs export is the split that matters:
    local   Member Price, Wholesale                — walk-in and trade
    export  Export Price (GST Free), WeChat Pay,   — parcels leaving NZ
            Courier Export
Those two behave nothing alike. Export is exposed to cross-border freight and
collapses when it stops; local walk-in trade barely notices.
"""
import pandas as pd

from config import MONTHS, RAW_CHANNEL_FILE, describe, raw_path, work_path

# Sheet label -> stable code. The labels carry payment-method wording that
# changes; the codes are what everything downstream uses.
CHANNEL_CODES = {
    "Member Price (NZD)": "member_price",
    "Wholesale (NZD)": "wholesale",
    "Export Price (GST Free) (NZD)": "export_gst_free",
    "WeChat Pay (CNY) (NZD)": "wechat_pay",
    "Courier Export (Free Shipping) (NZD)": "courier_export",
}

CHANNEL_GROUP = {
    "member_price": "local",
    "wholesale": "local",
    "export_gst_free": "export",
    "wechat_pay": "export",
    "courier_export": "export",
}


def main():
    print(describe())
    df = pd.read_excel(raw_path(RAW_CHANNEL_FILE), header=None)

    # rows 0-1 headers, rows 2-6 the five channels, last row the total
    rows = df.iloc[2:7].copy()

    month_cols = []
    for prefix, _period in MONTHS:
        month_cols += [f"{prefix}_order", f"{prefix}_qty", f"{prefix}_amt"]

    # Same two shapes as the sales sheet: normally a trailing total block,
    # occasionally not. See step01 for the reasoning.
    narrow = ["channel_name"] + month_cols
    wide = narrow + ["total_order", "total_qty", "total_amt"]

    if len(rows.columns) == len(wide):
        rows.columns = wide
    elif len(rows.columns) == len(narrow):
        rows.columns = narrow
        for suffix in ("order", "qty", "amt"):
            rows[f"total_{suffix}"] = sum(
                pd.to_numeric(rows[f"{prefix}_{suffix}"], errors="coerce").fillna(0)
                for prefix, _period in MONTHS)
    else:
        raise SystemExit(
            f"Column count mismatch: the channel sheet has {len(rows.columns)} "
            f"columns.\n"
            f"  configured : {[p for _, p in MONTHS]} ({len(MONTHS)} month(s))\n"
            f"  file       : {RAW_CHANNEL_FILE}\n"
            f"  expected   : {len(narrow)} (no total block) or {len(wide)} (with one)"
        )

    rows["channel_name"] = rows["channel_name"].astype(str).str.strip()
    rows["channel_code"] = rows["channel_name"].map(CHANNEL_CODES)

    unknown = rows[rows["channel_code"].isna()]
    if len(unknown):
        raise SystemExit(
            "These channel labels aren't in CHANNEL_CODES — add them before "
            "continuing, otherwise their revenue silently disappears:\n"
            + unknown[["channel_name"]].to_string(index=False)
        )

    frames = []
    for prefix, period in MONTHS:
        chunk = rows[["channel_code", f"{prefix}_order",
                      f"{prefix}_qty", f"{prefix}_amt"]].copy()
        chunk.columns = ["channel_code", "order_count", "qty", "amount"]
        chunk["period"] = period
        chunk = chunk.dropna(subset=["order_count", "qty", "amount"], how="all")
        frames.append(chunk)

    fact = pd.concat(frames, ignore_index=True)
    fact["channel_group"] = fact["channel_code"].map(CHANNEL_GROUP)
    fact = fact[["period", "channel_code", "channel_group",
                 "order_count", "qty", "amount"]]
    fact.to_csv(work_path("fact_channel.csv"), index=False, encoding="utf-8-sig")

    print(f"\n{len(fact)} rows -> data/work/fact_channel.csv")
    print("\nLocal vs export")
    for (period, group), sub in fact.groupby(["period", "channel_group"]):
        print(f"  {period}  {group:<7} {sub['qty'].sum():>7,.0f} units "
              f"{sub['amount'].sum():>12,.2f}")


if __name__ == "__main__":
    main()

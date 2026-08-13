"""
Step 12 — run every query the report needs and save the answers as JSON.

INPUT   MySQL
OUTPUT  data/work/report_data.json

Everything downstream — charts, slides, the LLM narrative — reads this one
file. Nothing else touches the database, so every part of the report is
looking at the same numbers by construction rather than by discipline.

TWO RULES THIS FILE ENFORCES
----------------------------
1. TRENDS STOP AT THE REPORTING MONTH.
   Every trend query carries `period <= rpt_period`. Without it, building
   March's report while April is already loaded pulls April into the trend
   charts, and the narrative starts describing a month the report isn't about.
   Nothing errors; the deck just quietly describes the wrong period.

2. DERIVED NUMBERS ARE COMPUTED HERE, ONCE.
   Month-on-month percentages live in `computed`. They are not recalculated by
   the chart script, the deck script, or the language model. An earlier version
   let the model derive them from raw monthly totals and it produced
   percentages that appeared nowhere in the data. Now the arithmetic happens in
   one place that can be tested, and the model is explicitly forbidden from
   doing any of its own.
"""
import json

import datetime
import decimal

import db
from config import STORE_CODE, TREND_MONTHS, describe, work_path


def json_safe(value):
    """Convert a MySQL value into something JSON can hold and arithmetic works on.

    SUM() and ROUND() come back as decimal.Decimal, and DATE columns as
    datetime.date. Neither is JSON-serialisable, and the tempting fix —
    json.dump(default=str) — turns them into strings rather than failing.
    That produces a file that looks completely normal and blows up two steps
    later on `'int' + 'str'`, in a chart renderer that has nothing to do with
    the cause.

    Converting at the boundary means the JSON only ever contains numbers,
    strings and nulls, and every consumer can rely on that.
    """
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def rows_as_dicts(cursor, sql, params=()):
    cursor.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [{col: json_safe(val) for col, val in zip(columns, row)}
            for row in cursor.fetchall()]


def to_float(value):
    return float(value) if value is not None else None


def mom_percent(series):
    """[(a→b)%, (b→c)%, ...] — the only place month-on-month is computed."""
    out = []
    for i in range(1, len(series)):
        previous, current = series[i - 1], series[i]
        out.append(round((current - previous) / previous * 100, 2) if previous else 0.0)
    return out


def month_label(period):
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(period[5:7]) - 1]} {period[:4]}"


def main():
    print(describe())
    conn = db.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT rpt_period FROM report_config LIMIT 1")
    row = cursor.fetchone()
    if not row:
        raise SystemExit("report_config is empty — run sql/schema.sql")
    period = row[0]

    cursor.execute("SELECT store_id FROM dim_store WHERE store_code = %s", (STORE_CODE,))
    store = cursor.fetchone()
    if store is None:
        raise SystemExit(f"store_code {STORE_CODE!r} is not in dim_store")
    store_id = store[0]

    data = {"period": period, "period_label": month_label(period),
            "store_code": STORE_CODE, "trend_months": TREND_MONTHS}

    # ---- headline ----------------------------------------------------------
    cursor.execute("""
        SELECT SUM(f.amount), SUM(f.qty), SUM(f.order_count)
        FROM fact_sales f JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period = %s AND f.store_id = %s
    """, (period, store_id))
    total_amount, total_qty, total_orders = cursor.fetchone()
    data["headline"] = {
        "total_amount": to_float(total_amount),
        "total_qty": to_float(total_qty),
        "total_orders": to_float(total_orders),
        "avg_order_value": round(float(total_amount) / float(total_orders), 2)
                           if total_orders else None,
    }

    # Milk powder is reported as its own bucket. Its tier flag is only
    # meaningful for the handful of SKUs with an explicit override, so rolling
    # it into premium/regular would misrepresent both.
    data["headline"]["tiers"] = rows_as_dicts(cursor, """
        SELECT
            CASE WHEN p.category = 'milk_powder' THEN 'milk_powder' ELSE p.tier END
                AS bucket,
            SUM(f.amount) AS amount,
            ROUND(SUM(f.amount) * 100.0 / SUM(SUM(f.amount)) OVER (), 2) AS pct_of_total
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period = %s AND f.store_id = %s
        GROUP BY bucket
    """, (period, store_id))

    # ---- monthly trend (<= reporting month) --------------------------------
    trend = rows_as_dicts(cursor, """
        SELECT d.period,
               CASE WHEN p.category = 'milk_powder' THEN 'milk_powder' ELSE p.tier END
                   AS bucket,
               SUM(f.amount) AS amount, SUM(f.qty) AS qty
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period <= %s AND f.store_id = %s
        GROUP BY d.period, bucket
        ORDER BY d.period, bucket
    """, (period, store_id))
    for r in trend:
        r["amount"], r["qty"] = to_float(r["amount"]), to_float(r["qty"])
        r["period_label"] = month_label(r["period"])
    data["monthly_trend"] = trend

    # ---- category mix ------------------------------------------------------
    categories = rows_as_dicts(cursor, """
        SELECT p.category, SUM(f.amount) AS amount, SUM(f.qty) AS qty
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period = %s AND f.store_id = %s
        GROUP BY p.category ORDER BY amount DESC
    """, (period, store_id))
    cat_amount = sum(float(c["amount"]) for c in categories)
    cat_qty = sum(float(c["qty"]) for c in categories)
    for c in categories:
        c["amount"], c["qty"] = to_float(c["amount"]), to_float(c["qty"])
        c["amount_pct"] = round(c["amount"] * 100 / cat_amount, 1)
        c["qty_pct"] = round(c["qty"] * 100 / cat_qty, 1)
    data["category_mix"] = {"total_amount": cat_amount, "total_qty": cat_qty,
                            "categories": categories}

    # ---- best sellers ------------------------------------------------------
    top = rows_as_dicts(cursor, """
        SELECT p.sku_code, p.brand, p.product_desc, p.category, p.tier,
               SUM(f.qty) AS qty, SUM(f.amount) AS amount
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period = %s AND f.store_id = %s
        GROUP BY p.sku_id ORDER BY qty DESC LIMIT 10
    """, (period, store_id))
    for i, r in enumerate(top, start=1):
        r["rank"], r["qty"], r["amount"] = i, to_float(r["qty"]), to_float(r["amount"])
    data["top_products"] = top
    data["premium_in_top10"] = sum(1 for r in top if r["tier"] == "premium")

    # ---- what the premium range is actually made of ------------------------
    # Percentages here are *within premium*, not of the store. Keeping them in
    # their own block makes that hard to confuse — an earlier layout had both
    # denominators in one dict and the commentary quoted the wrong one.
    premium_mix = rows_as_dicts(cursor, """
        SELECT p.category, SUM(f.amount) AS amount, SUM(f.qty) AS qty
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period = %s AND f.store_id = %s AND p.tier = 'premium'
        GROUP BY p.category ORDER BY amount DESC
    """, (period, store_id))
    premium_amount = sum(r["amount"] for r in premium_mix)
    premium_qty = sum(r["qty"] for r in premium_mix)
    for r in premium_mix:
        r["amount_pct"] = round(r["amount"] * 100 / premium_amount, 1) if premium_amount else 0.0
        r["qty_pct"] = round(r["qty"] * 100 / premium_qty, 1) if premium_qty else 0.0
    data["premium_mix"] = {
        "total_amount": round(premium_amount, 2),
        "total_qty": premium_qty,
        "categories": premium_mix,
    }

    # Three numbers that open the product-structure section.
    leading = premium_mix[0] if premium_mix else None
    data["structure_intro"] = {
        "premium_amount": round(premium_amount, 2),
        "premium_pct_of_store": round(
            premium_amount * 100 / data["headline"]["total_amount"], 1)
            if data["headline"]["total_amount"] else 0.0,
        "leading_premium_category": leading["category"] if leading else None,
        "leading_premium_pct": leading["amount_pct"] if leading else 0.0,
        "premium_in_top10": data["premium_in_top10"],
        "top_n": len(top),
    }

    # ---- brands ------------------------------------------------------------
    brands = rows_as_dicts(cursor, """
        SELECT brand, amount, ROUND(amount * 100.0 / total, 1) AS pct_of_store,
               main_category
        FROM (
            SELECT p.brand, SUM(f.amount) AS amount,
                   SUM(SUM(f.amount)) OVER () AS total,
                   SUBSTRING_INDEX(GROUP_CONCAT(
                       p.category ORDER BY f.amount DESC), ',', 1) AS main_category
            FROM fact_sales f
            JOIN dim_product p ON f.sku_id = p.sku_id
            JOIN dim_date d ON f.date_id = d.date_id
            WHERE d.period = %s AND f.store_id = %s
            GROUP BY p.brand
        ) t ORDER BY amount DESC LIMIT 5
    """, (period, store_id))
    for b in brands:
        b["amount"], b["pct_of_store"] = to_float(b["amount"]), to_float(b["pct_of_store"])
    data["top_brands"] = brands

    # main_category is carried so the narrative can say "top supplement brand"
    # instead of comparing a milk-powder brand against a supplement brand —
    # milk powder has a far higher unit price, so that comparison says nothing.

    # ---- milk powder brands ------------------------------------------------
    milk = rows_as_dicts(cursor, """
        SELECT brand, amount, ROUND(amount * 100.0 / total, 1) AS pct_of_category
        FROM (
            SELECT p.brand, SUM(f.amount) AS amount,
                   SUM(SUM(f.amount)) OVER () AS total
            FROM fact_sales f
            JOIN dim_product p ON f.sku_id = p.sku_id
            JOIN dim_date d ON f.date_id = d.date_id
            WHERE d.period = %s AND f.store_id = %s AND p.category = 'milk_powder'
            GROUP BY p.brand
        ) t ORDER BY amount DESC
    """, (period, store_id))
    for m in milk:
        m["amount"], m["pct_of_category"] = to_float(m["amount"]), to_float(m["pct_of_category"])
    data["milk_powder_brands"] = milk

    # ---- functional types over time ---------------------------------------
    functional = rows_as_dicts(cursor, """
        SELECT d.period, p.product_type, SUM(f.qty) AS qty, SUM(f.amount) AS amount
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period <= %s AND f.store_id = %s
          AND p.product_type NOT IN ('not_applicable', 'other_supplement')
        GROUP BY d.period, p.product_type
        ORDER BY p.product_type, d.period
    """, (period, store_id))
    for r in functional:
        r["qty"], r["amount"] = to_float(r["qty"]), to_float(r["amount"])
        r["period_label"] = month_label(r["period"])
    data["functional_trend"] = functional

    # ---- pickup vs shipped, milk powder only -------------------------------
    pickup = rows_as_dicts(cursor, """
        SELECT d.period, p.tier, SUM(f.amount) AS amount, SUM(f.qty) AS qty
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d ON f.date_id = d.date_id
        WHERE d.period <= %s AND f.store_id = %s
          AND p.category = 'milk_powder' AND p.shipping_channel = 'local'
        GROUP BY d.period, p.tier ORDER BY d.period, p.tier
    """, (period, store_id))
    for r in pickup:
        r["amount"], r["qty"] = to_float(r["amount"]), to_float(r["qty"])
        r["period_label"] = month_label(r["period"])
    data["pickup_tier_trend"] = pickup

    # ---- channel split -----------------------------------------------------
    channel = rows_as_dicts(cursor, """
        SELECT d.period, c.channel_group, SUM(c.qty) AS qty, SUM(c.amount) AS amount,
               ROUND(SUM(c.qty) * 100.0 /
                     SUM(SUM(c.qty)) OVER (PARTITION BY d.period), 1) AS qty_pct
        FROM fact_channel c JOIN dim_date d ON c.date_id = d.date_id
        WHERE d.period <= %s AND c.store_id = %s
        GROUP BY d.period, c.channel_group ORDER BY d.period, c.channel_group
    """, (period, store_id))
    for r in channel:
        r["qty"], r["amount"] = to_float(r["qty"]), to_float(r["amount"])
        r["qty_pct"] = to_float(r["qty_pct"])
        r["period_label"] = month_label(r["period"])
    data["channel_trend"] = channel

    # ---- SKU concentration -------------------------------------------------
    data["sku_pareto"] = [
        {"decile": int(r["decile"]), "decile_amount": to_float(r["decile_amount"]),
         "cumulative_pct": to_float(r["cumulative_pct"])}
        for r in rows_as_dicts(cursor, """
            WITH ranked AS (
                SELECT p.sku_id, SUM(f.amount) AS amount,
                       NTILE(10) OVER (ORDER BY SUM(f.amount) DESC) AS decile
                FROM fact_sales f
                JOIN dim_product p ON f.sku_id = p.sku_id
                JOIN dim_date d ON f.date_id = d.date_id
                WHERE d.period = %s AND f.store_id = %s
                GROUP BY p.sku_id
            ), totals AS (
                SELECT decile, SUM(amount) AS decile_amount FROM ranked GROUP BY decile
            )
            SELECT decile, decile_amount,
                   ROUND(SUM(decile_amount) OVER (ORDER BY decile) * 100.0
                         / SUM(decile_amount) OVER (), 1) AS cumulative_pct
            FROM totals ORDER BY decile
        """, (period, store_id))]

    # ---- operating context -------------------------------------------------
    cursor.execute("""
        SELECT m.foot_traffic, m.miniprogram_leads, m.miniprogram_completion_rate,
               m.study_tour_flag, m.study_tour_note, m.activity_description
        FROM monthly_context m JOIN dim_date d ON m.date_id = d.date_id
        WHERE d.period = %s AND m.store_id = %s
    """, (period, store_id))
    ctx = cursor.fetchone()
    data["operating_context"] = {
        "foot_traffic": ctx[0] if ctx else None,
        "miniprogram_leads": ctx[1] if ctx else None,
        "miniprogram_completion_rate": to_float(ctx[2]) if ctx else None,
        "study_tour_flag": ctx[3] if ctx else None,
        "study_tour_note": ctx[4] if ctx else None,
        "activity_description": ctx[5] if ctx else None,
    }
    if not ctx:
        print(f"\n! monthly_context has no row for {period} — the operating "
              "figures on the deck will be blank.")
        print("  Check data/reference/monthly_context.csv has that month, then run")
        print("    python pipeline/step11_load_monthly_context.py")

    # ---- derived: month-on-month, computed once ----------------------------
    computed = {}

    trend_periods = sorted({r["period"] for r in trend})[-TREND_MONTHS:]
    amount_by_period, qty_by_period = {}, {}
    for r in trend:
        amount_by_period[r["period"]] = amount_by_period.get(r["period"], 0) + r["amount"]
        qty_by_period[r["period"]] = qty_by_period.get(r["period"], 0) + r["qty"]

    computed["trend_periods"] = trend_periods
    computed["trend_labels"] = [month_label(p) for p in trend_periods]
    computed["amount_totals"] = [round(amount_by_period.get(p, 0), 2) for p in trend_periods]
    computed["amount_mom_pct"] = mom_percent(computed["amount_totals"])
    computed["qty_totals"] = [round(qty_by_period.get(p, 0), 2) for p in trend_periods]
    computed["qty_mom_pct"] = mom_percent(computed["qty_totals"])

    channel_periods = sorted({r["period"] for r in channel})[-TREND_MONTHS:]
    local_by = {r["period"]: r["qty"] for r in channel if r["channel_group"] == "local"}
    export_by = {r["period"]: r["qty"] for r in channel if r["channel_group"] == "export"}
    computed["channel_periods"] = channel_periods
    computed["channel_labels"] = [month_label(p) for p in channel_periods]
    computed["local_qty"] = [round(local_by.get(p, 0), 2) for p in channel_periods]
    computed["local_qty_mom_pct"] = mom_percent(computed["local_qty"])
    computed["export_qty"] = [round(export_by.get(p, 0), 2) for p in channel_periods]
    computed["export_qty_mom_pct"] = mom_percent(computed["export_qty"])

    data["computed"] = computed

    with open(work_path("report_data.json"), "w", encoding="utf8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nreport_data.json written for {period}")
    print(f"  revenue        {data['headline']['total_amount']:>12,.2f}")
    print(f"  units          {data['headline']['total_qty']:>12,.0f}")
    print(f"  orders         {data['headline']['total_orders']:>12,.0f}")
    print(f"  trend covers   {computed['trend_labels']}")
    if computed["amount_mom_pct"]:
        print(f"  revenue MoM    {computed['amount_mom_pct']}")
        print(f"  export MoM     {computed['export_qty_mom_pct']}")
        print(f"  local MoM      {computed['local_qty_mom_pct']}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()

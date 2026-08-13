-- ===========================================================================
-- analysis_queries.sql — the report's questions, as standalone SQL
--
-- These are the queries step12_fetch_report_data.py runs. They live there as
-- Python strings because the pipeline needs the results as JSON, but that
-- makes them awkward to read and impossible to try out. This file is the same
-- SQL, runnable directly:
--
--     mysql -u root -p retail_demo < sql/analysis_queries.sql
--
-- The reporting month comes from report_config, so every query below answers
-- "for the month the report is currently set to". Change it once:
--
--     UPDATE report_config SET rpt_period = '2026-03' WHERE config_id = 1;
--
-- and every query here moves with it. Passing the month into each query
-- separately is how you end up with a deck whose charts are on two different
-- months.
-- ===========================================================================

SET @period   = (SELECT rpt_period FROM report_config LIMIT 1);
SET @store_id = (SELECT store_id FROM dim_store WHERE store_code = 'DEMO-CENTRAL');

SELECT CONCAT('Reporting month: ', @period) AS `-- context --`;


-- ---------------------------------------------------------------------------
-- 1. Headline
-- ---------------------------------------------------------------------------
SELECT
    SUM(f.amount)                              AS revenue,
    SUM(f.qty)                                 AS units,
    SUM(f.order_count)                         AS orders,
    ROUND(SUM(f.amount) / SUM(f.order_count), 2) AS avg_order_value
FROM fact_sales f
JOIN dim_date d ON f.date_id = d.date_id
WHERE d.period = @period AND f.store_id = @store_id;


-- ---------------------------------------------------------------------------
-- 2. Revenue split by tier
--
-- Milk powder is pulled out as its own bucket. Its premium/regular flag is
-- only meaningful for the handful of SKUs with an explicit override, so
-- folding it into the other two would misrepresent all three.
--
-- The window function is doing the work here: SUM(SUM(amount)) OVER () gives
-- each group's share of the grand total without a second pass or a subquery.
-- ---------------------------------------------------------------------------
SELECT
    CASE WHEN p.category = 'milk_powder' THEN 'milk_powder' ELSE p.tier END AS bucket,
    SUM(f.amount)                                                AS amount,
    ROUND(SUM(f.amount) * 100.0 / SUM(SUM(f.amount)) OVER (), 2) AS pct_of_total
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period = @period AND f.store_id = @store_id
GROUP BY bucket
ORDER BY amount DESC;


-- ---------------------------------------------------------------------------
-- 3. Monthly trend, stopping at the reporting month
--
-- `d.period <= @period` is the important part. Without it, building March's
-- report once April is loaded pulls April into the trend chart. Nothing
-- errors; the chart just describes a month the report isn't about.
-- ---------------------------------------------------------------------------
SELECT
    d.period,
    CASE WHEN p.category = 'milk_powder' THEN 'milk_powder' ELSE p.tier END AS bucket,
    SUM(f.amount) AS amount,
    SUM(f.qty)    AS qty
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period <= @period AND f.store_id = @store_id
GROUP BY d.period, bucket
ORDER BY d.period, bucket;


-- ---------------------------------------------------------------------------
-- 4. Month-on-month, in SQL
--
-- The pipeline computes this in Python (step 12) so there is exactly one
-- implementation feeding the charts, the slides and the language model. The
-- LAG version is here because it is the natural way to ask the question, and
-- because it is worth being able to check the Python against something.
-- ---------------------------------------------------------------------------
WITH monthly AS (
    SELECT d.period, SUM(f.amount) AS amount, SUM(f.qty) AS qty
    FROM fact_sales f
    JOIN dim_date d ON f.date_id = d.date_id
    WHERE d.period <= @period AND f.store_id = @store_id
    GROUP BY d.period
)
SELECT
    period,
    amount,
    LAG(amount) OVER (ORDER BY period) AS prev_amount,
    ROUND((amount - LAG(amount) OVER (ORDER BY period))
          * 100.0 / LAG(amount) OVER (ORDER BY period), 2) AS amount_mom_pct,
    ROUND((qty - LAG(qty) OVER (ORDER BY period))
          * 100.0 / LAG(qty) OVER (ORDER BY period), 2)    AS qty_mom_pct
FROM monthly
ORDER BY period;


-- ---------------------------------------------------------------------------
-- 5. Category mix — revenue share against unit share
--
-- The gap between the two columns is the unit-price effect. Milk powder
-- typically shows something like 28% of revenue on 17% of units.
-- ---------------------------------------------------------------------------
SELECT
    p.category,
    SUM(f.amount)                                              AS amount,
    SUM(f.qty)                                                 AS qty,
    ROUND(SUM(f.amount) * 100.0 / SUM(SUM(f.amount)) OVER (), 1) AS amount_pct,
    ROUND(SUM(f.qty)    * 100.0 / SUM(SUM(f.qty))    OVER (), 1) AS qty_pct
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period = @period AND f.store_id = @store_id
GROUP BY p.category
ORDER BY amount DESC;


-- ---------------------------------------------------------------------------
-- 6. Best sellers, with the tier flag
--
-- Ranked by units rather than revenue. The store wants to know what walks out
-- of the door; revenue ranking would just list the milk powder.
-- ---------------------------------------------------------------------------
SELECT
    ROW_NUMBER() OVER (ORDER BY SUM(f.qty) DESC) AS rnk,
    p.sku_code, p.brand, p.product_desc, p.category, p.tier,
    SUM(f.qty)    AS qty,
    SUM(f.amount) AS amount
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period = @period AND f.store_id = @store_id
GROUP BY p.sku_id
ORDER BY qty DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- 7. Brands by revenue, with each brand's main category
--
-- main_category exists so the write-up doesn't compare across categories.
-- Milk powder has roughly ten times the unit price of a supplement, so
-- "brand A beat brand B" across the two says nothing.
-- ---------------------------------------------------------------------------
WITH brand_totals AS (
    SELECT
        p.brand,
        SUM(f.amount) AS amount,
        SUM(SUM(f.amount)) OVER () AS store_total
    FROM fact_sales f
    JOIN dim_product p ON f.sku_id = p.sku_id
    JOIN dim_date d    ON f.date_id = d.date_id
    WHERE d.period = @period AND f.store_id = @store_id
    GROUP BY p.brand
),
brand_main_category AS (
    SELECT brand, category,
           ROW_NUMBER() OVER (PARTITION BY brand ORDER BY amount DESC) AS rn
    FROM (
        SELECT p.brand, p.category, SUM(f.amount) AS amount
        FROM fact_sales f
        JOIN dim_product p ON f.sku_id = p.sku_id
        JOIN dim_date d    ON f.date_id = d.date_id
        WHERE d.period = @period AND f.store_id = @store_id
        GROUP BY p.brand, p.category
    ) x
)
SELECT
    t.brand,
    t.amount,
    ROUND(t.amount * 100.0 / t.store_total, 1) AS pct_of_store,
    c.category AS main_category
FROM brand_totals t
JOIN brand_main_category c ON c.brand = t.brand AND c.rn = 1
ORDER BY t.amount DESC
LIMIT 10;


-- ---------------------------------------------------------------------------
-- 8. Milk powder brands — share of the category, not of the store
--
-- Different denominator from query 7 on purpose. Mixing the two is the single
-- easiest way to put a figure on a slide that contradicts its own chart.
-- ---------------------------------------------------------------------------
SELECT
    p.brand,
    SUM(f.amount)                                              AS amount,
    ROUND(SUM(f.amount) * 100.0 / SUM(SUM(f.amount)) OVER (), 1) AS pct_of_category
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period = @period AND f.store_id = @store_id
  AND p.category = 'milk_powder'
GROUP BY p.brand
ORDER BY amount DESC;


-- ---------------------------------------------------------------------------
-- 9. In-store pickups: premium against regular, by month
--
-- shipping_channel = 'local' means the customer collected it. There is no
-- "collected in store" field in the source data — it's inferred from the
-- absence of a freight tag on the product name.
-- ---------------------------------------------------------------------------
SELECT
    d.period,
    p.tier,
    SUM(f.amount) AS amount,
    SUM(f.qty)    AS qty
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period <= @period AND f.store_id = @store_id
  AND p.category = 'milk_powder'
  AND p.shipping_channel = 'local'
GROUP BY d.period, p.tier
ORDER BY d.period, p.tier;


-- ---------------------------------------------------------------------------
-- 10. Functional supplement types over time
--
-- product_type is filled in by a keyword pass over the product name
-- (step 06) and then remembered in dim_product, so it only has to be worked
-- out once per SKU.
-- ---------------------------------------------------------------------------
SELECT
    d.period,
    p.product_type,
    SUM(f.qty)    AS qty,
    SUM(f.amount) AS amount
FROM fact_sales f
JOIN dim_product p ON f.sku_id = p.sku_id
JOIN dim_date d    ON f.date_id = d.date_id
WHERE d.period <= @period AND f.store_id = @store_id
  AND p.category = 'supplement'
  AND p.product_type IS NOT NULL
  AND p.product_type <> 'not_applicable'
GROUP BY d.period, p.product_type
ORDER BY d.period, qty DESC;


-- ---------------------------------------------------------------------------
-- 11. Local against export volume
--
-- These come from a separate export (fact_channel) rather than from
-- fact_sales, because the till system reports channel at order level and not
-- per SKU. The two totals won't tie out exactly, which is expected.
-- ---------------------------------------------------------------------------
SELECT
    d.period,
    c.channel_group,
    SUM(c.qty)                                              AS qty,
    ROUND(SUM(c.qty) * 100.0 /
          SUM(SUM(c.qty)) OVER (PARTITION BY d.period), 1)  AS qty_pct
FROM fact_channel c
JOIN dim_date d ON c.date_id = d.date_id
WHERE d.period <= @period AND c.store_id = @store_id
GROUP BY d.period, c.channel_group
ORDER BY d.period, c.channel_group;


-- ---------------------------------------------------------------------------
-- 12. Revenue concentration by SKU decile
--
-- NTILE splits the SKUs into ten equal-sized groups by revenue, then a running
-- window sum turns that into a cumulative curve. On this data the top decile
-- carries about a third of revenue and the top two carry half.
-- ---------------------------------------------------------------------------
WITH ranked AS (
    SELECT
        p.sku_id,
        SUM(f.amount) AS amount,
        NTILE(10) OVER (ORDER BY SUM(f.amount) DESC) AS decile
    FROM fact_sales f
    JOIN dim_product p ON f.sku_id = p.sku_id
    JOIN dim_date d    ON f.date_id = d.date_id
    WHERE d.period = @period AND f.store_id = @store_id
    GROUP BY p.sku_id
),
by_decile AS (
    SELECT decile, SUM(amount) AS decile_amount, COUNT(*) AS sku_count
    FROM ranked
    GROUP BY decile
)
SELECT
    decile,
    sku_count,
    decile_amount,
    ROUND(SUM(decile_amount) OVER (ORDER BY decile) * 100.0
          / SUM(decile_amount) OVER (), 1) AS cumulative_pct
FROM by_decile
ORDER BY decile;


-- ---------------------------------------------------------------------------
-- 13. Operating context
--
-- Foot traffic, enquiries and campaign notes never touch the till system.
-- Somebody types them into monthly_context.csv each month and step 11 loads
-- them.
-- ---------------------------------------------------------------------------
SELECT
    m.foot_traffic,
    m.miniprogram_leads,
    m.miniprogram_completion_rate,
    m.study_tour_flag,
    m.study_tour_note,
    m.activity_description
FROM monthly_context m
JOIN dim_date d ON m.date_id = d.date_id
WHERE d.period = @period AND m.store_id = @store_id;


-- ===========================================================================
-- Two checks worth running after an import
-- ===========================================================================

-- Anything unclassified will silently distort every category chart.
SELECT 'unclassified SKUs' AS check_name, COUNT(*) AS n
FROM dim_product
WHERE category IS NULL OR category = '';

-- Sales rows whose SKU isn't in dim_product. Should always be zero — the
-- foreign key prevents it — but it costs nothing to be sure after a load.
SELECT 'orphan fact rows' AS check_name, COUNT(*) AS n
FROM fact_sales f
LEFT JOIN dim_product p ON f.sku_id = p.sku_id
WHERE p.sku_id IS NULL;

-- ============================================================
-- Star schema for the monthly retail report.
--
--   dim_product   one row per SKU — what the product IS
--   dim_date      one row per month
--   dim_store     one row per store (a single store today)
--   fact_sales    one row per (SKU, month, store) — what it SOLD
--   fact_channel  one row per (channel, month, store) — store-wide split
--   monthly_context   hand-entered figures that never touch the POS
--   report_config     which month the report scripts are currently building
--
-- Run once:
--     mysql -u root -p < sql/schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS retail_demo
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE retail_demo;


-- ------------------------------------------------------------
-- dim_date
--
-- "period" not "year_month": YEAR_MONTH is a reserved word in MySQL
-- (INTERVAL '1-2' YEAR_MONTH), and a bare column with that name fails the
-- moment you SELECT it directly while appearing to work elsewhere.
--
-- Rows are added automatically by the load step as new months arrive, so
-- there's nothing to maintain here by hand.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_date (
    date_id   INT AUTO_INCREMENT PRIMARY KEY,
    period    CHAR(7)  NOT NULL UNIQUE,      -- 'YYYY-MM'
    year      SMALLINT NOT NULL,
    month     TINYINT  NOT NULL,
    quarter   TINYINT  NOT NULL
) ENGINE=InnoDB;


CREATE TABLE IF NOT EXISTS dim_store (
    store_id    INT AUTO_INCREMENT PRIMARY KEY,
    store_code  VARCHAR(30) NOT NULL UNIQUE,
    store_name  VARCHAR(80) NOT NULL,
    region      VARCHAR(40) DEFAULT NULL
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- dim_product
--
-- Descriptive attributes only — never sales figures.
--
-- This table is also the pipeline's memory. A SKU's classification is decided
-- once and reused on every later run, which is why the amount of manual work
-- shrinks month over month instead of repeating.
--
--   tier              the store's own "do we push this?" flag.
--                     NOT a price band: a $9 souvenir can be premium.
--   shipping_channel  only meaningful for milk_powder; everything else is
--                     not_applicable
--   product_type      functional sub-type, supplements only
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_product (
    sku_id            INT AUTO_INCREMENT PRIMARY KEY,
    sku_code          VARCHAR(30)  NOT NULL UNIQUE,
    brand             VARCHAR(60)  NOT NULL,
    product_desc      VARCHAR(200) NOT NULL,
    category          ENUM('supplement','milk_powder','honey',
                           'skincare','souvenir','chocolate') NOT NULL,
    tier              ENUM('premium','regular') NOT NULL DEFAULT 'regular',
    shipping_channel  ENUM('export','local','not_applicable')
                          NOT NULL DEFAULT 'not_applicable',
    product_type      VARCHAR(30) NOT NULL DEFAULT 'not_applicable',
    INDEX idx_brand (brand),
    INDEX idx_category (category)
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- fact_sales
--
-- Sparse on purpose: a SKU that didn't sell in a month has no row, rather
-- than a row of zeros. SUM() gives the same answer either way, and the table
-- stays proportional to real activity.
--
-- The composite unique key is what makes re-running a month safe — the load
-- is an upsert, so importing the same file twice overwrites rather than
-- duplicates.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_sales (
    sales_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
    sku_id       INT NOT NULL,
    date_id      INT NOT NULL,
    store_id     INT NOT NULL,
    order_count  INT     DEFAULT 0,
    qty          INT     DEFAULT 0,
    amount       DECIMAL(12,2) DEFAULT 0.00,
    UNIQUE KEY uq_sales (sku_id, date_id, store_id),
    FOREIGN KEY (sku_id)   REFERENCES dim_product(sku_id),
    FOREIGN KEY (date_id)  REFERENCES dim_date(date_id),
    FOREIGN KEY (store_id) REFERENCES dim_store(store_id)
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- fact_channel
--
-- Store-wide, one level above the SKU grain: how the month split between
-- walk-in trade and parcels leaving the country. Not derivable from
-- fact_sales, which is why it's a separate table fed by a separate sheet.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_channel (
    channel_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
    date_id        INT NOT NULL,
    store_id       INT NOT NULL,
    channel_code   VARCHAR(30) NOT NULL,
    channel_group  ENUM('local','export') NOT NULL,
    order_count    INT     DEFAULT 0,
    qty            INT     DEFAULT 0,
    amount         DECIMAL(12,2) DEFAULT 0.00,
    UNIQUE KEY uq_channel (date_id, store_id, channel_code),
    FOREIGN KEY (date_id)  REFERENCES dim_date(date_id),
    FOREIGN KEY (store_id) REFERENCES dim_store(store_id)
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- monthly_context
--
-- Foot traffic, campaign notes and so on. None of it comes from the POS —
-- the store manager types it in each month, so it lives in its own table
-- rather than being wedged into a fact table it has nothing to do with.
--
-- Maintained through data/reference/monthly_context.csv. Editing this table
-- directly is a good way to end up with the CSV and the database disagreeing.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monthly_context (
    date_id                      INT NOT NULL,
    store_id                     INT NOT NULL,
    foot_traffic                 INT DEFAULT NULL,
    miniprogram_leads            INT DEFAULT NULL,
    miniprogram_completion_rate  DECIMAL(5,2) DEFAULT NULL,  -- 58.00 means 58%
    study_tour_flag              ENUM('yes','no') NOT NULL DEFAULT 'no',
    study_tour_note              VARCHAR(255) DEFAULT NULL,
    activity_description         TEXT,
    PRIMARY KEY (date_id, store_id),
    FOREIGN KEY (date_id)  REFERENCES dim_date(date_id),
    FOREIGN KEY (store_id) REFERENCES dim_store(store_id)
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- report_config
--
-- A one-row table holding the month currently being reported. It's a table
-- rather than a session variable because the scripts each open their own
-- connection — a @variable set in one is gone in the next, which produced
-- NULLs that looked like missing data rather than an error.
--
-- config_id is fixed at 1 and is the primary key. That's what makes the
-- switch a genuine upsert: without it, "change the month" could insert a
-- second row, and every query does SELECT rpt_period ... LIMIT 1 — so the
-- report would be for whichever row the server returned first.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_config (
    config_id  TINYINT UNSIGNED NOT NULL DEFAULT 1,
    rpt_period CHAR(7) NOT NULL,
    PRIMARY KEY (config_id)
) ENGINE=InnoDB;


-- ------------------------------------------------------------
-- Seed
-- ------------------------------------------------------------
INSERT INTO dim_store (store_code, store_name, region)
SELECT 'DEMO-CENTRAL', 'Kea Wellness - Central', 'Auckland'
WHERE NOT EXISTS (SELECT 1 FROM dim_store WHERE store_code = 'DEMO-CENTRAL');

INSERT INTO report_config (config_id, rpt_period)
VALUES (1, '2026-01')
ON DUPLICATE KEY UPDATE rpt_period = rpt_period;   -- keep an existing setting

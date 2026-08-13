"""
config.py — single place for everything that changes between runs.

Normally you never edit this file. `python monthly.py 2026-05` sets
RPT_PERIOD and the month and filenames are derived from it.

Only edit the FALLBACK block if:
  1. One spreadsheet contains several months (the store's first quarter
     arrived that way), or
  2. The files aren't named to the convention below.

File naming convention (both zero-padded and not are accepted):
    2026-5.xlsx     per-SKU sales detail
    2026-5p.xlsx    channel split  (p = payment/path)
"""
import os

MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]

# ---------------------------------------------------------------------------
# Business vocabulary.
#
# These are the only category / tier / channel values the pipeline knows about.
# They match the MySQL ENUMs exactly, so a value never has to be translated
# between the CSV stage and the database stage — an earlier version of this
# pipeline carried Chinese labels through the CSVs and translated on load,
# which meant every new category had to be added in two places.
# ---------------------------------------------------------------------------
CATEGORIES = ["supplement", "milk_powder", "honey",
              "skincare", "souvenir", "chocolate"]
EXCLUDED_CATEGORY = "excluded"          # gift / non-product rows

TIERS = ["premium", "regular"]          # the store's own "do we push this?" flag
SHIPPING = ["export", "local", "not_applicable"]

# Display names used on charts and slides.
CATEGORY_LABELS = {
    "supplement": "Supplements",
    "milk_powder": "Milk Powder",
    "honey": "Honey",
    "skincare": "Skincare",
    "souvenir": "Souvenirs",
    "chocolate": "Chocolate",
}
TIER_LABELS = {"premium": "Premium", "regular": "Regular", "milk_powder": "Milk Powder"}

PRODUCT_TYPE_LABELS = {
    "fish_oil": "Fish Oil / Omega", "coq10": "CoQ10", "liver_support": "Liver Support",
    "probiotic": "Probiotic", "calcium": "Calcium", "propolis": "Propolis",
    "joint_care": "Joint Care", "multivitamin": "Multivitamin", "lecithin": "Lecithin",
    "eye_care": "Eye Care", "magnesium": "Magnesium",
    "other_supplement": "Other", "not_applicable": "N/A",
}

# Freight tags that appear in the product name. Anything tagged ships out;
# an untagged milk-powder line is in-store pickup.
EXPORT_TAGS = {"Express Freight", "Standard Freight", "15-Day Express"}

# How many months of history the trend charts show.
TREND_MONTHS = 4


def months_for(year, start_month, end_month):
    """Build [(excel column prefix, 'YYYY-MM'), ...]; both ends inclusive.

    A wide monthly sheet holds three columns per month — may_order, may_qty,
    may_amt — so the prefix is the month's English abbreviation.
        months_for(2026, 5, 5)  -> May only
        months_for(2026, 4, 6)  -> a whole quarter in one file
    """
    if not 1 <= start_month <= end_month <= 12:
        raise ValueError(f"bad month range: {start_month}-{end_month}")
    return [(MONTH_ABBR[m - 1], f"{year}-{m:02d}")
            for m in range(start_month, end_month + 1)]


def files_for(period, folder=None):
    """Derive both spreadsheet names from '2026-05'.

    Accepts the month with or without a leading zero (2026-5.xlsx and
    2026-05.xlsx both work) — hand-named files drop the zero often enough
    that failing on it would just be annoying.
    Returns (sales_file, channel_file); if neither spelling exists on disk it
    returns the preferred name so the caller can raise a useful error.
    """
    folder = folder or RAW_DIR
    year, month = period.split("-")
    stems = [f"{year}-{int(month)}", f"{year}-{month}"]

    def pick(suffix):
        for stem in stems:
            name = f"{stem}{suffix}.xlsx"
            if os.path.exists(os.path.join(folder, name)):
                return name
        return f"{stems[0]}{suffix}.xlsx"

    return pick(""), pick("p")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")            # source spreadsheets
REFERENCE_DIR = os.path.join(ROOT, "data", "reference")  # human-maintained files
WORK_DIR = os.path.join(ROOT, "data", "work")          # intermediate CSVs
OUTPUT_DIR = os.path.join(ROOT, "output")              # finished decks, by month

for _d in (RAW_DIR, REFERENCE_DIR, WORK_DIR, OUTPUT_DIR):
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Reporting period, and everything derived from it
# ---------------------------------------------------------------------------
RPT_PERIOD = os.environ.get("RPT_PERIOD")

if RPT_PERIOD:
    _y, _m = int(RPT_PERIOD[:4]), int(RPT_PERIOD[5:7])
    MONTHS = months_for(_y, _m, _m)                    # one month per report
    RAW_SALES_FILE, RAW_CHANNEL_FILE = files_for(RPT_PERIOD)
else:
    # ---- FALLBACK: only used when running the steps directly ----
    MONTHS = months_for(2026, 1, 1)
    RAW_SALES_FILE = "2026-1.xlsx"
    RAW_CHANNEL_FILE = "2026-1p.xlsx"

RAW_SALES_FILE = os.environ.get("RAW_SALES_FILE", RAW_SALES_FILE)
RAW_CHANNEL_FILE = os.environ.get("RAW_CHANNEL_FILE", RAW_CHANNEL_FILE)


# ---------------------------------------------------------------------------
# Database
#
# Credentials come from the environment. There is deliberately no default
# password: an earlier version of this project had one hard-coded in five
# different files, which is exactly the kind of thing that ends up in a
# public commit.
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "database": os.environ.get("MYSQL_DATABASE", "retail_demo"),
}
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD")

STORE_CODE = os.environ.get("STORE_CODE", "DEMO-CENTRAL")


def raw_path(filename):
    return os.path.join(RAW_DIR, filename)


def reference_path(filename):
    return os.path.join(REFERENCE_DIR, filename)


def work_path(filename):
    return os.path.join(WORK_DIR, filename)


def describe():
    """One-line summary, printed by every entry point so a wrong config is
    obvious before anything gets written."""
    periods = [p for _, p in MONTHS]
    src = f"RPT_PERIOD={RPT_PERIOD}" if RPT_PERIOD else "FALLBACK (manual)"
    return (f"[config | {src}] {periods[0]}..{periods[-1]} "
            f"({len(MONTHS)} month{'s' if len(MONTHS) > 1 else ''}) "
            f"| sales={RAW_SALES_FILE} | channel={RAW_CHANNEL_FILE}")


if __name__ == "__main__":
    print(describe())
    print("\nColumn mapping:")
    for prefix, period in MONTHS:
        print(f"  {prefix}_order / {prefix}_qty / {prefix}_amt  ->  {period}")

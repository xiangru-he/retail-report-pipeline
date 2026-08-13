"""
run_import.py — spreadsheets in, database updated.

    python run_import.py                 start (may stop for review)
    python run_import.py --resume        continue after you've reviewed
    python run_import.py --dry-run       list the steps, run nothing

EXIT 0  loaded
EXIT 2  paused — something needs a person's judgement
EXIT 1  a step failed

TWO PHASES, WITH A DELIBERATE STOP BETWEEN THEM
-----------------------------------------------
    phase 1   parse the spreadsheets, work out what's new, ask about anything
              ambiguous                                       <- may stop here
    phase 2   apply the decisions and load everything

The stop is the point of the design. Two things genuinely can't be automated:
a brand nobody has classified yet, and a product whose name disagrees with its
brand's category (a "sheep placenta" under a brand mapped to milk powder).
Guessing at either quietly corrupts every later report, and nothing about the
result looks wrong until someone reads a chart closely.

So phase 1 writes the questions to a CSV and exits 2. You fill the blanks in,
run --resume, and the answers are remembered in dim_product from then on —
each month asks about less than the last.

RE-RUNNING IS SAFE
------------------
Every load is an upsert keyed on (period, store, sku). Importing the same month
twice overwrites rather than doubling.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
from config import MONTHS, describe  # noqa: E402

PIPELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")

# (script, what it does, may it stop for review?)
PHASE1 = [
    ("step01_extract_products.py", "parse the sales spreadsheet", False),
    ("step02_brand_categories.py", "find brands with no category", True),
    ("step03_check_conflicts.py", "find products that disagree with their brand", True),
]

PHASE2 = [
    ("step04_finalise_classification.py", "settle category / tier / shipping", False),
    ("step05_split_star_schema.py", "split into dimension and fact rows", False),
    ("step06_classify_product_types.py", "sort supplements into functional types", False),
    ("step07_extract_channels.py", "parse the channel spreadsheet", False),
    ("step08_load_sales.py", "load dim_product + fact_sales", False),
    ("step09_load_product_types.py", "write product_type onto dim_product", False),
    ("step10_load_channels.py", "load fact_channel", False),
    ("step11_load_monthly_context.py", "load the hand-entered monthly figures", False),
]


def run(script, description):
    """Run one step. Returns its exit code; 2 means 'a person is needed'."""
    print("\n" + "-" * 66)
    print(f"  {script}   {description}")
    print("-" * 66)
    result = subprocess.run([sys.executable, script], cwd=PIPELINE)
    return result.returncode


def run_phase(steps, name):
    for script, description, may_pause in steps:
        code = run(script, description)
        if code == 2 and may_pause:
            print("\n" + "=" * 66)
            print(f"  Paused at {script}")
            print("=" * 66)
            print("  Read what it printed above, edit the CSV it names, then:")
            print("      python run_import.py --resume")
            return 2
        if code != 0:
            print(f"\nx {script} failed (exit {code}) — {name} stopped here.")
            print("  Nothing after this point ran, so the database is unchanged "
                  "by the remaining steps.")
            return 1
    return 0


def check_monthly_context():
    """Nag about monthly_context.csv before the load, not after.

    Foot traffic and campaign notes are typed in by hand, so they're the thing
    most likely to be forgotten. Checking here means finding out now rather
    than seeing blank cards on a finished slide.
    """
    result = subprocess.run(
        [sys.executable, "step11_load_monthly_context.py", "--check"], cwd=PIPELINE)
    return result.returncode


def main():
    args = sys.argv[1:]
    resume = "--resume" in args

    print("=" * 66)
    print("  IMPORT")
    print("=" * 66)
    print(describe())
    print(f"  months in scope: {[period for _p, period in MONTHS]}")

    if "--dry-run" in args:
        print("\nphase 1 (may stop for review)")
        for script, description, _ in PHASE1:
            print(f"    {script:38} {description}")
        print("\nphase 2")
        for script, description, _ in PHASE2:
            print(f"    {script:38} {description}")
        return 0

    if not resume:
        code = run_phase(PHASE1, "import")
        if code:
            return code
    else:
        print("\n--resume: skipping phase 1, going straight to the load.")

    # Checked on both paths. An earlier version only checked it during phase 1,
    # so a --resume run would load everything with the operating figures still
    # blank and nothing would say so until the deck was built.
    context_code = check_monthly_context()
    if context_code == 2:
        print("\n" + "=" * 66)
        print("  Paused — monthly_context.csv needs a row for this month")
        print("=" * 66)
        print("  Fill it in, then: python run_import.py --resume")
        return 2

    code = run_phase(PHASE2, "import")
    if code:
        return code

    print("\n" + "=" * 66)
    print("  Import complete — the database is up to date.")
    print("  Next: python run_report.py")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())

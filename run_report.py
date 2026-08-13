"""
run_report.py — database in, slide deck out.

    python run_report.py                 build the report for RPT_PERIOD
    python run_report.py --no-llm        skip the model, use rule-composed text
    python run_report.py --data-only     just refresh report_data.json

EXIT 0  built
EXIT 1  a step failed
EXIT 3  built, but the commentary contains a number that isn't in the source

WHICH MONTH
-----------
report_config.rpt_period in the database. One row, one switch. Every query
reads it, so there's no way to build a report where half the charts are on one
month and half on another — which is exactly what happened when the month was
passed as an argument to each step separately.

WHY THE WARNINGS ARE REPEATED AT THE END
----------------------------------------
A grounding failure printed in the middle of a run scrolls off the screen while
the charts render. By the time anyone notices, the wrong figure is on a slide.
So anything needing attention is collected and printed again last, after the
filename.
"""
import glob
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline"))
import db  # noqa: E402
from config import OUTPUT_DIR, describe, work_path  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(ROOT, "pipeline")


def artifact_patterns(period):
    """What to move into output/<period>/ when the run finishes.

    Deliberately period-specific. A plain *.pptx wildcard once swept February's
    deck into March's folder, and the only symptom was two files in a directory
    that should have had one.
    """
    return [
        f"monthly_report_{period}.pptx",
        "chart_*.png",
        "report_data.json",
        "narrative.json",
    ]


def run(script, description, args=()):
    print("\n" + "-" * 66)
    print(f"  {script}   {description}")
    print("-" * 66)
    if script.endswith(".js"):
        command = ["node", script, *args]
    else:
        command = [sys.executable, script, *args]
    return subprocess.run(command, cwd=PIPELINE).returncode


def sync_monthly_context(period):
    """Push monthly_context.csv into the table before querying it.

    The CSV is the source of truth and someone will have edited it since the
    import — usually to correct a figure or write up the month's campaign. If
    this didn't run, the report would use whatever was loaded weeks ago and
    nothing would indicate the file and the table disagreed.
    """
    return subprocess.run(
        [sys.executable, "step11_load_monthly_context.py", period],
        cwd=PIPELINE).returncode


def archive(period):
    out_dir = os.path.join(OUTPUT_DIR, period)
    os.makedirs(out_dir, exist_ok=True)

    moved = 0
    for pattern in artifact_patterns(period):
        for src in glob.glob(work_path(pattern)):
            shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
            moved += 1

    # Sweep out any deck from another month that has ended up here.
    for stray in glob.glob(os.path.join(out_dir, "monthly_report_*.pptx")):
        if os.path.basename(stray) != f"monthly_report_{period}.pptx":
            os.remove(stray)
            print(f"  removed stray {os.path.basename(stray)}")

    return out_dir, moved


def main():
    args = sys.argv[1:]
    period = db.rpt_period()

    print("=" * 66)
    print("  REPORT")
    print("=" * 66)
    print(describe())
    print(f"  reporting month: {period}   (report_config.rpt_period)")

    todos = []

    # Clear last run's narrative before anything else. It belongs to whichever
    # month was built previously, and if step 13 is skipped — no key, --no-llm,
    # a failed call — step 15 would happily put another month's sentences next
    # to this month's charts. Nothing would error; the deck would just be wrong.
    stale = work_path("narrative.json")
    if os.path.exists(stale):
        os.remove(stale)

    if sync_monthly_context(period) not in (0, 2):
        print("x could not sync monthly_context.csv")
        return 1

    if run("step12_fetch_report_data.py", "run every query, save the answers"):
        return 1
    if "--data-only" in args:
        print(f"\nreport_data.json refreshed for {period}")
        return 0

    narrative_code = 0
    if "--no-llm" in args:
        print("\n--no-llm: the deck will use rule-composed wording, unless a "
              "narrative was archived with this month previously.")
    else:
        narrative_code = run("step13_generate_narrative.py", "draft and check the commentary")
        if narrative_code == 3:
            todos.append("The commentary contains at least one number that is "
                         "not in the source data — see the step 13 output above "
                         "and check it before sending this out.")
        elif narrative_code != 0:
            todos.append("The commentary step failed. The deck was built with "
                         "rule-composed wording instead — accurate, just plainer.")

    if run("step14_render_charts.py", "render the charts"):
        return 1
    if run("step15_build_deck.js", "assemble the deck"):
        print("\nx the deck step failed. If this is 'Cannot find module', run "
              "npm install first.")
        return 1

    out_dir, moved = archive(period)

    print("\n" + "=" * 66)
    print(f"  {os.path.relpath(out_dir, ROOT)}/monthly_report_{period}.pptx")
    print(f"  ({moved} files archived)")
    print("=" * 66)

    if todos:
        print("\nBefore you send it:")
        for i, item in enumerate(todos, 1):
            print(f"  {i}. {item}")
        return 3

    print("\nNothing outstanding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

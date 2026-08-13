"""
monthly.py — the whole month in one command.

    python monthly.py 2026-05              import, then report
    python monthly.py 2026-05 --resume     continue after reviewing a pause
    python monthly.py 2026-05 --report     report only, skip the import
    python monthly.py 2026-05 --no-llm     rule-composed wording

EXIT 0  done
EXIT 2  paused — something needs a person
EXIT 3  built, but a figure in the commentary needs checking

WHY THIS EXISTS
---------------
Everything here can be done by running run_import.py and run_report.py in
order. The reason for a wrapper is that the month has to be set in three
places — the two spreadsheet filenames and report_config.rpt_period — and
setting two of the three is the single easiest mistake to make. It produces a
deck that builds cleanly and is about the wrong month.

So the month is given once, on the command line, and everything downstream is
derived from it:

    2026-05  ->  RPT_PERIOD env var    ->  config.MONTHS
                                       ->  data/raw/2026-5.xlsx   (sales)
                                       ->  data/raw/2026-5p.xlsx  (channels)
             ->  report_config.rpt_period in MySQL

THE MONTHLY ROUTINE
-------------------
    1. drop the two spreadsheets into data/raw/
    2. add a row to data/reference/monthly_context.csv
    3. python monthly.py 2026-05
    4. answer anything it stops to ask, then --resume
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def usage():
    print(__doc__.strip())
    return 1


def main():
    args = sys.argv[1:]
    periods = [a for a in args if PERIOD_RE.match(a)]
    if len(periods) != 1:
        return usage()
    period = periods[0]

    flags = [a for a in args if a.startswith("--")]
    report_only = "--report" in flags
    resume = "--resume" in flags

    # Passed to every child process. Setting it here rather than in each step
    # is the whole point: one value, derived everywhere.
    env = dict(os.environ, RPT_PERIOD=period)

    print("=" * 66)
    print(f"  MONTHLY RUN — {period}")
    print("=" * 66)

    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    os.environ["RPT_PERIOD"] = period
    import config  # noqa: E402  (must come after RPT_PERIOD is set)
    import db      # noqa: E402

    sales = config.raw_path(config.RAW_SALES_FILE)
    channels = config.raw_path(config.RAW_CHANNEL_FILE)

    if not report_only:
        absent = [os.path.basename(p) for p in (sales, channels) if not os.path.exists(p)]
        if absent:
            print(f"\nx data/raw/ is missing {absent}")
            print(f"  Expected: {config.RAW_SALES_FILE} (sales) and "
                  f"{config.RAW_CHANNEL_FILE} (channels).")
            print("  Either spelling of the month works — 2026-5.xlsx or 2026-05.xlsx.")
            return 1

        code = subprocess.run(
            [sys.executable, "run_import.py"] + (["--resume"] if resume else []),
            cwd=ROOT, env=env).returncode
        if code == 2:
            print("\n" + "=" * 66)
            print("  Paused. Deal with what it asked for, then:")
            print(f"      python monthly.py {period} --resume")
            print("=" * 66)
            return 2
        if code != 0:
            return code

    # Set the reporting month only once the data is actually loaded. Setting it
    # up front would leave report_config pointing at a month with no rows if the
    # import failed, and the next report run would quietly produce empty charts.
    db.set_rpt_period(period)
    print(f"\nreport_config.rpt_period = {period}")

    report_flags = [f for f in flags if f in ("--no-llm", "--data-only")]
    code = subprocess.run([sys.executable, "run_report.py", *report_flags],
                          cwd=ROOT, env=env).returncode

    if code == 3:
        return 3
    if code != 0:
        return code

    print(f"\nFinished — output/{period}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

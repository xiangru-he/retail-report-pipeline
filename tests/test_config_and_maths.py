"""
Tests for the month plumbing and the month-on-month arithmetic.

Both look too simple to test. Both caused real bugs.

The month plumbing: a wide sheet names its columns by month (jan_qty, feb_qty),
and four separate scripts had those prefixes written into them. Adding April
meant editing all four, and missing one produced a KeyError several minutes
into a run — one script at a time, so it took several attempts to get through.
Deriving the names from one function is what fixed it.

The arithmetic: month-on-month is calculated once, in step 12, and everything
downstream quotes the result. Earlier the language model was left to work it
out from raw totals and produced figures that were in no version of the data.
"""
import pytest

import config
import step12_fetch_report_data as step12


# --------------------------------------------------------- month plumbing --
def test_months_for_single_month():
    assert config.months_for(2026, 5, 5) == [("may", "2026-05")]


def test_months_for_a_range():
    assert config.months_for(2026, 1, 3) == [
        ("jan", "2026-01"), ("feb", "2026-02"), ("mar", "2026-03")]


def test_months_for_pads_the_month_number():
    """'2026-5' and '2026-05' sort differently as strings, and period is used
    as a sort key throughout."""
    _prefix, period = config.months_for(2026, 5, 5)[0]
    assert period == "2026-05"


@pytest.mark.parametrize("start,end", [(0, 3), (1, 13), (5, 2)])
def test_months_for_rejects_a_bad_range(start, end):
    with pytest.raises(ValueError):
        config.months_for(2026, start, end)


def test_files_for_derives_both_spreadsheet_names(tmp_path):
    sales, channels = config.files_for("2026-05", folder=str(tmp_path))
    assert sales.endswith(".xlsx") and channels.endswith(".xlsx")
    assert channels.replace("p.xlsx", ".xlsx") == sales


def test_files_for_accepts_either_spelling_of_the_month(tmp_path):
    """Files are named by hand and the leading zero gets dropped about half the
    time. Failing on that would be a pointless obstacle."""
    (tmp_path / "2026-05.xlsx").write_text("")
    (tmp_path / "2026-05p.xlsx").write_text("")
    sales, channels = config.files_for("2026-05", folder=str(tmp_path))
    assert sales == "2026-05.xlsx"
    assert channels == "2026-05p.xlsx"

    (tmp_path / "2026-05.xlsx").unlink()
    (tmp_path / "2026-05p.xlsx").unlink()
    (tmp_path / "2026-5.xlsx").write_text("")
    (tmp_path / "2026-5p.xlsx").write_text("")
    sales, channels = config.files_for("2026-05", folder=str(tmp_path))
    assert sales == "2026-5.xlsx"
    assert channels == "2026-5p.xlsx"


def test_no_default_database_password():
    """An earlier version of this project had the password written into five
    files. This assertion is here so it can't come back."""
    import importlib
    import os
    saved = os.environ.pop("MYSQL_PASSWORD", None)
    try:
        reloaded = importlib.reload(config)
        assert reloaded.DB_PASSWORD in (None, "")
    finally:
        if saved is not None:
            os.environ["MYSQL_PASSWORD"] = saved
        importlib.reload(config)


# ------------------------------------------------- month-on-month, one place -
def test_mom_percent_basic():
    assert step12.mom_percent([100.0, 150.0]) == [50.0]


def test_mom_percent_chain_is_one_shorter_than_the_series():
    """Four months give three transitions. An off-by-one here would pair each
    percentage with the wrong month label on the chart."""
    assert len(step12.mom_percent([100.0, 110.0, 90.0, 99.0])) == 3


def test_mom_percent_negative():
    assert step12.mom_percent([100.0, 60.0]) == [-40.0]


def test_mom_percent_single_month_has_no_comparison():
    """The first month a store is on the system. The report has to build
    anyway — the charts show "no comparison available"."""
    assert step12.mom_percent([100.0]) == []
    assert step12.mom_percent([]) == []


def test_mom_percent_handles_a_zero_baseline():
    """A month with no sales in a category. Dividing by it must not raise
    part-way through a report."""
    result = step12.mom_percent([0.0, 50.0])
    assert len(result) == 1
    assert result[0] is None or isinstance(result[0], float)


def test_mom_percent_is_rounded_for_display():
    """Values go straight onto slides, and the grounding check matches text
    against them — an unrounded 42.35000000000001 would never match "42.35"."""
    for value in step12.mom_percent([88500.0, 50900.0, 79200.0]):
        assert value == round(value, 2)

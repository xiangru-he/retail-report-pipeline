"""
Tests for the numeric grounding check.

The first test is the one that matters: it reproduces a fabrication that
actually reached a finished deck. The month's revenue was 78,427.85 and the
generated headline said 84,427.85. Nothing crashed, no rule was violated, and
the figure sat on the title slide.

The rest cover the cases where a naive version of this check went wrong and
produced false alarms — a check that cries wolf gets switched off.
"""
import pytest

import grounding


SOURCE = {
    "period": "2026-02",
    "headline": {"total_amount": 78427.85, "total_qty": 1759, "total_orders": 285},
    "computed": {
        "amount_mom_pct": [-42.35],
        "export_qty_mom_pct": [-40.0],
        "local_qty_mom_pct": [-9.1],
    },
    "top_brands": [{"brand": "Orama", "amount": 12043.20, "pct_of_store": 15.4}],
}

HOLIDAYS = {
    "2026-02": [{"date": "2026-02-15", "end": "2026-02-23",
                 "name": "Chinese New Year"}],
}


def check(text, field="headline_title"):
    return grounding.check({field: text}, SOURCE, HOLIDAYS)


# --------------------------------------------------------------- the point --
def test_catches_the_real_fabrication():
    """78,427.85 written as 84,427.85 — one digit, no error, wrong deck."""
    missing, _ = check("February revenue was NZ$84,427.85")
    assert len(missing) == 1
    assert "84427.85" in missing[0]


def test_accepts_the_true_figure():
    missing, sign_only = check("February revenue was NZ$78,427.85")
    assert missing == []
    assert sign_only == []


def test_catches_an_invented_percentage():
    missing, _ = check("Premium reached 37.6% of revenue")
    assert len(missing) == 1


# ------------------------------------------------- sign handling, separately -
def test_sign_expressed_in_words_is_not_a_fabrication():
    """The stored value is -42.35 and the model writes "fell 42.35%".
    That reads better than a minus sign and must not be treated as invented —
    but it still gets surfaced, because the direction word could be wrong."""
    missing, sign_only = check("Revenue fell 42.35% on January")
    assert missing == []
    assert len(sign_only) == 1


def test_negative_written_as_negative_passes_clean():
    missing, sign_only = check("Revenue change was -42.35%")
    assert missing == []
    assert sign_only == []


# ---------------------------------------------- the two regex special cases --
def test_date_range_hyphen_is_not_a_minus_sign():
    """"15-23 Feb" must not be read as 15 and -23. An early version did, and
    reported a perfectly good holiday date as unsourced."""
    numbers = grounding.extract_numbers("Chinese New Year ran 15-23 Feb")
    assert -23 not in numbers
    assert 23 in numbers


def test_a_genuine_negative_before_a_non_date_stays_negative():
    """If a hyphen before a number were always treated as a range, a real
    fabrication could hide behind a flipped sign."""
    numbers = grounding.extract_numbers("month on month -42.35%")
    assert -42.35 in numbers


def test_holiday_dates_count_as_sourced():
    missing, _ = check("Chinese New Year ran 15-23 February", field="channel_comment")
    assert missing == []


# ------------------------------------------------------------- practicality --
def test_small_prose_numbers_do_not_need_a_source():
    """"the top 3 brands", "100% of" — requiring a source for these would bury
    the real findings."""
    missing, _ = check("The top 3 brands account for most of the category")
    assert missing == []


def test_rounding_slack():
    """The source holds 15.4; the text says 15.4% — and a mention of 78,428
    for 78,427.85 is a rounding, not an invention."""
    missing, _ = check("Orama is 15.4% of store revenue, NZ$12,043.20")
    assert missing == []


@pytest.mark.parametrize("text,expected_missing", [
    ("Export volume fell 40.0% while local fell 9.1%", 0),
    ("Export volume fell 40.0% while local fell 9.7%", 1),
])
def test_one_wrong_number_among_several_right_ones(text, expected_missing):
    """The realistic failure isn't a sentence of nonsense — it's one wrong
    figure in an otherwise correct paragraph."""
    missing, _ = check(text, field="channel_comment")
    assert len(missing) == expected_missing


def test_non_string_values_are_ignored_not_crashed_on():
    missing, sign_only = grounding.check({"count": 7}, SOURCE)
    assert missing == [] and sign_only == []

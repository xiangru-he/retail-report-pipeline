"""
Tests for the product/brand conflict check (step 03).

The last test is a regression. `keyword_guess` used to return None when a
product name matched no category keyword, and `verdict` tested it with
`guess is None`. That worked on one pandas version and crashed on another:
passing values through `DataFrame.apply(axis=1)` can turn None into a float
NaN, and `NaN.startswith` raises AttributeError several steps into an import
that has already done real work.

It surfaced on a different machine from the one it was written on, which is
the point — "it works here" and "the sentinel survives the round trip" are
different claims.
"""
import numpy as np
import pandas as pd
import pytest

from step03_check_conflicts import keyword_guess, verdict


# ------------------------------------------------------- what the name says --
@pytest.mark.parametrize("desc,expected", [
    ("Manuka Honey UMF 10+ (500g)", "honey"),
    ("Omega 3 Fish Oil 500mg", "supplement"),
    ("Milk Chocolate Block (250g)", "chocolate"),
    ("Lanolin Moisturising Cream (150ml)", "skincare"),
])
def test_single_keyword_match(desc, expected):
    assert keyword_guess(desc) == expected


def test_a_name_matching_two_categories_is_ambiguous():
    """"Honey Gift Set" is honey by brand and souvenir by keyword. The check
    doesn't try to resolve it — it hands it to a person."""
    guess = keyword_guess("Honey Gift Set (250g x4)")
    assert guess.startswith("ambiguous")
    assert "honey" in guess and "souvenir" in guess


def test_no_match_returns_an_empty_string_not_none():
    """The sentinel is the same type as every other return value, so nothing
    downstream has to ask what type it got."""
    result = keyword_guess("Wool Throw Blanket")
    assert result == "" or isinstance(result, str)


# ------------------------------------------------------------- the verdict --
def test_agreement_is_a_match():
    assert verdict("honey", "honey") == "match"


def test_disagreement_is_flagged_as_a_conflict():
    """A supplement keyword under a milk powder brand. Usually a word
    collision, occasionally a genuine misfile — either way, a person decides."""
    assert verdict("milk_powder", "supplement").startswith("CONFLICT")


def test_ambiguous_is_a_conflict():
    assert verdict("honey", "ambiguous:honey+souvenir").startswith("CONFLICT")


def test_unclassified_brand_is_not_a_conflict():
    """It's a different question, asked at step 02, and reporting it here too
    would mean answering the same thing twice."""
    assert verdict("", "supplement") == "brand_not_classified"


# ----------------------------------------------------------- the regression --
@pytest.mark.parametrize("empty", [None, np.nan, float("nan"), "", pd.NA])
def test_verdict_survives_every_shape_of_missing(empty):
    """None, NaN and "" all mean the same thing here and must not raise.

    Which one actually arrives depends on the pandas version, so the code
    cannot depend on getting a particular one.
    """
    assert verdict("honey", empty) == "no_keyword_match"


def test_guess_survives_a_dataframe_round_trip():
    """The exact path that broke: build the column with apply, read it back
    with apply(axis=1). Whatever pandas does to the sentinel in between, the
    verdict has to come out."""
    df = pd.DataFrame({
        "product_desc": ["Wool Throw Blanket", "Manuka Honey UMF 10+", "Plain Item"],
        "brand_category": ["souvenir", "honey", "honey"],
    })
    df["keyword_guess"] = df["product_desc"].apply(keyword_guess)
    df["verdict"] = df.apply(
        lambda r: verdict(r["brand_category"], r["keyword_guess"]), axis=1)

    assert df["verdict"].map(lambda v: isinstance(v, str)).all()
    # And the downstream filter must still work — .str.startswith on a column
    # containing NaN raises when used as a boolean mask.
    assert len(df[df["verdict"].str.startswith("CONFLICT")]) >= 0

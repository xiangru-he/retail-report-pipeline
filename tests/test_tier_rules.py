"""
Tests for premium/regular classification and brand-name matching.

Two things are being defended here.

First, `tier` is the store's marker for the range it wants staff to push. It is
not a price band. The rules are declarative — a list of brands, plus a few
product-level exceptions — rather than a hardcoded list of SKU codes, because
SKU codes change when a supplier reissues a product and the tier does not.

Second, brand names arrive from the spreadsheet spelled inconsistently:
different capitalisation, a missing space, an occasional typo. Fuzzy matching
handles that, but a threshold set too low silently merges two real brands, and
nothing about the resulting chart looks wrong. 0.85 was chosen by measuring the
closest pair of genuinely different brands in the list and leaving headroom.
"""
import difflib

import pytest

import tier_rules as T


# ------------------------------------------------------- brand-level rules --
def test_a_premium_brand_is_premium_throughout():
    tier, reason = T.classify(T.PREMIUM_BRANDS[0], "any product", "")
    assert tier == "premium"
    assert T.PREMIUM_BRANDS[0] in reason


def test_an_unlisted_brand_falls_through_to_regular():
    """Not an error. Most brands have no tier rule, and the default is the
    common case rather than something to warn about."""
    tier, reason = T.classify("Brand Nobody Has Listed", "fish oil 1000mg", "")
    assert tier == "regular"
    assert "no tier rule" in reason


# ----------------------------------------------- product-level exceptions ---
def test_sku_rule_narrows_a_brand_to_certain_products():
    """A brand can be premium only for part of its range — the rule matches on
    words in the product description."""
    rule = T.SKU_RULES[0]
    keyword = rule["keywords"][0]
    tier, _ = T.classify(rule["brand"], f"{keyword} 60 capsules", "")
    assert tier == "premium"

    tier, _ = T.classify(rule["brand"], "something else entirely", "")
    assert tier == "regular"


def test_no_brand_appears_in_both_rule_sets():
    """A brand listed as wholly premium AND given a narrowing rule means the
    narrowing rule can never fire — it is dead code that reads as if it works.
    tier_rules raises on import if this happens; this test states the intent."""
    overlap = set(T.PREMIUM_BRANDS) & {r["brand"] for r in T.SKU_RULES}
    assert overlap == set()


# --------------------------------------------------------- name resolution --
def test_case_and_spacing_differences_resolve_to_the_same_brand():
    brand = T.PREMIUM_BRANDS[0]
    for spelling in (brand.upper(), brand.lower(), f"  {brand}  "):
        resolved, _ = T.resolve_brand(spelling)
        assert resolved == brand


def test_a_missing_space_still_resolves():
    """'Cove & Clay' and 'Cove&Clay' are the same supplier typed twice."""
    spaced = next((b for b in T.PREMIUM_BRANDS if " " in b), None)
    if spaced is None:
        pytest.skip("no multi-word brand in the list")
    resolved, how = T.resolve_brand(spaced.replace(" ", ""))
    assert resolved == spaced
    assert how in ("tight", "fuzzy")


def test_an_unrelated_name_does_not_resolve():
    resolved, how = T.resolve_brand("Completely Different Supplier Ltd")
    assert resolved is None
    assert how == "none"


def test_fuzzy_threshold_has_headroom_over_the_closest_real_pair():
    """The check that justifies the constant.

    If two genuinely different brands in the list scored above the threshold,
    fuzzy matching would merge them — one brand's revenue would vanish into
    another's bar and the chart would look entirely plausible.
    """
    brands = sorted({*T.PREMIUM_BRANDS, *(r["brand"] for r in T.SKU_RULES)})
    worst_pair, worst_score = None, 0.0
    for i, a in enumerate(brands):
        for b in brands[i + 1:]:
            score = difflib.SequenceMatcher(
                None, T.normalise_brand(a), T.normalise_brand(b)).ratio()
            if score > worst_score:
                worst_pair, worst_score = (a, b), score

    assert worst_score < T.FUZZY_THRESHOLD, (
        f"{worst_pair} score {worst_score:.3f} is at or above the "
        f"{T.FUZZY_THRESHOLD} threshold — they would be merged")


# ---------------------------------------------------- pickup vs shipped ----
def test_pickup_is_inferred_from_the_absence_of_a_freight_tag():
    """There is no 'collected in store' field in the source data. A product
    with no freight tag was picked up; one with a tag was shipped."""
    assert T.is_local_pickup("") is True
    assert T.is_local_pickup("nan") is True


def test_a_known_freight_tag_means_it_was_shipped():
    for tag in T.EXPORT_TAGS:
        assert T.is_local_pickup(tag) is False, tag


def test_an_unfamiliar_tag_is_recorded_rather_than_swallowed():
    """A freight tag nobody has seen before is treated as pickup — the safer
    default — but it is added to `unknown_tags` so the step that calls this can
    surface it. Silently absorbing a new tag would move a shipped order into
    the pickup figures with nothing to show for it."""
    T.unknown_tags.clear()
    T.is_local_pickup("{some new courier}")
    assert "{some new courier}" in T.unknown_tags


def test_a_pickup_only_rule_does_not_fire_on_a_shipped_order():
    """The narrowing rule that says "premium only when collected in store"."""
    rule = next(r for r in T.SKU_RULES if r["local_pickup_only"])
    shipped_tag = sorted(T.EXPORT_TAGS)[0]
    keyword = (rule["keywords"] or ["anything"])[0]

    tier, _ = T.classify(rule["brand"], f"{keyword} product", "")
    assert tier == "premium"

    tier, reason = T.classify(rule["brand"], f"{keyword} product", shipped_tag)
    assert tier == "regular"
    assert "pickup-only" in reason

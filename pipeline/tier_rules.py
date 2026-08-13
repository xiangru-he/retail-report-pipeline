"""
tier_rules.py — decides whether a SKU is "premium" or "regular".

WHAT "PREMIUM" MEANS HERE
-------------------------
Not a price band. It's the store's own flag for "this is what we want staff
to push". A $9 souvenir can be premium and a $130 tin of formula can be
regular. Getting this backwards makes every downstream reading wrong, which
is why it's stated at the top of this file and in the LLM prompt.

WHY RULES INSTEAD OF A LIST OF SKU CODES
----------------------------------------
The first version kept a CSV of individual SKU codes that were exceptions to
their brand's default. It broke the first time the store added a new item to
an existing premium line: the new code wasn't in the list, so it was silently
classified as regular, and the premium share dropped a few points with no
error anywhere. Rules match on brand + keyword + shipping mode, so a new SKU
in a known line is picked up automatically.

THE RULES (confirmed with the store owner)
------------------------------------------
  1. Brands in PREMIUM_BRANDS  -> every SKU is premium
  2. Fernvale + "magnesium" in the name        -> premium
  3. Westbrook, in-store pickup only           -> premium
  4. Clearfield, in-store pickup, and the name mentions immune / digestion
                                               -> premium
  5. everything else                           -> regular

BRAND NAME MATCHING
-------------------
The same brand arrives spelled several ways ("Solwave" / "SOLWAVE"), and
occasionally misspelled. Matching is: normalise -> exact -> ignore spaces ->
fuzzy (ratio >= 0.85). Every fuzzy merge is recorded in `fuzzy_matches` and
the caller is expected to print it: a silent wrong merge would move the
premium share with nothing in the log to explain it.

The 0.85 threshold was checked against the real brand list — the closest
unrelated pair scored 0.63, while realistic typos score 0.86-0.95. See
tests/test_tier_rules.py.
"""
import difflib
import re

# ---------------------------------------------------------------------------
# 1. Brands where every SKU is premium
# ---------------------------------------------------------------------------
# NOTE: a brand listed here is premium in every case, so it must NOT also
# appear in SKU_RULES — the whole-brand check runs first and would make the
# narrower rule unreachable. (Westbrook belongs in SKU_RULES, not here: it is
# only premium when the customer collects in store.)
PREMIUM_BRANDS = [
    "solwave", "northlight", "riverstone bio",
    "manuka ridge", "golden vale", "hivewood",
    "lanolux", "pounamu skin",
    "southern craft", "kiwiana co", "harbour wool", "piko gifts",
    "cocoa bay",
]

# ---------------------------------------------------------------------------
# 2-4. Rules that apply inside an otherwise-regular brand.
#      keywords=None means "don't look at the product name at all"
# ---------------------------------------------------------------------------
SKU_RULES = [
    {
        "brand": "fernvale",
        "keywords": ["magnesium"],
        "local_pickup_only": False,
        "note": "Fernvale magnesium line",
    },
    {
        "brand": "westbrook",
        "keywords": None,
        "local_pickup_only": True,
        "note": "Westbrook in-store pickup",
    },
    {
        "brand": "clearfield",
        "keywords": ["immune", "digestion"],
        "local_pickup_only": True,
        "note": "Clearfield in-store immune/digestion line",
    },
]

FUZZY_THRESHOLD = 0.85

# A freight tag in the product name means it ships out; no tag means the
# customer collects it in store.
EXPORT_TAGS = {"Express Freight", "Standard Freight", "15-Day Express"}

# Populated as a side effect so callers can surface them.
fuzzy_matches = []      # [(raw spelling, matched brand, ratio), ...]
unknown_tags = set()    # freight tags we've never seen before


def normalise_brand(s):
    """Lowercase, trim, collapse runs of whitespace."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _tight(s):
    """Also drop every space, so 'Cove & Clay' and 'Cove&Clay' compare equal."""
    return normalise_brand(s).replace(" ", "")


_KNOWN_BRANDS = PREMIUM_BRANDS + [r["brand"] for r in SKU_RULES]
_TIGHT_TO_BRAND = {_tight(b): b for b in _KNOWN_BRANDS}

# A brand in both places would make its SKU rule unreachable (see the note on
# PREMIUM_BRANDS). Fail loudly at import rather than quietly misclassify.
_overlap = set(PREMIUM_BRANDS) & {r["brand"] for r in SKU_RULES}
if _overlap:
    raise ValueError(
        f"{sorted(_overlap)} appear in both PREMIUM_BRANDS and SKU_RULES. "
        "The whole-brand check runs first, so the SKU rule would never fire. "
        "Pick one."
    )


def resolve_brand(raw_brand):
    """Map a spelling from the spreadsheet onto a brand this module knows.

    Returns (brand or None, how) where how is exact / tight / fuzzy / none.
    None simply means the brand has no tier rule — it falls through to
    "regular", which is the normal case, not an error.
    """
    n = normalise_brand(raw_brand)
    if n in _KNOWN_BRANDS:
        return n, "exact"

    t = _tight(n)
    if t in _TIGHT_TO_BRAND:
        return _TIGHT_TO_BRAND[t], "tight"

    best, best_ratio = None, 0.0
    for known_tight, known_brand in _TIGHT_TO_BRAND.items():
        ratio = difflib.SequenceMatcher(None, t, known_tight).ratio()
        if ratio > best_ratio:
            best, best_ratio = known_brand, ratio
    if best_ratio >= FUZZY_THRESHOLD:
        fuzzy_matches.append((str(raw_brand), best, round(best_ratio, 3)))
        return best, "fuzzy"
    return None, "none"


def is_local_pickup(freight_tag):
    """In-store pickup = no freight tag on the product name.

    Note this is inferred from an *absence*, not read from a dedicated field.
    Unfamiliar tags are recorded in `unknown_tags` for the caller to report,
    but the return value keeps the original behaviour.
    """
    tag = str(freight_tag).strip()
    if tag in ("", "nan", "None", "NaN"):
        return True
    if tag not in EXPORT_TAGS:
        unknown_tags.add(tag)
    return tag not in EXPORT_TAGS


def classify(raw_brand, product_desc, freight_tag):
    """Return ('premium' | 'regular', reason)."""
    brand, _how = resolve_brand(raw_brand)
    if brand is None:
        return "regular", "brand has no tier rule"

    if brand in PREMIUM_BRANDS:
        return "premium", f"{brand}: whole brand is premium"

    desc = str(product_desc).lower()
    for rule in SKU_RULES:
        if rule["brand"] != brand:
            continue
        if rule["local_pickup_only"] and not is_local_pickup(freight_tag):
            return "regular", f"{brand}: ships out, rule is pickup-only"
        if rule["keywords"] is None:
            return "premium", rule["note"]
        hit = [k for k in rule["keywords"] if k in desc]
        if hit:
            return "premium", f"{rule['note']} (matched {'/'.join(hit)})"
        return "regular", f"{brand}: no keyword match ({'/'.join(rule['keywords'])})"

    return "regular", "default"

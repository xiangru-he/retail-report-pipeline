"""
grounding.py — check that every number in the generated commentary can be
traced back to the source data.

THE PROBLEM
-----------
A language model writing about a table will occasionally produce a number that
looks plausible and isn't there. It happened on a real report: the month's
revenue was 78,427.85 and the generated headline said 84,427.85. Nothing
crashed. The figure appeared on the title slide of a deck that went to the
store owner.

Prompting alone doesn't fix this. "Only use numbers from the data" is already
in the prompt, and the model still slipped a digit. So the output is checked
mechanically instead of trusted.

HOW IT WORKS
------------
Pull every number-shaped token out of the generated text, then confirm each one
appears somewhere in report_data.json (or the holiday calendar), allowing for
rounding. Findings are split into two kinds, because conflating them makes the
check useless:

  missing    the value isn't in the source at all — most likely invented,
             must be checked by a person
  sign_only  the magnitude matches but the sign doesn't. Almost always the
             model writing "down 46.87%" for a stored -46.87 — which reads
             better than a minus sign. Worth a glance to confirm the direction
             word is right, not worth blocking on.

Without that split, the sign cases (common and harmless) drown the invented
ones (rare and serious) and the whole check gets ignored.

WHY THE TWO REGEX SPECIAL CASES
-------------------------------
Both were bugs found by running this on real output:

  · "1-2 Feb" or "15-23 Feb" — the hyphen is a range, not a minus sign. An
    early version read the second number as negative and reported a perfectly
    good date as unsourced.
  · "-42.35%" after a word ending in a digit — genuinely negative and must
    stay negative, or a real fabrication could hide behind a sign flip.

The rule that satisfies both: a hyphen is a range separator only when the
number after it is immediately followed by a date word.
"""
import re

NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")

# Words that mark a number as part of a date, so a preceding hyphen is a range.
DATE_WORDS = re.compile(
    r"^\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|"
    r"november|december)", re.IGNORECASE)

# Small numbers that show up as ordinary prose ("the top 3 brands", "100%")
# and shouldn't need a source.
NARRATIVE_NUMBERS = {0, 1, 2, 3, 4, 5, 10, 100}

TOLERANCE = 0.1     # rounding slack when matching against source values


def extract_numbers(text):
    """Every number-shaped token, with range hyphens resolved."""
    found = []
    for match in NUMBER_PATTERN.finditer(text):
        token = match.group()
        if token.startswith("-"):
            following = text[match.end():]
            if DATE_WORDS.match(following):
                token = token[1:]          # "12-14 Apr" — a range, not a minus
        try:
            found.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return found


def collect_source_numbers(obj, into):
    """Every numeric value anywhere in the source structure, at several
    roundings so 46.87 also matches a text mention of 46.9."""
    if isinstance(obj, dict):
        for value in obj.values():
            collect_source_numbers(value, into)
    elif isinstance(obj, list):
        for value in obj:
            collect_source_numbers(value, into)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        value = float(obj)
        into.update({round(value, 2), round(value, 1), round(value, 0)})
    elif isinstance(obj, str):
        # Digits inside strings count too — dates in the holiday calendar.
        for digits in re.findall(r"\d+", obj):
            try:
                into.add(float(digits))
            except ValueError:
                pass


def check(narrative, *sources):
    """Verify narrative text against the source data.

    narrative : {field: text}
    sources   : one or more JSON-ish structures the numbers may come from

    Returns (missing, sign_only), each a list of human-readable findings.
    """
    allowed = set()
    for source in sources:
        collect_source_numbers(source, allowed)
    allowed |= NARRATIVE_NUMBERS
    allowed_magnitudes = {abs(v) for v in allowed}

    missing, sign_only = [], []
    for field, text in narrative.items():
        if not isinstance(text, str):
            continue
        for number in extract_numbers(text):
            if any(abs(number - candidate) <= TOLERANCE for candidate in allowed):
                continue
            if any(abs(abs(number) - candidate) <= TOLERANCE
                   for candidate in allowed_magnitudes):
                sign_only.append(
                    f"[{field}] {number} matches in magnitude but not sign — "
                    "check the direction word (rose / fell) is right")
            else:
                missing.append(
                    f"[{field}] {number} does not appear in the source data — "
                    "verify before publishing")
    return missing, sign_only

"""
Step 13 — have a language model write the commentary, then check its numbers.

INPUT   data/work/report_data.json, data/reference/holidays.json
OUTPUT  data/work/narrative.json

    python step13_generate_narrative.py

EXIT 0  fine
EXIT 3  written, but contains numbers that aren't in the source — a person
        must look before the deck is sent anywhere

OPTIONAL BY DESIGN
------------------
No API key, or the call fails? The deck still builds. step15 falls back to
sentences composed from the same figures — accurate, just flatter. The model
is an enhancement layer, never a dependency, because a report that can't be
produced on a given evening is worse than a plain one.

THE DIVISION OF LABOUR
----------------------
    arithmetic  -> Python (step 12, in `computed`)
    wording     -> the model

The model is given percentages that are already calculated and is forbidden
from deriving any of its own. This isn't caution for its own sake: an earlier
version let it work out month-on-month from raw totals and it produced figures
that were nowhere in the data.

ABOUT THE PROMPT
----------------
Every numbered rule below was added in response to something the model actually
did. They're kept in that form — rule plus the failure that prompted it —
because a rule without its reason gets deleted by the next person who finds it
fussy. The most recent addition, rule 15, came from a real March report: the model
wrote "the third consecutive month of decline" about a series with three data
points, which can show at most two. Every number in that sentence was real and
the grounding check passed it — the error was in a word, not a figure.
"""
import json
import os
import re
import sys

import grounding
from config import describe, reference_path, work_path

MODEL = os.environ.get("NARRATIVE_MODEL", "claude-sonnet-5")
API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Fields step15 will look for. Anything else is ignored; anything absent falls
# back to a rule-composed sentence.
NARRATIVE_FIELDS = [
    "headline_title",
    "trend_title", "trend_qty_title",
    "structure_intro_title", "category_mix_title", "premium_mix_title",
    "top_products_title", "brand_title",
    "milk_brand_title", "milk_brand_note",
    "pickup_title", "pickup_comment",
    "functional_title", "functional_note",
    "channel_title", "channel_comment",
    "concentration_title",
    "operations_title", "campaign_title", "campaign_bullets",
]

SYSTEM_PROMPT = """You are a retail analyst writing the commentary for a store's
monthly report. The readers are the store manager and an area manager. They can
already see the charts; what they want from the words is a reading of them.

BACKGROUND YOU NEED, BUT MUST NOT EXPLAIN BACK TO THEM
------------------------------------------------------
- `tier` is either premium or regular. This is NOT a price band and has nothing
  to do with how expensive something is. It is the store's own marker for
  "this is what we want staff to push". A cheap souvenir can be premium;
  an expensive tin of formula can be regular.
- So never describe premium as "high-value" or regular as "budget" or
  "volume lines", and never conclude from regular outselling premium that
  customers prefer cheaper goods. That misreads the flag entirely.
- Premium share tells you whether the range the store is pushing is moving.
  It says nothing about basket size or customer spending power.
- The store's direction is to grow premium. Frame suggestions with that in mind.
- The reader defined this scheme. Don't explain it to them, and don't work the
  word "push" into every other sentence.

RULES — breaking any one of these makes the output unusable
------------------------------------------------------------
1. Use only numbers present in report_data. Never compute a new percentage,
   difference or ratio, however simple. Month-on-month figures are already
   calculated in `computed` — quote those.
2. Every field needs a point, not a restatement. "X is 45% of revenue" alone is
   not commentary. Either say what follows from it, or place two figures side
   by side so the reader draws the conclusion.
3. Seasonality: holidays_context lists the public holidays for each month. When
   a month moves sharply and that month contains a relevant holiday, say so —
   particularly Chinese New Year, when cross-border freight stops. Hedge it:
   "likely related to", "typically affected by". Never state it as established
   cause. If the month has no relevant holiday, don't reach for one.
4. No empty praise. "Demonstrates the effectiveness of our strategy" and
   similar are banned even when a number supports them. Whether something
   worked is the reader's call; lay out the evidence.
5. Don't grade performance either way — no "encouraging results", no
   "disappointing". State what happened.
6. Suggestions, when you make them, are concrete store-floor actions:
   "give the premium range more shelf space at the counter". Not diagnoses
   ("penetration is low and requires improvement"), and nothing above store
   level — pricing, supplier terms and marketing budget aren't the reader's
   to set.
7. Comment fields (pickup_comment, channel_comment, functional_note) run to
   1-2 sentences. Titles are one line, under 90 characters, no full stop.
8. Register: written business English, plain and specific. No exclamation
   marks, no "surged" or "plummeted". Not stiff either — "closely aligned
   with", "as outlined above" and similar filler add nothing.
9. In a ranking, don't compare across categories. Milk powder has a much higher
   unit price than supplements, so "brand A beat brand B" across the two says
   nothing. Use each brand's main_category and name the leader within a
   category. Avoid "well ahead of second place".
10. Each field describes its own chart. Don't borrow a figure from another
    slide: quoting a brand's share of its category on a slide showing share of
    total store revenue leaves the reader thinking the chart is wrong.
11. Never write "all" or "every" about a list unless you have checked each row.
    Say what the top two or three are instead.
12. Currency is New Zealand dollars: write NZD or NZ$.
13. Direction words must match the sign. A negative in `computed` is a fall.
    Writing "down 40.0%" without the minus is fine; calling it growth is not.
14. campaign_bullets: turn activity_description into 2-4 lines, one per line,
    "who it applies to: what the offer is". If several mechanics apply to the
    same products, that is one campaign — put it on one line rather than
    repeating the same prefix three times. Invent nothing.
15. Counting claims must be checked against the series, and the series is
    short. A run of N declines needs N+1 data points; the trend window is four
    months, so there are at most three transitions and often fewer. Write
    "fell in both February and March", which the reader can verify by looking
    at the chart, rather than counting a run whose start is not in the data.
16. Return valid JSON. Keys from NARRATIVE_FIELDS only, all values strings
    (campaign_bullets joins its lines with \\n). If you can't do a field well,
    leave the key out — the pipeline has a sensible fallback. Don't pad.
"""


def build_user_prompt(report_data, holidays):
    return (
        "report_data — every number must come from here, do not derive new ones:\n"
        + json.dumps(report_data, ensure_ascii=False, indent=1)
        + "\n\nholidays_context — public holidays for the months in scope, "
          "for judging whether a movement is seasonal:\n"
        + json.dumps(holidays, ensure_ascii=False, indent=1)
        + "\n\nWrite the fields listed in NARRATIVE_FIELDS. Return JSON."
    )


def parse_json_lenient(text):
    """Parse the reply, tolerating a trailing comma.

    Models add one often enough, and Python's json is stricter than most
    parsers about it. Failing the whole run over a comma wastes a paid call for
    output that is otherwise fine.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Reply is not valid JSON ({exc}). Raw text below — it is "
                f"usually one character away from usable, and can be fixed by "
                f"hand into narrative.json:\n\n{text}") from exc


def call_model(report_data, holidays):
    import anthropic

    client = anthropic.Anthropic(api_key=API_KEY)
    response = client.messages.create(
        model=MODEL,
        # Generous, because this model emits a reasoning block first and that
        # comes out of the same budget. Too small and the reply is cut off
        # mid-thought, leaving a response with no text block at all.
        max_tokens=16000,
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT + "\n\nNARRATIVE_FIELDS = " + json.dumps(NARRATIVE_FIELDS),
        messages=[{"role": "user",
                   "content": build_user_prompt(report_data, holidays)}],
    )

    # Not every block is text — a reasoning block can come first.
    text_blocks = [b.text for b in response.content
                   if getattr(b, "type", None) == "text"]
    if not text_blocks:
        raise RuntimeError(
            f"No text in the reply (stop_reason={response.stop_reason}, "
            f"blocks={[getattr(b, 'type', '?') for b in response.content]}). "
            "If stop_reason is max_tokens, raise the limit.")

    text = re.sub(r"^```(json)?|```$", "", text_blocks[0].strip(),
                  flags=re.MULTILINE).strip()
    return parse_json_lenient(text)


def main():
    print(describe())

    with open(work_path("report_data.json"), encoding="utf8") as f:
        report_data = json.load(f)

    holidays_path = reference_path("holidays.json")
    all_holidays = {}
    if os.path.exists(holidays_path):
        with open(holidays_path, encoding="utf8") as f:
            all_holidays = json.load(f)
    else:
        print("! holidays.json missing — no seasonal attribution this run")

    # Only the months actually on the charts.
    periods = {report_data["period"]}
    for key in ("monthly_trend", "channel_trend", "functional_trend",
                "pickup_tier_trend"):
        periods.update(r["period"] for r in report_data.get(key, []))
    holidays = {p: all_holidays[p] for p in sorted(periods) if p in all_holidays}

    if not API_KEY:
        print("\nANTHROPIC_API_KEY not set — skipping.")
        print("The deck will build with rule-composed wording: the same "
              "figures, just plainer.")
        return 0

    narrative = call_model(report_data, holidays)
    narrative = {k: v for k, v in narrative.items() if k in NARRATIVE_FIELDS}

    missing, sign_only = grounding.check(narrative, report_data, holidays)

    if missing:
        print(f"\n{len(missing)} number(s) could not be traced to the source "
              "(possibly invented — check each):")
        for finding in missing:
            print("  -", finding)
    if sign_only:
        print(f"\n{len(sign_only)} sign mismatch(es) (usually fine, worth a glance):")
        for finding in sign_only:
            print("  -", finding)
    if not missing and not sign_only:
        print("\nGrounding check passed — every figure traces to the source.")

    with open(work_path("narrative.json"), "w", encoding="utf8") as f:
        json.dump(narrative, f, ensure_ascii=False, indent=2)
    print(f"\nnarrative.json written, {len(narrative)} field(s)")

    # 3 means "produced, but needs review". The orchestrator repeats this at
    # the very end — a warning in the middle of a long run scrolls away, and by
    # the time a wrong figure is noticed it is already on a slide.
    return 3 if missing else 0


if __name__ == "__main__":
    sys.exit(main() or 0)

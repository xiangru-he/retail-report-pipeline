# Retail monthly report pipeline

Two spreadsheets in, a finished slide deck out, in one command.

```
python monthly.py 2026-04
```

Built for a real shop — a health-products retailer in Auckland selling
supplements, milk powder and honey to walk-in customers and to parcel-forwarding
customers overseas. The monthly report used to take most of a day in Excel. It
now takes about four minutes, and the person running it is the store manager,
not a developer.

The code here is the same pipeline running against **synthetic data**. Real
per-SKU revenue and supplier names belong to the business, so `tools/make_synthetic_data.py`
generates a stand-in dataset with invented brands that preserves the shape of
the real four months, including a February collapse in export volume that the
report has to explain.

---

## Contents

- [What it produces](#what-it-produces)
- [The problem](#the-problem)
- [Architecture](#architecture)
- [The part I'd want to talk about: checking the model's numbers](#the-part-id-want-to-talk-about-checking-the-models-numbers)
- [Where the language model is allowed to operate](#where-the-language-model-is-allowed-to-operate)
- [Design decisions](#design-decisions)
- [Bugs that changed the design](#bugs-that-changed-the-design)
- [Running it](#running-it)
- [Repository layout](#repository-layout)
- [Tests](#tests)

---

## What it produces

![Four slides from the generated deck](docs/images/deck_overview.png)

A twelve-slide deck: headline figures, four-month revenue and volume trends,
category mix, best sellers, brand rankings, in-store pickup composition,
supplement types over time, local versus export channel movement, revenue
concentration, and the month's operating context.

A complete sample sits in [`output/2026-04/`](output/2026-04/) — the deck plus
the `report_data.json` and PNGs it was built from. It was generated with
`--no-llm`, so every heading you see there is the rule-composed fallback; that
is what a reviewer gets by cloning this repo with no API key.

Charts are matplotlib PNGs; the commentary is real text in the slide, not baked
into an image. Every heading and note is either drafted by a language model and
checked against the source, or — with no API key present — composed from the
same figures by rule.

---

## The problem

The store had its sales data, and no way to see it.

The point-of-sale system exports a wide spreadsheet: one row per SKU, three
columns per month (`jan_order`, `jan_qty`, `jan_amt`). A second spreadsheet
splits volume by channel. Everything a manager might want to know — is the
premium range moving, which brands are growing, why did February fall off a
cliff — was in there, and getting it out meant an afternoon of pivot tables.

Three things make it more than a charting exercise:

**The categories are not in the data.** Nothing in the export says whether an
SKU is a supplement or milk powder, or whether it's part of the range the store
is pushing. That knowledge lives in the manager's head. It has to be captured
once and then remembered, or the work is the same every month.

**The interesting movements need context the data doesn't have.** February's
export volume fell 40%. The database cannot know that Chinese New Year ran
15–23 February and cross-border freight stops for roughly two weeks either side.

**The person running it is not technical.** A pipeline that needs someone to
edit a SQL file each month is a pipeline that gets abandoned in month three.

---

## Architecture

```
data/raw/2026-04.xlsx     ─┐
data/raw/2026-04p.xlsx    ─┤
                           │
                    ┌──────▼────────────────────────────┐
                    │  IMPORT  (run_import.py)          │
                    │                                   │
                    │  phase 1  parse, find what's new  │
                    │           ────── stops here ──────┼──► a person answers
                    │  phase 2  classify and load       │      2 questions
                    └──────┬────────────────────────────┘
                           │
                    ┌──────▼─────────────────────────────┐
                    │  MySQL star schema                 │
                    │                                    │
                    │  dim_product ◄── the memory:       │
                    │    category / tier / shipping,     │
                    │    settled once, reused forever    │
                    │  dim_date  dim_store               │
                    │  fact_sales  fact_channel          │
                    │  monthly_context  report_config    │
                    └──────┬─────────────────────────────┘
                           │
                    ┌──────▼───────────────────────────────────────┐
                    │  REPORT  (run_report.py)                     │
                    │                                              │
                    │  12  every query → report_data.json          │
                    │      (all arithmetic happens here)           │
                    │  13  language model writes prose             │
                    │      → grounding check → narrative.json      │
                    │  14  matplotlib → chart_*.png                │
                    │  15  pptxgenjs → the deck                    │
                    └──────┬───────────────────────────────────────┘
                           │
              output/2026-04/monthly_report_2026-04.pptx
```

`monthly.py` wraps both halves so the month is given once.

---

## The part I'd want to talk about: checking the model's numbers

A language model writing about a table will occasionally produce a number that
looks right and isn't.

It happened. The month's revenue was **78,427.85**. The generated headline said
**84,427.85**. Nothing crashed, no rule was broken, and the figure went onto the
title slide of a deck that reached the store owner.

The prompt already said *use only numbers from the data*. It said so clearly. The
model still slipped a digit. That's the lesson worth extracting: **for numeric
output, prompting is not a control — it's a request.** So the output is checked
mechanically instead of trusted.

`pipeline/grounding.py` pulls every number-shaped token out of the generated text
and confirms each one appears somewhere in `report_data.json` or the holiday
calendar, allowing for rounding. Findings are split in two:

| | meaning | what to do |
|---|---|---|
| `missing` | not in the source at all — likely invented | check before publishing |
| `sign_only` | magnitude matches, sign doesn't | glance at the direction word |

The split matters more than it sounds. `sign_only` fires constantly and is nearly
always benign — the model writes "fell 42.35%" for a stored `-42.35`, which reads
better than a minus sign. Without separating them, the common harmless case
buries the rare serious one and the whole check gets ignored within a month.

Two special cases in the tokeniser, both from real false alarms:

```python
if token.startswith("-"):
    following = text[match.end():]
    if DATE_WORDS.match(following):
        token = token[1:]          # "15-23 Feb" — a range, not a minus
```

An early version read `15-23 Feb` as `15` and `-23` and reported a perfectly good
holiday date as unsourced. The obvious fix — treat a hyphen between digits as a
range — was worse: it turned a genuine `-42.35%` positive, which is exactly how a
fabrication could hide. The rule that satisfies both is narrow: a hyphen is a
range separator only when a date word follows.

When the check finds something, step 13 exits 3, and `run_report.py` **repeats
the warning after the filename at the end of the run**. A warning printed in the
middle scrolls away while the charts render; by the time anyone notices, the
wrong figure is already on a slide.

`tests/test_grounding.py` reproduces the original fabrication as its first test.

---

## Where the language model is allowed to operate

```
arithmetic  ->  Python (step 12, in `computed`)
wording     ->  the model
```

Every percentage the report quotes is calculated in SQL and Python, rounded, and
handed to the model as a finished number. The prompt forbids deriving any new
one, "however simple". An earlier version let the model work out month-on-month
from raw totals and it produced figures that were in no version of the data.

The model's actual job is narrow: read a number that is already correct, and say
what it means.

On February's channel slide, the two paths give:

**Rule-composed** — what the committed sample deck contains, and what you get
with no API key:

> Export fell 40.0%, local fell 9.1%

**Model-drafted**, once it has passed the grounding check:

> Export volume fell 40.0% while local fell only 9.1% — a gap consistent with
> the Chinese New Year freight pause (15–23 Feb) rather than a change in local
> demand

Both are accurate and both quote the same two pre-computed numbers. The second
is the one a manager can act on. The attribution comes from a holiday calendar
loaded as context, and it is hedged, because the data supports correlation and
not cause.

To see this on your own data, run step 13 once with a key and commit the
resulting `narrative.json` — it is a plain JSON file of strings, so the deck
will use it on every subsequent build without another API call.

### The prompt is a list of past failures

`step13_generate_narrative.py` carries fifteen numbered rules. Each exists
because the model did the thing it forbids, and each is stored with its reason —
a rule without its reason gets deleted by the next person who finds it fussy.

| rule | what prompted it |
|---|---|
| never compute a new percentage | derived month-on-month from raw totals, invented figures |
| `tier` is not a price band | called premium "high-value" and regular "budget lines" |
| no cross-category brand comparisons | ranked a milk powder brand against a supplement brand on revenue, which means nothing when unit prices differ by 10× |
| each field uses only its own slide's data | quoted a brand's share *of its category* on the slide showing share *of the store* — the chart looked wrong |
| no verdicts, in either direction | opened with "demonstrates the effectiveness of our strategy" |
| store-floor actions only | recommended renegotiating supplier terms, which is not the reader's to set |
| direction words must match the sign | called a fall growth |

That fourth rule is the subtle one. Both numbers were real, both were in the
source, and the grounding check passed — the figure was simply answering a
different question from the chart beside it. Mechanical verification catches
invention; it cannot catch a true number in the wrong place. That still needs
a prompt rule and a reader.

`tier` deserves a note too. It marks the range the store wants staff to
recommend. It is **not** a price band — a cheap souvenir can be premium, an
expensive tin of formula regular. Every model I gave this to assumed otherwise
and started writing about customer spending power, so the correction is now the
first thing in the system prompt.

---

## Design decisions

### The database is the memory

`dim_product` holds each SKU's category, tier and shipping mode. Once a product
is classified, it is never asked about again.

This is what makes the thing sustainable. Month one asked about 60 brands. Month
four asked about 4 — only genuinely new products. The manual work shrinks toward
zero on its own, without anyone maintaining a mapping file.

### Two questions a machine shouldn't answer

`run_import.py` stops for exactly two things, and exits `2` — meaning *a person
is needed*, distinct from `1` for failure:

1. **A brand with no category.** New supplier, nobody has said what they sell.
2. **A product that disagrees with its brand.** A "sheep placenta 60 capsules"
   under a brand mapped to milk powder — usually the brand is right and this
   product is the exception.

Guessing at either corrupts every later report, and nothing about the result
looks wrong. So they become a CSV with blanks, and the run resumes when they're
filled in. The answers land in `dim_product` and are never asked again.

### Tier by rule, not by SKU list

```python
PREMIUM_BRANDS = ["orama", "nonie", ...]        # whole brand
SKU_RULES = [
    {"brand": "clearfield", "keywords": ["immune", "digestion"],
     "local_pickup_only": True},                 # part of a brand
]
```

The first version was a list of SKU codes. Codes change when a supplier reissues
a product; the tier doesn't. `tier_rules.py` raises **on import** if a brand
appears in both lists — that combination makes the narrowing rule unreachable
dead code that reads as though it works. (I wrote that bug into this repo and
the guard caught it.)

### The fuzzy threshold is measured, not guessed

Brand names arrive spelled inconsistently — capitalisation, a missing space, the
occasional typo. `difflib` at 0.85 handles it.

A threshold set too low silently merges two real brands: one brand's revenue
vanishes into another's bar and the chart looks entirely plausible. So the
constant is justified by measurement, and there's a test that keeps it honest —
it scores every pair of genuinely different brands and asserts the closest pair
still sits below the threshold. On the real list the worst pair scored 0.706.

### One switch for the reporting month

`report_config.rpt_period` — one row, one value, read by every query.

It's a table rather than a session variable because each script opens its own
connection, and a `@variable` set in one is gone in the next; that produced NULLs
that looked like missing data rather than an error. The `config_id` primary key
makes changing it a genuine upsert — without it, "change the month" could insert
a second row, and every query does `LIMIT 1`.

### Degrading instead of failing

No API key, or the call fails? The deck still builds. Every heading falls back
to a sentence composed from the same figures — accurate, just flatter. In the
deck code that's one function:

```js
function text(field, fallback) {
  const value = N[field];
  return (typeof value === "string" && value.trim()) ? value.trim() : fallback;
}
```

A report that can't be produced on a given evening is worse than a plain one.
It also means **you can clone this repo and get a complete deck without an API
key** — `python monthly.py 2026-04 --no-llm`.

### Sparse facts

No row in `fact_sales` means no sales, not zero. Writing zeros for every SKU in
every month it didn't sell would multiply the table by roughly twenty for no
information gain, and `SUM` over missing rows already returns what you want.

### Re-running is always safe

Every load is `INSERT ... ON DUPLICATE KEY UPDATE` keyed on `(period, store, sku)`.
Importing the same month twice overwrites rather than doubling. This matters more
than it sounds — the natural response to "did that work?" is to run it again.

---

## Bugs that changed the design

The ones that taught me something, rather than a full list.

**A trend query with no upper bound.** Building March's report showed April's
data in the trend chart. Every query filtered `period >= start` and none filtered
`period <= rpt_period`, because when the code was written there *was* no later
month. Nothing errored; the chart was simply describing a different month from
its title. Now `period <= rpt_period` is on every trend query and there's a test
for the boundary.

**The archive wildcard.** `output/2026-02/` kept acquiring March's deck. The
archive step globbed `*.pptx` out of the working directory and swept in whatever
was there. The only symptom was two files in a folder that should have had one —
and if you opened the wrong one, a plausible deck about the wrong month. Now the
filename is period-specific and strays are removed.

**The month-on-month card showed the wrong month.** The channel slide picked the
*most negative* month rather than the *latest* — I'd written it while looking at
February, where those were the same. March's deck printed February's −40%.
Test data that only covers the case you were thinking about will confirm
whatever you already believe.

**Month names hardcoded in four places.** Adding April meant editing four
scripts, and missing one produced a `KeyError` several minutes into a run — one
script at a time, so it took several passes to get through. Fixing them
individually as each error appeared was the wrong instinct; deriving all of them
from `months_for()` was the fix.

**Step 2 wiped hand-filled categories.** It regenerated the brand-category CSV
from scratch each month, blanking 25 brands the manager had classified by hand.
The next run then asked about all of them again. Now there's a three-tier
precedence: previous CSV wins, then known defaults, then blank.

**`getpass()` on a non-interactive terminal.** Hung forever with no output, which
is the worst failure mode there is — it looks like slow work. Now it raises with
a message naming the environment variable.

**A hardcoded password in five files.** Mine, in the first version. Moved to
environment variables with no default, and there's a test asserting the default
hasn't come back.

---

## Running it

### Requirements

MySQL 8, Python 3.10+, Node 18+ (for the deck step only).

```bash
git clone <this repo> && cd retail-report-pipeline

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install

cp .env.example .env        # fill in MYSQL_PASSWORD
set -a && source .env && set +a

mysql -u root -p < sql/schema.sql
```

### The synthetic dataset

`data/raw/` already contains four months. To regenerate:

```bash
python tools/make_synthetic_data.py
```

### A month

```bash
python monthly.py 2026-01     # first month: expect a stop for classification
# fill in the CSV it names
python monthly.py 2026-01 --resume

python monthly.py 2026-02     # fewer questions
python monthly.py 2026-03     # fewer still
python monthly.py 2026-04
```

Without an `ANTHROPIC_API_KEY`, add `--no-llm` and the deck builds with
rule-composed wording.

### What a month looks like for the manager

1. Drop the two spreadsheets into `data/raw/`
2. Add a row to `data/reference/monthly_context.csv` — foot traffic, campaigns
   (these aren't in the POS; somebody types them)
3. `python monthly.py 2026-05`
4. Answer anything it stops to ask, then `--resume`

---

## Repository layout

```
monthly.py                 one command per month
run_import.py              spreadsheets → database, stops for judgement calls
run_report.py              database → deck, repeats warnings at the end

pipeline/
  config.py                month plumbing, paths, credentials from env
  db.py                    connection, the reporting-month switch, dim_product reads
  tier_rules.py            premium/regular rules, fuzzy brand matching
  grounding.py             the numeric verifier
  step01..step07           parse and classify (the human checkpoints live here)
  step08..step11           load into MySQL
  step12_fetch_report_data.py    every query → JSON; all arithmetic
  step13_generate_narrative.py   the model, the prompt rules, the check
  step14_render_charts.py        matplotlib
  step15_build_deck.js           pptxgenjs

sql/schema.sql             star schema, with the reasoning in comments
tools/make_synthetic_data.py   generates data/raw/
tests/                     pytest
data/reference/            human-maintained: categories, overrides, holidays,
                           monthly context
output/<period>/           finished deck plus the JSON and PNGs it came from
```

Why one JS file in a Python project: `pptxgenjs` expresses this layout in about
a third of the lines `python-pptx` needs, and the boundary between the two is a
JSON file, so the languages don't have to agree.

---

## Tests

```bash
pytest
```

40 tests. The ones worth reading:

- `test_grounding.py` — first test reproduces the 84,427.85 fabrication; the rest
  guard against false alarms, because a check that cries wolf gets switched off
- `test_tier_rules.py` — scores every pair of real brands and asserts the closest
  pair sits below the fuzzy threshold
- `test_config_and_maths.py` — month-column derivation, month-on-month chain
  length, zero baselines, and that rounding survives (an unrounded
  `42.35000000000001` would never match `"42.35"` in the grounding check)

---

## A note on the data

Everything in `data/` is synthetic. Brands, product names and the store are
invented; the figures are generated to match the real dataset's shape — four
months, a February trough, an export channel that moves independently of the
local one — without reproducing any real commercial figure.

The February movement is designed rather than random: export volume falls 40%,
local falls 9%, and both recover in March. That asymmetry is the thing the
report has to explain, and it's what makes the holiday-attribution logic worth
having.

---

MIT licensed.

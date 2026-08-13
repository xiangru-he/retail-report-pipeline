"""
Step 14 — render the charts as PNGs.

INPUT   data/work/report_data.json
OUTPUT  data/work/chart_*.png

Charts are rendered here rather than built with the deck library because
matplotlib gives control the PowerPoint chart API doesn't: gradient bars, a
consistent dark theme, labels placed where they don't collide. The deck step
just places the images.

Nothing in this file reads the database or recomputes anything — every figure
comes from report_data.json, same as the narrative. That's what keeps the
chart and the sentence beside it in agreement.

No month name is hard-coded. An early version had "March" written into four
chart titles; February's report went out with March in the headings.
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Wedge

from config import CATEGORY_LABELS, PRODUCT_TYPE_LABELS, TREND_MONTHS, describe, work_path

BG = "#0B0F1F"
CARD = "#141A33"
CARD_EDGE = "#232B52"
MUTED = "#8B93B8"
WHITE = "#FFFFFF"
BLUE = "#5E8CFF"
CYAN = "#56D6D6"
PURPLE = "#B084F5"
GREEN = "#4ADE80"
RED = "#F2596B"
ORANGE = "#F2A65A"
SERIES_COLOURS = [BLUE, CYAN, PURPLE, GREEN, ORANGE, RED,
                  "#9B7BFF", "#82E6B0", "#E29CFF", "#5D6AA8"]

TIER_COLOURS = {"premium": BLUE, "milk_powder": CYAN, "regular": PURPLE}
TIER_NAMES = {"premium": "Premium", "milk_powder": "Milk Powder", "regular": "Regular"}

with open(work_path("report_data.json"), encoding="utf8") as f:
    DATA = json.load(f)

PERIOD_LABEL = DATA["period_label"]
COMPUTED = DATA["computed"]


def glow(colour, layers=4, width=10):
    """Soft halo behind text — widest and faintest first."""
    return [pe.withStroke(linewidth=width * i / layers, foreground=colour, alpha=0.10)
            for i in range(layers, 0, -1)] + [pe.Normal()]


def card(ax, x, y, w, h, face=CARD, edge=CARD_EDGE):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.018",
        linewidth=1.1, edgecolor=edge, facecolor=face, mutation_aspect=1, zorder=1))


def gradient_bar(ax, x, y, length, height, left, right, steps=200):
    cmap = LinearSegmentedColormap.from_list("g", [left, right])
    ax.imshow(np.linspace(0, 1, steps).reshape(1, steps),
              extent=[x, x + length, y, y + height],
              aspect="auto", cmap=cmap, zorder=2, interpolation="bilinear")


def new_figure(w, h):
    return plt.figure(figsize=(w, h), dpi=200, facecolor=BG)


def style_axes(ax):
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(CARD_EDGE)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.grid(axis="y", color="#1C2340", linewidth=0.8)
    ax.set_axisbelow(True)


def label_segments(ax, xs, bottoms, heights, fmt, min_share=0.035):
    """Value inside each stacked segment, skipped when the segment is too
    short for the text to be readable."""
    span = max((b + h for b, h in zip(bottoms, heights)), default=1)
    for x, bottom, height in zip(xs, bottoms, heights):
        if height <= 0 or height < span * min_share:
            continue
        ax.text(x, bottom + height / 2, fmt(height), ha="center", va="center",
                fontsize=9, color=WHITE, fontweight="bold", zorder=4,
                path_effects=[pe.withStroke(linewidth=2.5, foreground=BG)])


def save(fig, name):
    fig.savefig(work_path(name), facecolor=BG)
    plt.close(fig)
    print(f"  {name}")


# ---------------------------------------------------------------------------
def chart_headline():
    """Three KPI cards plus the tier split."""
    fig = new_figure(13.3, 5.7)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off"); ax.set_facecolor(BG)

    head = DATA["headline"]
    cards = [(f"${head['total_amount']:,.2f}", f"{PERIOD_LABEL} revenue (NZD)", BLUE),
             (f"{head['total_qty']:,.0f}", "units sold", CYAN),
             (f"{head['total_orders']:,.0f}", "orders", PURPLE)]
    w, h, gap, x0, y0 = 0.30, 0.34, 0.025, 0.03, 0.60
    for i, (value, label, colour) in enumerate(cards):
        x = x0 + i * (w + gap)
        card(ax, x, y0, w, h)
        ax.text(x + w / 2, y0 + h * 0.62, value, ha="center", va="center",
                fontsize=27, color=WHITE, fontweight="bold",
                path_effects=glow(colour), zorder=3)
        ax.text(x + w / 2, y0 + h * 0.22, label, ha="center", va="center",
                fontsize=13, color=MUTED, zorder=3)

    # Reversed, because the bars are drawn bottom-up: this puts the largest
    # bucket at the top where the eye lands first.
    tiers = sorted(head["tiers"], key=lambda t: t["amount"])
    total = sum(t["amount"] for t in tiers)
    bx, by, bw, bh, bgap = 0.03, 0.06, 0.94, 0.15, 0.045
    for i, tier in enumerate(tiers):
        y = by + i * (bh + bgap)
        card(ax, bx, y, bw, bh)
        share = tier["amount"] / total if total else 0
        colour = TIER_COLOURS.get(tier["bucket"], BLUE)
        gradient_bar(ax, bx + 0.16, y + bh * 0.30, (bw - 0.22) * share, bh * 0.40,
                     colour, CARD_EDGE)
        ax.text(bx + 0.02, y + bh / 2, TIER_NAMES.get(tier["bucket"], tier["bucket"]),
                ha="left", va="center", fontsize=13, color=WHITE,
                fontweight="bold", zorder=3)
        ax.text(bx + bw - 0.02, y + bh / 2,
                f"${tier['amount']:,.0f}   ({share * 100:.1f}%)",
                ha="right", va="center", fontsize=12, color=MUTED, zorder=3)
    save(fig, "chart_headline.png")


def _trend_figure(value_key, formatter, title, mom_key, mom_label, filename):
    """Stacked monthly bars with month-on-month cards down the right."""
    periods = COMPUTED["trend_periods"]
    labels = COMPUTED["trend_labels"]
    buckets = ["premium", "milk_powder", "regular"]

    values = {b: [] for b in buckets}
    for period in periods:
        for bucket in buckets:
            values[bucket].append(sum(
                r[value_key] for r in DATA["monthly_trend"]
                if r["period"] == period and r["bucket"] == bucket))

    fig = new_figure(8.4, 5.3)
    ax = fig.add_axes([0.10, 0.16, 0.57, 0.72])
    style_axes(ax)

    x = np.arange(len(periods))
    bottoms = np.zeros(len(periods))
    for bucket in buckets:
        heights = np.array(values[bucket], dtype=float)
        ax.bar(x, heights, 0.5, bottom=bottoms, color=TIER_COLOURS[bucket],
               label=TIER_NAMES[bucket], zorder=3)
        label_segments(ax, x, bottoms, heights, formatter)
        bottoms += heights

    ceiling = bottoms.max() * 1.25 if len(bottoms) else 1
    for i, total in enumerate(bottoms):
        ax.text(i, total + ceiling * 0.025, formatter(total), ha="center",
                fontsize=11, color=WHITE, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([l.split()[0] for l in labels], fontsize=12)
    ax.set_ylim(0, ceiling)
    ax.set_title(title, color=WHITE, fontsize=13, fontweight="bold", pad=12)
    legend = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3,
                       frameon=False, fontsize=10)
    for text in legend.get_texts():
        text.set_color(MUTED)

    mom = COMPUTED[mom_key]
    cax = fig.add_axes([0.71, 0.10, 0.27, 0.82])
    cax.axis("off"); cax.set_xlim(0, 1); cax.set_ylim(0, 1)
    if mom:
        height = 0.90 / len(mom)
        for i, value in enumerate(mom):
            y = 1.0 - (i + 1) * height + 0.03
            card(cax, 0.0, y, 1.0, height - 0.06)
            cax.text(0.5, y + (height - 0.06) * 0.62, f"{value:+.1f}%",
                     ha="center", va="center", fontsize=21, color=WHITE,
                     fontweight="bold",
                     path_effects=glow(RED if value < 0 else GREEN))
            cax.text(0.5, y + (height - 0.06) * 0.20,
                     f"{labels[i].split()[0]} to {labels[i + 1].split()[0]}\n{mom_label}",
                     ha="center", va="center", fontsize=9, color=MUTED)
    else:
        cax.text(0.5, 0.5, "First month —\nnothing to compare", ha="center",
                 va="center", fontsize=11, color=MUTED)
    save(fig, filename)


def chart_trend_amount():
    _trend_figure("amount", lambda v: f"${v:,.0f}",
                  f"{COMPUTED['trend_labels'][0]} to {COMPUTED['trend_labels'][-1]} "
                  "revenue (NZD)", "amount_mom_pct", "revenue", "chart_trend_amount.png")


def chart_trend_qty():
    _trend_figure("qty", lambda v: f"{v:,.0f}",
                  f"{COMPUTED['trend_labels'][0]} to {COMPUTED['trend_labels'][-1]} "
                  "units sold", "qty_mom_pct", "units", "chart_trend_qty.png")


def chart_category_mix():
    """Two donuts: share of revenue and share of units.

    Both are shown because they disagree, and the disagreement is the point —
    milk powder can be a large share of revenue on a small share of units.
    """
    cats = sorted(DATA["category_mix"]["categories"], key=lambda c: -c["amount_pct"])
    names = [CATEGORY_LABELS.get(c["category"], c["category"]) for c in cats]
    colours = SERIES_COLOURS[:len(cats)]

    fig = new_figure(14.6, 5.6)

    def donut(x0, values, total, unit, title):
        ax = fig.add_axes([x0, 0.10, 0.44, 0.80])
        ax.set_xlim(-1.95, 1.95); ax.set_ylim(-1.6, 1.6); ax.axis("off")
        start = 90
        for i, (share, colour, name, cat) in enumerate(zip(values, colours, names, cats)):
            theta = share / 100 * 360
            ax.add_patch(Wedge((0, 0), 1.12, start - theta, start, width=0.30,
                               facecolor=colour, alpha=0.16, linewidth=0))
            ax.add_patch(Wedge((0, 0), 1.0, start - theta, start, width=0.32,
                               facecolor=colour, edgecolor=BG, linewidth=2))
            mid = np.radians(start - theta / 2)
            # Labels alternate between two radii so neighbouring ones don't collide.
            radius = 1.45 if i % 2 == 0 else 1.72
            ax.plot([1.02 * np.cos(mid), radius * np.cos(mid)],
                    [1.02 * np.sin(mid), radius * np.sin(mid)],
                    color=colour, linewidth=1.0, zorder=4)
            align = "left" if np.cos(mid) >= 0 else "right"
            ax.text(radius * np.cos(mid) + (0.04 if align == "left" else -0.04),
                    radius * np.sin(mid),
                    f"{name} {share}%\n${cat['amount']:,.0f} | {cat['qty']:,.0f} units",
                    ha=align, va="center", fontsize=8.5, color=WHITE, linespacing=1.3)
            start -= theta
        ax.text(0, 0.10, title, ha="center", va="center", fontsize=13,
                color=WHITE, fontweight="bold")
        ax.text(0, -0.14, f"{total:,.0f}{unit}", ha="center", va="center",
                fontsize=10, color=MUTED)

    donut(0.03, [c["amount_pct"] for c in cats],
          DATA["category_mix"]["total_amount"], " NZD", f"{PERIOD_LABEL} revenue share")
    donut(0.53, [c["qty_pct"] for c in cats],
          DATA["category_mix"]["total_qty"], " units", f"{PERIOD_LABEL} unit share")

    legend = fig.add_axes([0.03, 0.0, 0.94, 0.09])
    legend.axis("off"); legend.set_xlim(0, 1); legend.set_ylim(0, 1)
    x = 0.06
    for name, colour in zip(names, colours):
        legend.scatter([x], [0.5], s=100, c=colour, marker="s")
        legend.text(x + 0.014, 0.5, name, va="center", ha="left",
                    fontsize=10.5, color=MUTED)
        x += 0.014 + len(name) * 0.011 + 0.04
    save(fig, "chart_category_mix.png")


def chart_structure_intro():
    """Three cards opening the product-structure section.

    Deliberately just numbers on a card, no chart. It's a section divider, and
    a reader arriving at a new topic wants the scale of it before the detail.
    """
    si = DATA["structure_intro"]
    fig = new_figure(13.3, 3.1)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off"); ax.set_facecolor(BG)

    leading = CATEGORY_LABELS.get(si["leading_premium_category"],
                                  si["leading_premium_category"] or "-")
    cards = [
        (f"${si['premium_amount']:,.0f}", "premium revenue (NZD)", BLUE),
        (f"{si['premium_pct_of_store']:.1f}%", "of store revenue", CYAN),
        (f"{si['premium_in_top10']} / {si['top_n']}", "premium in the best sellers", PURPLE),
    ]
    w, h, gap, x0, y0 = 0.30, 0.62, 0.025, 0.03, 0.18
    for i, (value, label, colour) in enumerate(cards):
        x = x0 + i * (w + gap)
        card(ax, x, y0, w, h)
        ax.text(x + w / 2, y0 + h * 0.60, value, ha="center", va="center",
                fontsize=30, color=WHITE, fontweight="bold",
                path_effects=glow(colour), zorder=3)
        ax.text(x + w / 2, y0 + h * 0.20, label, ha="center", va="center",
                fontsize=12, color=MUTED, zorder=3)
    ax.text(0.5, 0.07, f"largest premium category: {leading} "
                       f"({si['leading_premium_pct']}% of premium)",
            ha="center", va="center", fontsize=11, color=MUTED)
    save(fig, "chart_structure_intro.png")


def chart_premium_mix():
    """What the premium range consists of, as a ranked card list.

    Shares are within premium, not of the store — the subtitle on the slide
    says so, because the same 'category %' phrasing appears two slides earlier
    against a different denominator.
    """
    rows = sorted(DATA["premium_mix"]["categories"], key=lambda c: -c["amount_pct"])
    fig = new_figure(13.3, 5.3)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off"); ax.set_facecolor(BG)

    if not rows:
        ax.text(0.5, 0.5, "No premium sales recorded this month",
                ha="center", va="center", fontsize=14, color=MUTED)
        save(fig, "chart_premium_mix.png")
        return

    height, gap, top = 0.122, 0.020, 0.88
    for i, row in enumerate(rows[:6]):
        y = top - i * (height + gap) - height
        colour = SERIES_COLOURS[i % len(SERIES_COLOURS)]
        card(ax, 0.03, y, 0.94, height)
        ax.add_patch(plt.Circle((0.075, y + height / 2), 0.020, color=colour, zorder=3))
        ax.text(0.11, y + height / 2,
                CATEGORY_LABELS.get(row["category"], row["category"]),
                ha="left", va="center", fontsize=13, color=WHITE,
                fontweight="bold", zorder=3)
        ax.text(0.46, y + height / 2, f"${row['amount']:,.2f}", ha="left",
                va="center", fontsize=12, color=WHITE, zorder=3)
        ax.text(0.68, y + height / 2, f"{row['qty']:,.0f} units", ha="left",
                va="center", fontsize=12, color=MUTED, zorder=3)
        ax.text(0.90, y + height / 2, f"{row['amount_pct']}%", ha="right",
                va="center", fontsize=13, color=colour, fontweight="bold", zorder=3)
    save(fig, "chart_premium_mix.png")


def chart_top_products():
    """Best sellers by units, premium and regular in different colours —
    the seat count is what the reader is actually looking for."""
    rows = sorted(DATA["top_products"], key=lambda r: r["rank"], reverse=True)
    fig = new_figure(12.3, 5.6)
    ax = fig.add_axes([0.34, 0.08, 0.61, 0.84])
    style_axes(ax)

    ceiling = max(r["qty"] for r in rows) if rows else 1
    for i, row in enumerate(rows):
        share = row["qty"] / ceiling
        left, right = ((BLUE, "#3A5BD9") if row["tier"] == "premium"
                       else (PURPLE, "#8B5CD1"))
        gradient_bar(ax, 0, i - 0.3, share, 0.6, left, right)
        ax.text(share + 0.015, i, f"{row['qty']:,.0f}", va="center",
                fontsize=10.5, color=WHITE, fontweight="bold")

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{r['brand']} {r['product_desc']}"[:44] for r in rows],
                       fontsize=9.5, color=WHITE)
    ax.set_xlim(0, 1.15); ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xticks([]); ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#1C2340", linewidth=0.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(f"{PERIOD_LABEL} best sellers by units", color=WHITE,
                 fontsize=13, fontweight="bold", pad=12)

    key = fig.add_axes([0.34, 0.955, 0.61, 0.04])
    key.axis("off"); key.set_xlim(0, 1); key.set_ylim(0, 1)
    for x, colour, name in [(0.0, BLUE, "Premium"), (0.10, PURPLE, "Regular")]:
        key.scatter([x], [0.5], s=110, c=colour, marker="s")
        key.text(x + 0.018, 0.5, name, va="center", fontsize=10, color=MUTED)
    save(fig, "chart_top_products.png")


def _ranked_bars(rows, label_key, value_key, note_fn, title, filename,
                 left=BLUE, right=CYAN, width=12.1, height=5.3):
    rows = sorted(rows, key=lambda r: r[value_key])
    fig = new_figure(width, height)
    ax = fig.add_axes([0.24, 0.09, 0.71, 0.80])
    style_axes(ax)
    ceiling = max((r[value_key] for r in rows), default=1)
    for i, row in enumerate(rows):
        gradient_bar(ax, 0, i - 0.3, row[value_key] / ceiling, 0.6, left, right)
        ax.text(row[value_key] / ceiling + 0.015, i, note_fn(row), va="center",
                fontsize=10.5, color=WHITE, fontweight="bold")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([str(r[label_key]) for r in rows], fontsize=11, color=WHITE)
    ax.set_xlim(0, 1.32); ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xticks([]); ax.grid(visible=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(title, color=WHITE, fontsize=13, fontweight="bold", pad=12)
    save(fig, filename)


def chart_brands():
    _ranked_bars(
        DATA["top_brands"], "brand", "amount",
        lambda r: f"${r['amount']:,.0f}  ({r['pct_of_store']:.1f}%)",
        f"{PERIOD_LABEL} top brands by revenue", "chart_brands.png")


def chart_milk_brands():
    _ranked_bars(
        DATA["milk_powder_brands"], "brand", "amount",
        lambda r: f"${r['amount']:,.0f}  ({r['pct_of_category']:.1f}%)",
        f"{PERIOD_LABEL} milk powder brands (pickup + shipped)",
        "chart_milk_brands.png", left=CYAN, right=BLUE)


def chart_pickup_tiers():
    """Premium share of in-store milk powder pickups, month by month."""
    periods = sorted({r["period"] for r in DATA["pickup_tier_trend"]})[-TREND_MONTHS:]
    fig = new_figure(12.1, 3.5)
    if not periods:
        ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
        ax.text(0.5, 0.5, "No in-store milk powder pickups on record",
                ha="center", va="center", fontsize=13, color=MUTED)
        save(fig, "chart_pickup_tiers.png")
        return

    step = 0.94 / len(periods)
    size = min(0.20, step * 0.9)
    for i, period in enumerate(periods):
        rows = [r for r in DATA["pickup_tier_trend"] if r["period"] == period]
        premium = sum(r["amount"] for r in rows if r["tier"] == "premium")
        regular = sum(r["amount"] for r in rows if r["tier"] == "regular")
        total = premium + regular
        share = premium / total if total else 0

        ax = fig.add_axes([0.03 + i * step, 0.08, size, 0.66])
        ax.set_xlim(-1.3, 1.3); ax.set_ylim(-1.3, 1.3); ax.axis("off")
        ax.add_patch(Wedge((0, 0), 1.0, 90 - share * 360, 90, width=0.34,
                           facecolor=BLUE, edgecolor=BG, linewidth=2))
        ax.add_patch(Wedge((0, 0), 1.0, -270, 90 - share * 360, width=0.34,
                           facecolor=PURPLE, edgecolor=BG, linewidth=2))
        ax.text(0, 0.05, f"{share * 100:.0f}%", ha="center", va="center",
                fontsize=13, color=WHITE, fontweight="bold")
        ax.text(0, -0.22, "premium", ha="center", va="center", fontsize=8.5, color=MUTED)
        ax.text(0, 1.28, rows[0]["period_label"].split()[0] if rows else period,
                ha="center", va="bottom", fontsize=11, color=WHITE, fontweight="bold")

    fig.text(0.03, 0.90, "In-store milk powder pickups: premium vs regular",
             color=WHITE, fontsize=13, fontweight="bold")
    save(fig, "chart_pickup_tiers.png")


MAX_SERIES = 6      # beyond this the lines are indistinguishable


def chart_functional_types():
    """Functional supplement types over time.

    Only the largest few types get their own line; the rest are summed into
    "Other". With every type plotted the chart had eleven lines, the palette
    started repeating colours, and nothing could be traced across the months —
    a legend that long is a list, not a chart.

    The right-hand panel is left empty on purpose — the deck writes the
    commentary there as real text, so it can change without re-rendering.
    """
    periods = sorted({r["period"] for r in DATA["functional_trend"]})
    fig = new_figure(8.6, 6.1)
    ax = fig.add_axes([0.09, 0.26, 0.62, 0.62])
    style_axes(ax)

    by_type = {}
    for row in DATA["functional_trend"]:
        by_type.setdefault(row["product_type"], {})[row["period"]] = row["qty"]

    # Rank on total volume across the window, not on the latest month, so a
    # single quiet month doesn't drop a type that is otherwise a mainstay.
    ranked = sorted(by_type, key=lambda t: -sum(by_type[t].values()))
    kept, rest = ranked[:MAX_SERIES], ranked[MAX_SERIES:]

    series_list = [(PRODUCT_TYPE_LABELS.get(t, t), by_type[t]) for t in kept]
    if rest:
        other = {p: sum(by_type[t].get(p, 0) for t in rest) for p in periods}
        series_list.append((f"Other ({len(rest)} types)", other))

    x = np.arange(len(periods))
    for i, (label, series) in enumerate(series_list):
        is_other = rest and i == len(series_list) - 1
        ax.plot(x, [series.get(p, 0) for p in periods], marker="o", markersize=4,
                linewidth=1.8 if is_other else 2.2,
                linestyle="--" if is_other else "-",
                color=MUTED if is_other else SERIES_COLOURS[i % len(SERIES_COLOURS)],
                label=label)

    ax.set_xticks(x)
    ax.set_xticklabels([p[5:7] + "/" + p[2:4] for p in periods], fontsize=11)
    ax.set_title("Functional supplement types (units)", color=WHITE,
                 fontsize=12, fontweight="bold", pad=12)
    legend = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3,
                       frameon=False, fontsize=9.5, handlelength=1.4, columnspacing=1.2)
    for text in legend.get_texts():
        text.set_color(MUTED)
    save(fig, "chart_functional_types.png")


def chart_channels():
    """Local vs export units, side by side.

    Grouped rather than stacked: the story is that the two move independently,
    and a stacked bar hides exactly that.
    """
    periods = COMPUTED["channel_periods"]
    labels = COMPUTED["channel_labels"]
    local = COMPUTED["local_qty"]
    export = COMPUTED["export_qty"]

    pct = {(r["period"], r["channel_group"]): r["qty_pct"] for r in DATA["channel_trend"]}

    fig = new_figure(7.6, 5.3)
    ax = fig.add_axes([0.11, 0.20, 0.84, 0.66])
    style_axes(ax)

    x = np.arange(len(periods))
    width = 0.36
    ax.bar(x - width / 2, local, width, color=BLUE, label="Local (walk-in + trade)", zorder=3)
    ax.bar(x + width / 2, export, width, color=RED, label="Export (parcels)", zorder=3)

    ceiling = max(local + export) * 1.30 if periods else 1
    for i, period in enumerate(periods):
        for offset, values, group in [(-width / 2, local, "local"),
                                      (width / 2, export, "export")]:
            share = pct.get((period, group))
            note = f"{values[i]:,.0f}\n{share:.1f}%" if share is not None else f"{values[i]:,.0f}"
            ax.text(x[i] + offset, values[i] + ceiling * 0.02, note, ha="center",
                    va="bottom", fontsize=9, color=WHITE, fontweight="bold",
                    linespacing=1.3)

    ax.set_xticks(x)
    ax.set_xticklabels([l.split()[0] for l in labels], fontsize=12)
    ax.set_ylim(0, ceiling)
    ax.set_title(f"{labels[0].split()[0]} to {labels[-1].split()[0]} units by channel",
                 color=WHITE, fontsize=13, fontweight="bold", pad=12)
    legend = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2,
                       frameon=False, fontsize=9.5)
    for text in legend.get_texts():
        text.set_color(MUTED)
    save(fig, "chart_channels.png")


def chart_concentration():
    """Cumulative revenue by SKU decile."""
    rows = sorted(DATA["sku_pareto"], key=lambda r: r["decile"])
    fig = new_figure(12.1, 4.9)
    ax = fig.add_axes([0.06, 0.13, 0.92, 0.75])
    style_axes(ax)
    for i, row in enumerate(rows):
        ax.bar(i, row["cumulative_pct"], 0.6, color=BLUE, zorder=3)
        ax.text(i, row["cumulative_pct"] + 2.5, f"{row['cumulative_pct']:.0f}%",
                ha="center", fontsize=9.5, color=WHITE, fontweight="bold")
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([f"top {r['decile'] * 10}%" for r in rows],
                       fontsize=9.5, color=WHITE)
    ax.set_ylim(0, 115)
    ax.set_title("Cumulative revenue by SKU decile", color=WHITE,
                 fontsize=13, fontweight="bold", pad=12)
    save(fig, "chart_concentration.png")


def main():
    print(describe())
    print(f"\nRendering charts for {PERIOD_LABEL}")
    for render in (chart_headline, chart_trend_amount, chart_trend_qty,
                   chart_category_mix, chart_structure_intro, chart_premium_mix,
                   chart_top_products, chart_brands,
                   chart_milk_brands, chart_pickup_tiers, chart_functional_types,
                   chart_channels, chart_concentration):
        render()
    print("\ndone")


if __name__ == "__main__":
    main()

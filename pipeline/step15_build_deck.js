/**
 * Step 15 — assemble the slide deck.
 *
 * INPUT   data/work/report_data.json
 *         data/work/narrative.json      (optional)
 *         data/work/chart_*.png
 * OUTPUT  output/<period>/monthly_report_<period>.pptx
 *
 *     node step15_build_deck.js
 *
 * WHY JAVASCRIPT IN AN OTHERWISE PYTHON PROJECT
 * ---------------------------------------------
 * python-pptx builds a deck by positioning shapes one at a time, which for a
 * layout like this runs to a lot of code. pptxgenjs takes the same layout in
 * roughly a third of the lines and produces a file PowerPoint opens without
 * complaint. The boundary is a JSON file, so the language on either side of it
 * doesn't have to match.
 *
 * NARRATIVE IS OPTIONAL
 * ---------------------
 * If narrative.json is absent — no API key, or the call failed — every heading
 * and note falls back to a sentence composed from the same figures. Same
 * numbers, plainer prose. The store gets its report either way.
 *
 * TEXT AND CHARTS ARE KEPT SEPARATE
 * ---------------------------------
 * Nothing written here is baked into a PNG. Commentary is real text boxes, so
 * fixing a word doesn't mean re-rendering an image. An early version had the
 * memo drawn into chart_milk_brands.png, and correcting one sentence meant
 * regenerating the chart.
 */
const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const WORK = path.join(ROOT, "data", "work");

const DATA = JSON.parse(fs.readFileSync(path.join(WORK, "report_data.json"), "utf8"));

/* Where the commentary comes from, in order of preference:
 *
 *   1. data/work/narrative.json    — this run's output, if step 13 just ran
 *   2. output/<period>/narrative.json — the copy archived with that month's
 *      deck, which IS committed to the repository
 *
 * The second entry is what makes the model-written commentary visible to
 * someone who clones this repo without an API key. It costs one call, once,
 * from whoever generated the month — after that the text is just a file.
 *
 * run_report.py clears (1) at the start of every run, so a narrative left
 * over from a different month can never be picked up here. */
const NARRATIVE_PATH = [
  path.join(WORK, "narrative.json"),
  path.join(OUT_DIR, "narrative.json"),
].find((p) => fs.existsSync(p));

const HAS_NARRATIVE = Boolean(NARRATIVE_PATH);
const N = HAS_NARRATIVE ? JSON.parse(fs.readFileSync(NARRATIVE_PATH, "utf8")) : {};

const C = DATA.computed;
const PERIOD = DATA.period;
const LABEL = DATA.period_label;

const OUT_DIR = path.join(ROOT, "output", PERIOD);
fs.mkdirSync(OUT_DIR, { recursive: true });
const OUT_FILE = path.join(OUT_DIR, `monthly_report_${PERIOD}.pptx`);

/* ------------------------------------------------------------------ theme */
const BG = "0B0F1F";
const CARD = "141A33";
const CARD_EDGE = "232B52";
const WHITE = "FFFFFF";
const MUTED = "8B93B8";
const BLUE = "5E8CFF";
const CYAN = "56D6D6";
const GREEN = "4ADE80";
const RED = "F2596B";

const W = 13.333;
const H = 7.5;

/* -------------------------------------------------------------- utilities */
const money = (v) => "$" + Number(v).toLocaleString("en-NZ", {
  minimumFractionDigits: 0, maximumFractionDigits: 0 });
const units = (v) => Number(v).toLocaleString("en-NZ");
const signed = (v) => (v >= 0 ? "+" : "") + Number(v).toFixed(1) + "%";
const rose = (v) => (v >= 0 ? "rose" : "fell");
const shortMonth = (label) => String(label).split(" ")[0];

/** Enum values are stored snake_case (milk_powder, fish_oil). Printing them
 *  raw put "supplement is 34.7% of revenue" and "fish oil leads" on slides. */
const label = (value) => String(value)
  .replace(/_/g, " ")
  .replace(/^./, (c) => c.toUpperCase());

/** Narrative field if present, otherwise the rule-composed fallback.
 *  Called for every piece of prose in the deck — this one function is what
 *  makes the language model optional rather than required. */
function text(field, fallback) {
  const value = N[field];
  return (typeof value === "string" && value.trim()) ? value.trim() : fallback;
}

const lastMom = (series) => (series && series.length ? series[series.length - 1] : null);

/* ---------------------------------------------------------------- chrome  */
/* Section numbers match the contents slide, so a reader who skips ahead can
   still tell which part of the report they're looking at. */
const SECTIONS = [
  ["01", "Overview", "This month's revenue, units and orders, split by tier and category"],
  ["02", "Monthly trend", "How the last four months moved, and by how much"],
  ["03", "Product structure", "Category mix, the premium range, best sellers, brands"],
  ["04", "Channels", "Local walk-in and trade versus export parcels"],
  ["05", "Concentration", "How much of revenue a handful of SKUs carries"],
  ["06", "Operating context", "Foot traffic, enquiries and this month's campaigns"],
];

function slide(pptx, title, subtitle, section) {
  const s = pptx.addSlide();
  s.background = { color: BG };

  let top = 0.28;
  if (section) {
    const meta = SECTIONS.find((x) => x[0] === section);
    s.addText(`${section}  ·  ${meta ? meta[1] : ""}`, {
      x: 0.5, y: 0.20, w: 12.3, h: 0.3,
      fontSize: 11, bold: true, color: BLUE, fontFace: "Arial", charSpacing: 1,
    });
    top = 0.58;
  }

  s.addText(title, {
    x: 0.5, y: top, w: 12.3, h: 0.5,
    fontSize: 24, bold: true, color: WHITE, fontFace: "Arial",
  });
  if (subtitle) {
    s.addText(subtitle, {
      x: 0.5, y: top + 0.5, w: 12.3, h: 0.42,
      fontSize: 13, color: MUTED, fontFace: "Arial",
    });
  }
  s.addShape(pptx.ShapeType.rect, {
    x: 0.5, y: top + 0.46, w: 1.1, h: 0.035,
    fill: { color: BLUE }, line: { width: 0 },
  });
  return s;
}

function panel(s, x, y, w, h) {
  s.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: CARD }, line: { color: CARD_EDGE, width: 1 },
  });
}

function note(s, x, y, w, h, heading, body, accent = BLUE) {
  panel(s, x, y, w, h);
  s.addText(heading, {
    x: x + 0.22, y: y + 0.16, w: w - 0.44, h: 0.3,
    fontSize: 12, bold: true, color: accent, fontFace: "Arial",
  });
  s.addText(body, {
    x: x + 0.22, y: y + 0.5, w: w - 0.44, h: h - 0.68,
    fontSize: 11.5, color: WHITE, fontFace: "Arial",
    valign: "top", lineSpacingMultiple: 1.25,
  });
}

function chart(s, file, x, y, w, h) {
  const p = path.join(WORK, file);
  if (!fs.existsSync(p)) {
    s.addText(`${file} not found — run step14 first`, {
      x, y, w, h, fontSize: 13, color: RED, align: "center", valign: "middle",
    });
    return;
  }
  s.addImage({ path: p, x, y, w, h });
}

/* =========================================================== the slides == */
const TOP = 1.55;          // where content starts on a slide with a section marker

function slideCover(pptx) {
  const s = pptx.addSlide();
  s.background = { color: BG };
  s.addText("Monthly Sales Report", {
    x: 0.9, y: 2.5, w: 11.5, h: 0.9,
    fontSize: 42, bold: true, color: WHITE, fontFace: "Arial",
  });
  s.addText(`${LABEL}  ·  ${DATA.store_code}`, {
    x: 0.9, y: 3.45, w: 11.5, h: 0.5,
    fontSize: 19, color: BLUE, fontFace: "Arial",
  });
  s.addShape(pptx.ShapeType.rect, {
    x: 0.9, y: 4.1, w: 2.0, h: 0.04, fill: { color: BLUE }, line: { width: 0 },
  });
  s.addText(
    HAS_NARRATIVE
      ? "Figures computed from the sales database. Commentary drafted by a "
        + "language model and checked against the source data."
      : "Figures computed from the sales database. Commentary composed from "
        + "the same figures (no model output in this run).",
    { x: 0.9, y: 4.35, w: 9.5, h: 0.7,
      fontSize: 11.5, color: MUTED, fontFace: "Arial", lineSpacingMultiple: 1.3 });
  return s;
}

function slideContents(pptx) {
  const s = pptx.addSlide();
  s.background = { color: BG };
  s.addText("Contents", {
    x: 0.6, y: 0.5, w: 6, h: 0.7,
    fontSize: 30, bold: true, color: WHITE, fontFace: "Arial",
  });

  const colW = 5.75, rowH = 1.55, gapX = 0.35, gapY = 0.25;
  SECTIONS.forEach(([number, title, blurb], i) => {
    const x = 0.6 + (i % 2) * (colW + gapX);
    const y = 1.55 + Math.floor(i / 2) * (rowH + gapY);
    s.addShape("roundRect", {
      x, y, w: colW, h: rowH, rectRadius: 0.06,
      fill: { color: CARD }, line: { color: CARD_EDGE, width: 1 },
    });
    s.addShape("ellipse", {
      x: x + 0.25, y: y + 0.28, w: 0.55, h: 0.55,
      fill: { color: BLUE }, line: { type: "none" },
    });
    s.addText(number, {
      x: x + 0.25, y: y + 0.28, w: 0.55, h: 0.55,
      fontSize: 13, bold: true, color: WHITE, fontFace: "Arial",
      align: "center", valign: "middle",
    });
    s.addText(title, {
      x: x + 1.0, y: y + 0.2, w: colW - 1.2, h: 0.4,
      fontSize: 15, bold: true, color: WHITE, fontFace: "Arial",
    });
    s.addText(blurb, {
      x: x + 1.0, y: y + 0.62, w: colW - 1.2, h: 0.8,
      fontSize: 11, color: MUTED, fontFace: "Arial", lineSpacingMultiple: 1.2,
    });
  });
  return s;
}

function slideHeadline(pptx) {
  const h = DATA.headline;
  const mom = lastMom(C.amount_mom_pct);
  const fallback = mom === null
    ? `${LABEL}: ${money(h.total_amount)} across ${units(h.total_orders)} orders`
    : `${LABEL} revenue ${money(h.total_amount)}, ${rose(mom)} `
      + `${Math.abs(mom).toFixed(1)}% on ${shortMonth(C.trend_labels[C.trend_labels.length - 2])}`;

  const s = slide(pptx, text("headline_title", fallback),
                  `Average order value ${money(h.avg_order_value)}`, "01");
  chart(s, "chart_headline.png", 0.42, TOP, 12.5, 5.0);
  return s;
}

function slideTrendAmount(pptx) {
  const mom = lastMom(C.amount_mom_pct);
  const fallback = mom === null
    ? "Revenue by month"
    : `Revenue ${rose(mom)} ${Math.abs(mom).toFixed(1)}% month on month`;
  const s = slide(pptx, text("trend_title", fallback),
                  `${C.trend_labels[0]} – ${C.trend_labels[C.trend_labels.length - 1]} `
                  + "· premium / milk powder / regular, stacked (NZD)", "02");
  chart(s, "chart_trend_amount.png", 2.35, TOP, 8.6, 5.2);
  return s;
}

function slideTrendQty(pptx) {
  /* Units on their own slide rather than beside revenue. When the two
     disagree — volume up, revenue flat — that's the interesting month, and
     a shared slide makes each chart too small to see it. */
  const amountMom = lastMom(C.amount_mom_pct);
  const qtyMom = lastMom(C.qty_mom_pct);
  let fallback = "Units sold by month";
  if (qtyMom !== null) {
    const together = Math.sign(qtyMom) === Math.sign(amountMom);
    fallback = `Units ${rose(qtyMom)} ${Math.abs(qtyMom).toFixed(1)}% — `
             + (together ? "moving with revenue" : "moving against revenue");
  }
  const s = slide(pptx, text("trend_qty_title", fallback),
                  "Same three groups by units, so volume can be read "
                  + "separately from value", "02");
  chart(s, "chart_trend_qty.png", 2.35, TOP, 8.6, 5.2);
  return s;
}

function slideStructureIntro(pptx) {
  const si = DATA.structure_intro;
  const fallback = `Premium is ${si.premium_pct_of_store}% of revenue and holds `
                 + `${si.premium_in_top10} of the top ${si.top_n} seller slots`;
  const s = slide(pptx, text("structure_intro_title", fallback),
                  "The range the store is putting in front of customers, "
                  + "before the detail", "03");
  chart(s, "chart_structure_intro.png", 0.42, TOP + 0.55, 12.5, 2.9);
  return s;
}

function slideCategoryMix(pptx) {
  const cats = [...DATA.category_mix.categories].sort((a, b) => b.amount_pct - a.amount_pct);
  const top = cats[0];
  const fallback = top
    ? `${label(top.category)} is ${top.amount_pct}% of revenue on ${top.qty_pct}% of units`
    : "Category mix";
  const s = slide(pptx, text("category_mix_title", fallback),
                  "Revenue share and unit share side by side — the gap between "
                  + "the two is the unit-price effect", "03");
  chart(s, "chart_category_mix.png", 0.20, TOP - 0.15, 12.95, 4.8);
  return s;
}

function slidePremiumMix(pptx) {
  const rows = [...(DATA.premium_mix.categories || [])]
    .sort((a, b) => b.amount_pct - a.amount_pct);
  const top = rows[0];
  const fallback = top
    ? `${label(top.category)} is ${top.amount_pct}% of the premium range`
    : "Premium range by category";
  const s = slide(pptx, text("premium_mix_title", fallback),
                  "Shares are within premium, not of the store — a different "
                  + "denominator from the previous slide", "03");
  chart(s, "chart_premium_mix.png", 0.42, TOP, 12.5, 5.0);
  return s;
}

function slideTopProducts(pptx) {
  const fallback = `${DATA.premium_in_top10} of the top `
                 + `${DATA.top_products.length} sellers are premium lines`;
  const s = slide(pptx, text("top_products_title", fallback),
                  "Ranked by units sold", "03");
  chart(s, "chart_top_products.png", 0.55, TOP - 0.10, 12.2, 5.1);
  return s;
}

function slideBrands(pptx) {
  const lead = DATA.top_brands[0];
  const fallback = lead
    ? `${lead.brand} leads on revenue at ${lead.pct_of_store.toFixed(1)}% of the store`
    : "Brands by revenue";
  const s = slide(pptx, text("brand_title", fallback),
                  "Percentages are share of total store revenue", "03");
  chart(s, "chart_brands.png", 0.55, TOP - 0.10, 12.2, 5.0);
  return s;
}

function slideMilkBrands(pptx) {
  const lead = DATA.milk_powder_brands[0];
  const fallback = lead
    ? `${lead.brand} leads milk powder with ${lead.pct_of_category.toFixed(1)}% of the category`
    : "Milk powder brands";
  const s = slide(pptx, text("milk_brand_title", fallback),
                  "Pickup and shipped combined · percentages are share of the "
                  + "milk powder category, not of the store", "03");
  chart(s, "chart_milk_brands.png", 0.42, TOP, 8.6, 4.9);

  const memoFallback = lead
    ? `${lead.brand} accounts for ${lead.pct_of_category.toFixed(1)}% of milk `
      + "powder revenue this month. Shares here are within the category — the "
      + "store-wide slide uses a different denominator."
    : "No milk powder sales recorded this month.";
  note(s, 9.2, TOP, 3.75, 4.9, "Notes", text("milk_brand_note", memoFallback), CYAN);
  return s;
}

function slidePickup(pptx) {
  const rows = DATA.pickup_tier_trend.filter((r) => r.period === PERIOD);
  const premium = rows.filter((r) => r.tier === "premium")
                      .reduce((a, r) => a + r.amount, 0);
  const total = rows.reduce((a, r) => a + r.amount, 0);
  const share = total ? (premium / total) * 100 : 0;

  const fallback = total
    ? `Premium is ${share.toFixed(1)}% of in-store milk powder pickups`
    : "In-store milk powder pickups";
  const s = slide(pptx, text("pickup_title", fallback),
                  "Premium marks the range the store is putting in front of "
                  + "customers — it is not a price band", "03");
  chart(s, "chart_pickup_tiers.png", 0.42, TOP, 12.5, 2.9);
  note(s, 0.42, TOP + 3.05, 12.5, 1.6, "Reading",
       text("pickup_comment",
            total
              ? `Premium lines made up ${share.toFixed(1)}% of in-store milk `
                + `powder pickups in ${LABEL}. Staff can mention the premium `
                + "range when handing over a pickup order."
              : "No in-store milk powder pickups were recorded this month."));
  return s;
}

function slideFunctional(pptx) {
  const s = slide(pptx, text("functional_title", "Functional supplement types by month"),
                  "Units sold · a read on what customers are buying "
                  + "supplements for", "03");
  chart(s, "chart_functional_types.png", 0.42, TOP, 8.0, 4.9);

  const latest = DATA.functional_trend.filter((r) => r.period === PERIOD)
                     .sort((a, b) => b.qty - a.qty);
  const fallback = latest.length
    ? `${label(latest[0].product_type)} leads on units this month at ${units(latest[0].qty)}.`
    : "No functional supplement sales recorded this month.";
  note(s, 8.65, TOP, 4.28, 4.9, "Notes", text("functional_note", fallback), CYAN);
  return s;
}

function slideChannels(pptx) {
  /* Month-on-month here is the latest step, not the largest.
     An earlier version picked the most negative month so it had something
     dramatic to show; March's deck then printed February's -40%. */
  const exportMom = lastMom(C.export_qty_mom_pct);
  const localMom = lastMom(C.local_qty_mom_pct);

  const fallback = exportMom === null
    ? "Local and export volume by month"
    : `Export ${rose(exportMom)} ${Math.abs(exportMom).toFixed(1)}%, `
      + `local ${rose(localMom)} ${Math.abs(localMom).toFixed(1)}%`;

  const s = slide(pptx, text("channel_title", fallback),
                  "Units · grouped rather than stacked, because the two "
                  + "channels move independently", "04");
  chart(s, "chart_channels.png", 0.42, TOP, 7.7, 4.9);

  const rightX = 8.35;
  [["Export", exportMom, "parcels"], ["Local", localMom, "walk-in + trade"]]
    .forEach(([name, value, sub], i) => {
      const y = TOP + i * 1.25;
      panel(s, rightX, y, 4.58, 1.1);
      s.addText(value === null ? "n/a" : signed(value), {
        x: rightX + 0.2, y: y + 0.14, w: 2.2, h: 0.5,
        fontSize: 24, bold: true, fontFace: "Arial",
        color: value === null ? MUTED : (value < 0 ? RED : GREEN),
      });
      s.addText(`${name} units\n${sub}`, {
        x: rightX + 2.5, y: y + 0.18, w: 1.9, h: 0.75,
        fontSize: 11, color: MUTED, fontFace: "Arial", align: "right",
        lineSpacingMultiple: 1.2,
      });
    });

  const exportShare = DATA.channel_trend.find(
    (r) => r.period === PERIOD && r.channel_group === "export");
  const commentFallback = exportMom === null
    ? "First month on record — no comparison available yet."
    : `Export volume ${rose(exportMom)} ${Math.abs(exportMom).toFixed(1)}% and `
      + `local ${rose(localMom)} ${Math.abs(localMom).toFixed(1)}% month on month`
      + (exportShare ? `; export is ${exportShare.qty_pct}% of units this month.` : ".");
  note(s, rightX, TOP + 2.65, 4.58, 2.25, "Reading",
       text("channel_comment", commentFallback));
  return s;
}

function slideConcentration(pptx) {
  const rows = [...DATA.sku_pareto].sort((a, b) => a.decile - b.decile);
  const top20 = rows.find((r) => r.decile === 2);
  const fallback = top20
    ? `The top 20% of SKUs account for ${top20.cumulative_pct.toFixed(0)}% of revenue`
    : "Revenue concentration by SKU";
  const s = slide(pptx, text("concentration_title", fallback),
                  "Cumulative share of revenue as SKUs are added worst-to-best", "05");
  chart(s, "chart_concentration.png", 0.55, TOP, 12.2, 4.6);
  return s;
}

function slideOperations(pptx) {
  const ctx = DATA.operating_context || {};
  const s = slide(pptx, text("operations_title", `${LABEL} operating context`),
                  "Entered by hand each month — these figures are not in the POS", "06");

  const cards = [
    [ctx.foot_traffic ? units(ctx.foot_traffic) : "—", "foot traffic", BLUE],
    [ctx.miniprogram_leads ? units(ctx.miniprogram_leads) : "—", "app enquiries", CYAN],
    [ctx.miniprogram_completion_rate ? `${ctx.miniprogram_completion_rate}%` : "—",
      "enquiry completion", GREEN],
  ];
  cards.forEach(([value, lbl, colour], i) => {
    const x = 0.42 + i * 4.25;
    panel(s, x, TOP + 0.3, 3.95, 1.7);
    s.addText(value, {
      x: x + 0.2, y: TOP + 0.48, w: 3.55, h: 0.8,
      fontSize: 32, bold: true, color: colour, fontFace: "Arial",
    });
    s.addText(lbl, {
      x: x + 0.2, y: TOP + 1.35, w: 3.55, h: 0.4,
      fontSize: 12, color: MUTED, fontFace: "Arial",
    });
  });

  const tourText = ctx.study_tour_flag === "yes"
    ? (ctx.study_tour_note || "A tour group visited this month.")
    : "No tour groups this month.";
  note(s, 0.42, TOP + 2.35, 12.5, 1.5, "Tour groups", tourText, CYAN);
  return s;
}

function slideCampaigns(pptx) {
  /* Campaigns get their own slide because this is where the model's only
     genuinely generative output lands — turning a free-text note the manager
     typed into readable lines. Without a model it falls back to the raw note,
     which is still true, just unformatted. */
  const ctx = DATA.operating_context || {};
  const desc = ctx.activity_description || "";
  const s = slide(pptx, text("campaign_title", "Campaigns running this month"),
                  "Taken from the note entered in monthly_context.csv", "06");

  const bulletFallback = desc
    ? desc.split(/[;,]/).map((x) => x.trim()).filter(Boolean)
        .map((x) => `· ${x}`).join("\n")
    : "No campaigns recorded for this month.";

  // One card, not two. An earlier version also showed the raw note underneath
  // "for traceability", which in practice meant the reader saw the same
  // sentence twice — once tidied and once not. The tidied version either says
  // what the note said or it's wrong, and printing both doesn't help anyone
  // tell which.
  note(s, 0.42, TOP, 12.5, 4.3, "Key points",
       text("campaign_bullets", bulletFallback));
  return s;
}

function slideEnd(pptx) {
  const s = pptx.addSlide();
  s.background = { color: BG };
  s.addText("Questions on any figure trace back to source", {
    x: 0.7, y: 2.9, w: 11.7, h: 0.8,
    fontSize: 28, bold: true, color: WHITE, fontFace: "Arial",
  });
  s.addText(`${DATA.store_code}  ·  ${LABEL}`, {
    x: 0.7, y: 3.7, w: 11, h: 0.5,
    fontSize: 15, color: BLUE, fontFace: "Arial",
  });
  s.addText(`Generated ${new Date().toISOString().slice(0, 10)} from `
            + "report_data.json — every number on every slide comes from that "
            + "one file.",
    { x: 0.7, y: 4.15, w: 11, h: 0.5,
      fontSize: 11.5, color: MUTED, fontFace: "Arial" });
  return s;
}

/* ================================================================== main = */
function main() {
  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: "WIDE", width: W, height: H });
  pptx.layout = "WIDE";
  pptx.author = "retail-report-pipeline";
  pptx.title = `Monthly Sales Report ${LABEL}`;

  [slideCover, slideContents,
   slideHeadline,
   slideTrendAmount, slideTrendQty,
   slideStructureIntro, slideCategoryMix, slidePremiumMix, slideTopProducts,
   slideBrands, slideMilkBrands, slidePickup, slideFunctional,
   slideChannels,
   slideConcentration,
   slideOperations, slideCampaigns,
   slideEnd].forEach((build) => build(pptx));

  return pptx.writeFile({ fileName: OUT_FILE }).then(() => {
    console.log(`\n${path.relative(ROOT, OUT_FILE)}`);
    console.log(HAS_NARRATIVE
      ? "  commentary: model-drafted, checked against source"
      : "  commentary: rule-composed (no narrative.json in this run)");
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

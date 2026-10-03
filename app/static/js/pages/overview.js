import { api } from "../api.js";
import { C, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { delta, fill, h, iconSvg, skeleton, statTile } from "../dom.js";
import { dateLabel, flatTypeLabel, int, isNum, money, moneyShort, monthLabel, pct, titleCase } from "../format.js";
import { countUp, cycleWords, reveal, splitWords, whenVisible } from "../motion.js";
import { chipGroup } from "../picker.js";
import { state, update } from "../state.js";
import { createTownMap, loadMap, loadTownStats, mapCaption } from "../townmap.js";

export async function render(root, { meta }) {
  const q = meta.quality;

  // ---------------------------------------------------------------- hero
  const line1 = h("span", {}, "Know the market.");
  const line2 = h("span", { class: "soft" }, "Know what you can afford.");
  const title = h("h1", { class: "display" }, line1, h("br"), line2);
  const hero = h("div", { class: "wrap hero__inner" });
  root.append(h("section", { class: "hero" }, hero));
  hero.append(
    h(
      "div",
      {},
      h("p", { class: "eyebrow" }, "HDB resale prices, explained"),
      title,
      reveal(
        h("p", { class: "lede" }, "See prices in every town, work out what you can afford, and check if an asking price makes sense. All from official HDB data."),
        350,
      ),
      reveal(
        h(
          "div",
          { class: "hero__actions" },
          h("a", { class: "btn btn--primary", href: "#/market" }, "Explore the market"),
          h("a", { class: "btn btn--secondary", href: "#/value" }, "Check a flat’s price"),
        ),
        450,
      ),
      reveal(
        h(
          "div",
          { class: "provenance" },
          iconSvg("shield"),
          h("span", {}, h("b", {}, int(q.valid_rows)), " resale records"),
          h("i", { class: "sep" }),
          h("span", {}, `${monthLabel(q.earliest_month)} to ${monthLabel(meta.last_complete_month)}`),
          h("i", { class: "sep" }),
          h("span", {}, "HDB data from data.gov.sg"),
        ),
        550,
      ),
    ),
  );
  splitWords(line1);
  // The second line names the three questions the app answers, then settles on the tagline.
  const stopCycle = cycleWords(line2, ["Know what comes next.", "Know what a flat is worth.", "Know what you can afford."]);
  window.addEventListener("hashchange", stopCycle, { once: true });

  // ---------------------------------------------------------------- KPIs
  const kpiRow = h("div", { class: "grid grid--4" }, [0, 1, 2, 3].map(() => skeleton(124)));
  root.append(h("section", { class: "wrap section hero-kpis" }, kpiRow));

  // ---------------------------------------------------------------- map
  const mapSlot = h("div", {}, skeleton(420));
  root.append(
    h(
      "div",
      { class: "band band--teal" },
      h(
        "section",
        { class: "wrap section" },
        h("div", { class: "section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Prices by town"), h("h2", { class: "h2" }, "Tap a town to see its prices"))),
        mapSlot,
      ),
    ),
  );

  // ---------------------------------------------------------------- trend
  let trendRows = [];
  const trend = chartCard({
    title: "Resale prices since 2017",
    sub: "Median price of all flats sold each month. The bold line averages three months.",
    legend: [
      { label: "3-month median", color: C.s1 },
      { label: "Monthly median", color: "#b8b8bf" },
      { label: "Oct 2024: new flat classification starts", color: C.faint },
    ],
    height: 360,
    zoom: true,
    tableView: () =>
      tableView(
        [
          { key: "month", label: "Month", format: monthLabel },
          { key: "median_price_3m", label: "3-month median", align: "right", format: money },
          { key: "median_price", label: "Monthly median", align: "right", format: money },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        [...trendRows].reverse(),
      ),
  });
  root.append(h("section", { class: "wrap section" }, reveal(trend.el)));

  const lists = h("div", { class: "grid grid--2" }, skeleton(360), skeleton(360));
  const movers = h("div", { class: "grid grid--2" }, skeleton(220), skeleton(220));
  root.append(h("section", { class: "wrap section" }, lists), h("section", { class: "wrap section--tight" }, movers));
  root.append(journey(), howItWorks(meta), trustRow(meta));

  // ---------------------------------------------------------------- data
  const [data, map] = await Promise.all([api("overview"), loadMap()]);
  const k = data.kpis;

  const tile = (label, valueEl, metaParts) => statTile({ label, value: valueEl, meta: metaParts });
  fill(
    kpiRow,
    tile("Median resale price", countUp(h("span", {}), k.median_price, (v) => money(Math.round(v / 1000) * 1000)), [`All flats, ${k.window_label}`]),
    tile("Change from a year ago", countUp(h("span", {}), k.yoy_pct, (v) => pct(v)), [`It was ${money(k.median_price_year_ago)}`]),
    tile(`Flats sold, ${k.ytd_label}`, countUp(h("span", {}), k.transactions_ytd, (v) => int(Math.round(v))), [delta(k.transactions_ytd_change_pct), "vs the same months last year"]),
    tile("Last updated", h("span", {}, dateLabel(meta.quality.source_last_updated)), [`Full months up to ${monthLabel(meta.last_complete_month)}`]),
  );

  drawMapSection(mapSlot, meta, map);

  trendRows = data.trend;
  const months = data.trend.map((d) => d.month);
  const smooth = data.trend.map((d) => d.median_price_3m);
  const monthly = data.trend.map((d) => d.median_price);
  whenVisible(trend.el, () =>
    mount(
      trend.chartEl,
      lineOption({
        months,
        series: [
          { name: "Monthly median", values: monthly, color: "#c4c4cb", width: 1.5 },
          { name: "3-month median", values: smooth, color: C.s1, endDot: true },
        ],
        markers: meta.policy_events.map((e) => ({ month: e.month, label: "Oct 2024" })),
        tooltip: (i) =>
          tooltipHtml(monthLabel(months[i]), [
            { color: C.s1, value: money(smooth[i]), label: "3-month median" },
            { color: "#c4c4cb", value: money(monthly[i]), label: "monthly median" },
            { value: int(data.trend[i].transactions), label: "sales this month" },
          ]),
      }),
    ),
  );

  const ref = flatTypeLabel(data.reference_flat_type, true);
  const maxPrice = Math.max(...data.most_expensive.map((t) => t.median_price_12m));
  fill(
    lists,
    reveal(rankCard("Most expensive towns", `${ref}, last 12 months`, data.most_expensive, maxPrice)),
    reveal(rankCard("Most affordable towns", `${ref}, last 12 months`, data.most_affordable, maxPrice), 80),
  );
  fill(
    movers,
    reveal(moverCard("Rising fastest", data.rising, `${ref}, compared with the year before. Towns with ${data.min_sales_for_movers}+ sales.`)),
    reveal(moverCard("Cooling off", data.falling, "Same comparison. A drop can also mean smaller or older flats were sold."), 80),
  );
}

// -------------------------------------------------------------------- map
async function drawMapSection(slot, meta, map) {
  let flatType = meta.common_flat_types.includes(state.flatType) ? state.flatType : "4 ROOM";
  let selected = meta.towns.includes(state.town) ? state.town : "TAMPINES";
  let stats = await loadTownStats(flatType);

  const panel = h("div", { class: "mappanel" });
  const caption = h("p", { class: "small", style: { marginTop: "10px" } });
  const townMap = map.available
    ? createTownMap({
        map,
        onSelect: (town) => {
          selected = town;
          update({ town });
          redraw();
        },
      })
    : null;

  function drawPanel() {
    const row = stats.towns.find((t) => t.town === selected);
    const hasPrice = row && isNum(row.median_price_12m);
    fill(
      panel,
      h("p", { class: "eyebrow" }, flatTypeLabel(flatType, true)),
      h("h3", { class: "mappanel__name" }, titleCase(selected)),
      h("div", { class: "mappanel__price" }, hasPrice ? money(row.median_price_12m) : "Too few sales"),
      h("p", { class: "sub" }, hasPrice ? `Median price, ${stats.window_label}` : `Fewer than ${stats.min_sales} sold in the last 12 months.`),
      hasPrice
        ? h(
            "ul",
            { class: "breakdown mt-16" },
            h("li", {}, h("span", {}, "From a year ago"), h("b", {}, pct(row.yoy_pct))),
            h("li", {}, h("span", {}, "Over five years"), h("b", {}, pct(row.change_5y_pct))),
            h("li", {}, h("span", {}, "Flats sold"), h("b", {}, int(row.transactions_12m))),
            isNum(row.train_minutes) ? h("li", {}, h("span", {}, "Typical walk to a station"), h("b", {}, `${row.train_minutes} min`)) : null,
          )
        : null,
      h(
        "div",
        { class: "mappanel__actions" },
        h("a", { class: "btn btn--primary", href: "#/market", onclick: () => update({ town: selected, flatType }) }, `See ${titleCase(selected)}`),
        h("a", { class: "btn btn--secondary", href: "#/value", onclick: () => update({ town: selected, flatType }) }, "Check a flat here"),
      ),
    );
  }

  function redraw() {
    townMap?.update({ stats, selected: [selected] });
    caption.textContent = map.available ? mapCaption(stats, flatType) : "";
    drawPanel();
  }

  const chips = chipGroup({
    label: "Flat type",
    options: meta.common_flat_types.map((t) => [t, flatTypeLabel(t)]),
    value: flatType,
    onChange: async (value) => {
      flatType = value;
      update({ flatType });
      stats = await loadTownStats(flatType);
      redraw();
    },
  });

  const card = h(
    "article",
    { class: "card card--pad-lg" },
    h("div", { style: { marginBottom: "18px" } }, chips),
    townMap
      ? h("div", { class: "mapcard" }, h("div", {}, townMap.el, caption), panel)
      : h("div", {}, h("p", { class: "sub" }, "The map isn’t available in this build. Pick a town on the Market page instead."), panel),
  );
  fill(slot, reveal(card));
  redraw();
}

// -------------------------------------------------------------------- lists
function goTown(town) {
  update({ town, flatType: "4 ROOM" });
  location.hash = "#/market";
}

function rankCard(title, sub, rows, max) {
  return h(
    "article",
    { class: "card" },
    h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, title), h("p", { class: "sub" }, sub))),
    h(
      "ol",
      { class: "rank-list" },
      rows.map((row, i) =>
        h(
          "li",
          {},
          h("span", { class: "rank-list__n" }, i + 1),
          h(
            "div",
            {},
            h("button", { class: "rank-list__name", type: "button", onclick: () => goTown(row.town) }, titleCase(row.town)),
            h("div", { class: "rank-list__bar" }, h("i", { style: { width: `${(row.median_price_12m / max) * 100}%` } })),
          ),
          h("span", { class: "rank-list__val" }, money(row.median_price_12m), h("small", {}, `${int(row.transactions_12m)} sold`)),
        ),
      ),
    ),
  );
}

function moverCard(title, rows, sub) {
  return h(
    "article",
    { class: "card" },
    h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, title), h("p", { class: "sub" }, sub))),
    h(
      "ol",
      { class: "rank-list" },
      rows.map((row, i) =>
        h(
          "li",
          {},
          h("span", { class: "rank-list__n" }, i + 1),
          h("button", { class: "rank-list__name", type: "button", onclick: () => goTown(row.town) }, titleCase(row.town)),
          h("span", { class: "rank-list__val" }, delta(row.yoy_pct), h("small", {}, moneyShort(row.median_price_12m))),
        ),
      ),
    ),
  );
}

// -------------------------------------------------------------------- journey
function journey() {
  const steps = [
    ["#/market", "Market", "Prices and trends for any town"],
    ["#/forecast", "Forecast", "Where prices may go in six months"],
    ["#/afford", "Affordability", "What you can pay each month"],
    ["#/value", "Fair value", "Check an asking price against similar sales"],
    ["#/compare", "Compare", "Put up to three towns side by side"],
  ];
  const list = h(
    "div",
    { class: "journey" },
    steps.map(([href, title, text], i) => h("a", { href, style: { "--i": i } }, h("span", { class: "journey__n" }, i + 1), h("b", {}, title), h("span", {}, text))),
  );
  whenVisible(list);
  return h(
    "div",
    { class: "band" },
    h(
      "section",
      { class: "wrap section" },
      h("div", { class: "section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "How to use it"), h("h2", { class: "h2" }, "Five steps to a decision"))),
      list,
    ),
  );
}

// -------------------------------------------------------------------- how it works
function howItWorks(meta) {
  const q = meta.quality;
  const acc = meta.fair_value_accuracy;
  const steps = [
    ["Official data", int(q.total_rows), "resale records from HDB, pulled from data.gov.sg."],
    ["Checked", `${q.checks_total} checks`, "run on every record. Odd ones are flagged and kept."],
    meta.has_location
      ? ["Placed on the map", `${int(meta.location.blocks)} blocks`, "each with its walk to trains, schools, shops and parks."]
      : ["Summarised", `${meta.towns.length} towns`, "with prices, sales and trends for each flat type."],
    ["Modelled", `${acc.median_ape.toFixed(1)}% off`, `is the price model’s typical miss on ${int(acc.n)} sales it had never seen.`],
    ["Your answer", "5 steps", "from the market to one flat’s price."],
  ];
  const flow = h(
    "ol",
    { class: "flow" },
    steps.map(([title, number, text], i) =>
      h("li", { class: "flow__step", style: { "--i": i } }, h("span", { class: "flow__dot", "aria-hidden": "true" }), h("b", {}, title), h("span", { class: "flow__num" }, number), h("p", {}, text)),
    ),
  );
  whenVisible(flow);
  return h(
    "section",
    { class: "wrap section" },
    h(
      "article",
      { class: "card card--pad-lg" },
      h("p", { class: "eyebrow" }, "How it works"),
      h("h2", { class: "h2", style: { marginBottom: "28px" } }, "From public data to your answer"),
      flow,
      h("div", { class: "card__foot" }, "The pipeline runs on Databricks: Delta tables, Unity Catalog and MLflow."),
    ),
  );
}

function trustRow(meta) {
  const acc = meta.fair_value_accuracy;
  const items = [
    ["Open data only", "Prices are HDB resale records from data.gov.sg. Income is from SingStat. Nearby places are from LTA, MOE, NEA and NParks, and malls from OpenStreetMap."],
    ["Tested first", `The forecast was checked from ${meta.forecast_origins} past starting points (${meta.forecast_mape.toFixed(1)}% average error). The price model was tested on ${int(acc.n)} recent sales.`],
    ["Know the limits", "Every estimate comes with a range. The model can’t see renovation or views. This is not financial advice."],
  ];
  return h(
    "section",
    { class: "wrap section" },
    h(
      "div",
      { class: "grid grid--3" },
      items.map(([title, text], i) => reveal(h("article", { class: "card card--flat" }, h("h3", { class: "h3" }, title), h("p", { class: "sub", style: { marginTop: "8px" } }, text)), i * 80)),
    ),
  );
}

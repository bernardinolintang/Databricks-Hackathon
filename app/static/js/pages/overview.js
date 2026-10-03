import { api } from "../api.js";
import { C, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { clear, fill, delta, h, iconSvg, skeleton, statTile } from "../dom.js";
import { dateTime, flatTypeLabel, int, money, moneyShort, monthLabel, pct, titleCase } from "../format.js";
import { update } from "../state.js";

export async function render(root, { meta }) {
  const q = meta.quality;
  root.append(
    h(
      "section",
      { class: "wrap hero" },
      h("p", { class: "eyebrow" }, "HDB resale intelligence"),
      h("h1", { class: "display" }, "Know the market.", h("br"), h("span", { class: "soft" }, "Know what you can afford.")),
      h(
        "p",
        { class: "lede" },
        "Explore historical prices, see where they may head next, check affordability and estimate a flat’s fair value, all from Singapore’s official open housing data.",
      ),
      h(
        "div",
        { class: "hero__actions" },
        h("a", { class: "btn btn--primary", href: "#/market" }, "Explore the market"),
        h("a", { class: "btn btn--secondary", href: "#/value" }, "Estimate a flat’s value"),
      ),
      h(
        "div",
        { class: "provenance" },
        iconSvg("shield"),
        h("span", {}, h("b", {}, int(q.valid_rows)), " official resale transactions"),
        h("i", { class: "sep" }),
        h("span", {}, `${monthLabel(q.earliest_month)} to ${monthLabel(meta.last_complete_month)}`),
        h("i", { class: "sep" }),
        h("span", {}, "HDB via data.gov.sg"),
      ),
    ),
  );

  const kpiRow = h("div", { class: "grid grid--4" }, [0, 1, 2, 3].map(() => skeleton(124)));
  root.append(h("section", { class: "wrap section" }, kpiRow));

  const trend = chartCard({
    title: "Singapore resale prices since 2017",
    sub: "Median price across all flat types. The bold line pools three months of sales to smooth out noise.",
    legend: [
      { label: "3-month median", color: C.s1 },
      { label: "Monthly median", color: "#b8b8bf" },
      { label: "Oct 2024: Standard / Plus / Prime framework begins", color: C.faint, kind: "line" },
    ],
    height: 360,
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
  let trendRows = [];
  root.append(h("section", { class: "wrap section" }, trend.el));

  const lists = h("div", { class: "grid grid--2" }, skeleton(360), skeleton(360));
  const movers = h("div", { class: "grid grid--2" }, skeleton(220), skeleton(220));
  root.append(h("section", { class: "wrap section" }, lists), h("section", { class: "wrap section--tight" }, movers));

  root.append(journey(), trustRow(meta));

  const data = await api("overview");
  const k = data.kpis;
  fill(kpiRow, 
    statTile({ label: "Market median", value: money(k.median_price), meta: [`All flats, ${k.window_label}`] }),
    statTile({
      label: "Year on year",
      value: pct(k.yoy_pct),
      meta: [`Same months last year: ${money(k.median_price_year_ago)}`],
    }),
    statTile({
      label: `Resale transactions, ${k.ytd_label.replace("Jan – ", "Jan–")}`,
      value: int(k.transactions_ytd),
      meta: [delta(k.transactions_ytd_change_pct), "vs same period last year"],
    }),
    statTile({
      label: "Latest complete month",
      value: monthLabel(meta.last_complete_month),
      meta: [`Updated ${dateTime(meta.quality.source_last_updated).split(",")[0]}`],
    }),
  );

  trendRows = data.trend;
  const months = data.trend.map((d) => d.month);
  const smooth = data.trend.map((d) => d.median_price_3m);
  const monthly = data.trend.map((d) => d.median_price);
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
  );

  const ref = flatTypeLabel(data.reference_flat_type, true);
  const maxPrice = Math.max(...data.most_expensive.map((t) => t.median_price_12m));
  fill(lists, 
    rankCard("Highest-priced towns", `${ref}, median of the last 12 months`, data.most_expensive, maxPrice),
    rankCard("Most accessible towns", `${ref}, median of the last 12 months`, data.most_affordable, maxPrice),
  );
  fill(movers, 
    moverCard("Rising fastest", data.rising, `${ref}, last 12 months vs the 12 before. Towns with ${data.min_sales_for_movers}+ sales.`),
    moverCard("Cooling", data.falling, `${ref}, same comparison. A fall in a town median can reflect which flats sold, not only prices.`),
  );
}

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
          h("span", { class: "rank-list__val" }, money(row.median_price_12m), h("small", {}, `${int(row.transactions_12m)} sales`)),
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

function journey() {
  const steps = [
    ["#/market", "Market", "Prices and momentum by town and flat type"],
    ["#/forecast", "Forecast", "A six-month outlook with an honest range"],
    ["#/afford", "Affordability", "What your household can carry each month"],
    ["#/value", "Fair value", "Is an asking price in line with similar sales?"],
    ["#/compare", "Compare", "Weigh up to three towns side by side"],
  ];
  return h(
    "section",
    { class: "wrap section" },
    h("div", { class: "section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Plan a purchase"), h("h2", { class: "h2" }, "Five steps from browsing to a decision"))),
    h(
      "div",
      { class: "journey" },
      steps.map(([href, title, text], i) => h("a", { href }, h("span", { class: "journey__n" }, i + 1), h("b", {}, title), h("span", {}, text))),
    ),
  );
}

function trustRow(meta) {
  const acc = meta.fair_value_accuracy;
  const items = [
    ["Official data only", `Every figure traces back to HDB’s resale records on data.gov.sg and SingStat’s household income statistics. Nothing is scraped or invented.`],
    [
      "Tested, not assumed",
      `Forecasts were backtested from ${meta.forecast_origins} past starting points (${meta.forecast_mape.toFixed(1)}% average error). The fair value model was scored on ${int(acc.n)} recent sales it never saw: half landed within ${acc.median_ape.toFixed(1)}% of the estimate.`,
    ],
    ["Clear about limits", "Ranges instead of single numbers, assumptions you can change, and no financial advice. A model cannot see renovation, views or how a negotiation goes."],
  ];
  return h(
    "section",
    { class: "wrap section" },
    h("div", { class: "grid grid--3" }, items.map(([title, text]) => h("article", { class: "card card--flat" }, h("h3", { class: "h3" }, title), h("p", { class: "sub", style: { marginTop: "8px" } }, text)))),
  );
}

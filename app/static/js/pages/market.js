import { api } from "../api.js";
import { C, chartCard, columnsOption, histogramOption, lineOption, mount, rankedBarsOption, tooltipHtml, tableView } from "../charts.js";
import { callout, clear, fill, delta, errorBanner, h, nextStep, select, skeleton, statTile } from "../dom.js";
import { flatTypeLabel, int, money, moneyShort, monthLabel, pct, storeyLabel, titleCase, townLabel } from "../format.js";
import { state, update } from "../state.js";

export async function render(root, { meta }) {
  const filters = {
    town: state.town || "ALL",
    flat_type: state.flatType || "ALL",
    storey: "ALL",
    flat_model: "ALL",
    year_from: meta.years[0],
    year_to: meta.years[meta.years.length - 1],
  };

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 1 · Market"),
      h("h1", { class: "page-title" }, "What is happening in the market?"),
      h("p", { class: "lede" }, "Filter by town, flat type, storey and year. Every number on this page updates to the same slice of sales."),
    ),
  );

  const filterBar = h("div", { class: "filters" }, h("div", { class: "wrap" }, h("div", { class: "filters__row" })));
  const row = filterBar.querySelector(".filters__row");
  root.append(filterBar);

  const body = h("div", { class: "fade-on-load" });
  root.append(body);

  const kpiRow = h("div", { class: "grid grid--4" }, [0, 1, 2, 3].map(() => skeleton(124)));
  const headline = h("div");
  body.append(h("section", { class: "wrap section--tight" }, headline), h("section", { class: "wrap section" }, kpiRow));

  let last = null;
  const priceCard = chartCard({
    title: "Median resale price",
    sub: "Monthly median, with the middle half of sales shaded. Months with fewer than five sales are left blank.",
    legend: [
      { label: "Median price", color: C.s1 },
      { label: "Middle 50% of sales", color: C.s1Band, kind: "area" },
      { label: "Oct 2024 policy marker", color: C.faint },
    ],
    height: 380,
    tableView: () =>
      tableView(
        [
          { key: "month", label: "Month", format: monthLabel },
          { key: "median_price", label: "Median", align: "right", format: money },
          { key: "p25_price", label: "25th pct", align: "right", format: money },
          { key: "p75_price", label: "75th pct", align: "right", format: money },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        [...(last?.series || [])].reverse(),
      ),
  });
  const volumeCard = chartCard({
    title: "Sales volume",
    sub: "Resale transactions registered each month.",
    height: 240,
    tableView: () =>
      tableView(
        [
          { key: "month", label: "Month", format: monthLabel },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        [...(last?.series || [])].reverse(),
      ),
  });
  const distCard = chartCard({
    title: "Where prices sit",
    sub: "Spread of prices over the last 12 months.",
    height: 240,
    tableView: () =>
      tableView(
        [
          { key: "from", label: "From", format: money },
          { key: "to", label: "To", format: money },
          { key: "count", label: "Sales", align: "right", format: int },
        ],
        last?.distribution || [],
      ),
  });
  const rankCard = chartCard({
    title: "Price per square metre by town",
    sub: "Median over the last 12 months. Comparing per square metre removes the effect of flat size.",
    height: 560,
    tableView: () =>
      tableView(
        [
          { key: "town", label: "Town", format: titleCase },
          { key: "median_psm", label: "$/sqm", align: "right", format: money },
          { key: "median_price", label: "Median price", align: "right", format: money },
          { key: "yoy_pct", label: "Year on year", align: "right", format: (v) => pct(v) },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        last?.town_ranking || [],
        { selectedKey: last?.filters.town, keyOf: (r) => r.town },
      ),
  });
  const policySlot = h("div");

  body.append(
    h("section", { class: "wrap section" }, priceCard.el),
    h("section", { class: "wrap section--tight" }, h("div", { class: "grid grid--2" }, volumeCard.el, distCard.el)),
    h("section", { class: "wrap section" }, h("div", { class: "grid grid--wide-left" }, rankCard.el, policySlot)),
  );

  const nextSlot = h("div");
  root.append(nextSlot);

  const years = meta.years.map((y) => [y, String(y)]);
  const towns = [["ALL", "All towns"], ...meta.towns.map((t) => [t, titleCase(t)])];
  const types = [["ALL", "All flat types"], ...meta.flat_types.map((t) => [t, flatTypeLabel(t)])];
  const storeys = [["ALL", "Any storey"], ...meta.storey_ranges.map((s) => [s, `Storey ${storeyLabel(s)}`])];

  const modelOptions = () => {
    const list = filters.flat_type === "ALL" ? [...new Set(Object.values(meta.flat_models).flat())].sort() : meta.flat_models[filters.flat_type] || [];
    return [["ALL", "Any model"], ...list.map((m) => [m, titleCase(m)])];
  };

  function drawFilters() {
    fill(row, 
      select({ id: "f-town", label: "Town", options: towns, value: filters.town, onChange: (v) => set({ town: v }), grow: true }),
      select({ id: "f-type", label: "Flat type", options: types, value: filters.flat_type, onChange: (v) => set({ flat_type: v, flat_model: "ALL" }), grow: true }),
      select({ id: "f-storey", label: "Storey", options: storeys, value: filters.storey, onChange: (v) => set({ storey: v }), grow: true }),
      select({ id: "f-model", label: "Flat model", options: modelOptions(), value: filters.flat_model, onChange: (v) => set({ flat_model: v }), grow: true }),
      select({ id: "f-from", label: "From", options: years, value: filters.year_from, onChange: (v) => set({ year_from: Number(v) }) }),
      select({ id: "f-to", label: "To", options: years, value: filters.year_to, onChange: (v) => set({ year_to: Number(v) }) }),
    );
  }

  function set(patch) {
    Object.assign(filters, patch);
    if (filters.year_from > filters.year_to) [filters.year_from, filters.year_to] = [filters.year_to, filters.year_from];
    if (patch.town !== undefined) update({ town: filters.town === "ALL" ? state.town : filters.town });
    if (patch.flat_type !== undefined && filters.flat_type !== "ALL") update({ flatType: filters.flat_type });
    drawFilters();
    load();
  }

  let token = 0;
  async function load() {
    const mine = ++token;
    body.classList.add("is-loading");
    try {
      const data = await api("market", filters);
      if (mine !== token) return;
      last = data;
      draw(data);
    } catch (error) {
      if (mine !== token) return;
      fill(headline, errorBanner(error.message));
    } finally {
      if (mine === token) body.classList.remove("is-loading");
    }
  }

  function draw(data) {
    const f = data.filters;
    const place = townLabel(f.town);
    const what = flatTypeLabel(f.flat_type, true);
    const k = data.kpis;

    const momentumText =
      k.momentum_pct == null
        ? "Not enough recent sales to judge momentum."
        : Math.abs(k.momentum_pct) < 1
          ? "Prices over the last three months are roughly level with the three months before."
          : k.momentum_pct > 0
            ? `Prices over the last three months are ${pct(k.momentum_pct)} above the three months before, so momentum is upward.`
            : `Prices over the last three months are ${pct(k.momentum_pct)} below the three months before, so momentum is cooling.`;
    fill(headline, 
      h("p", { class: "insight" }, `${place}, ${what}: median ${money(k.median_price)}, ${k.yoy_pct == null ? "no year-on-year comparison" : `${pct(k.yoy_pct)} on a year ago`}.`),
      h("p", { class: "insight-sub" }, momentumText, ` Based on ${int(k.transactions_3m)} sales in ${k.window_label}.`),
    );

    fill(kpiRow, 
      statTile({ label: "Median price", value: money(k.median_price), meta: [k.window_label] }),
      statTile({ label: "Year on year", value: pct(k.yoy_pct), meta: [`A year earlier: ${money(k.median_price_year_ago)}`] }),
      statTile({ label: "Sales, last 12 months", value: int(k.transactions_12m), meta: [delta(k.transactions_12m_change_pct), "vs the 12 before"] }),
      statTile({ label: "Median price per sqm", value: money(k.median_psm), meta: [k.window_label] }),
    );

    const s = data.series;
    const months = s.map((d) => d.month);
    const median = s.map((d) => d.median_price);
    const p25 = s.map((d) => d.p25_price);
    const p75 = s.map((d) => d.p75_price);
    const markers = meta.policy_events.filter((e) => months.includes(e.month)).map((e) => ({ month: e.month, label: "Oct 2024" }));
    mount(
      priceCard.chartEl,
      lineOption({
        months,
        series: [{ name: "Median price", values: median, color: C.s1, endDot: true, connectNulls: false }],
        band: { lower: p25, upper: p75, color: C.s1Band },
        markers,
        tooltip: (i) =>
          tooltipHtml(monthLabel(months[i]), [
            { color: C.s1, value: money(median[i]), label: "median" },
            { color: C.s1Band, value: p25[i] == null ? null : `${moneyShort(p25[i])} – ${moneyShort(p75[i])}`, label: "middle 50%" },
            { value: int(s[i].transactions), label: "sales" },
          ]),
      }),
    );
    mount(
      volumeCard.chartEl,
      columnsOption({
        months,
        values: s.map((d) => d.transactions),
        tooltip: (i) => tooltipHtml(monthLabel(months[i]), [{ color: C.s1, value: int(s[i].transactions), label: "sales" }]),
      }),
    );
    const dist = data.distribution;
    mount(
      distCard.chartEl,
      histogramOption({
        labels: dist.map((b) => moneyShort(b.from)),
        values: dist.map((b) => b.count),
        tooltip: (i) => tooltipHtml(`${money(dist[i].from)} – ${money(dist[i].to)}`, [{ color: C.s1, value: int(dist[i].count), label: "sales" }]),
      }),
    );
    distCard.el.querySelector(".sub").textContent = `Spread of ${what} prices in ${place}, ${data.distribution_label}.`;

    const ranking = data.town_ranking;
    mount(
      rankCard.chartEl,
      rankedBarsOption({
        names: ranking.map((r) => titleCase(r.town)),
        values: ranking.map((r) => Math.round(r.median_psm)),
        emphasise: f.town === "ALL" ? null : (i) => ranking[i].town === f.town,
        format: (v) => `$${int(v)}`,
        tooltip: (i) =>
          tooltipHtml(titleCase(ranking[i].town), [
            { color: C.s1, value: `${money(ranking[i].median_psm)}/sqm`, label: "median" },
            { value: money(ranking[i].median_price), label: "median price" },
            { value: pct(ranking[i].yoy_pct), label: "year on year" },
            { value: int(ranking[i].transactions), label: "sales" },
          ]),
      }),
    );
    rankCard.chartEl.style.height = `${Math.max(240, ranking.length * 22 + 20)}px`;
    rankCard.el.querySelector(".sub").textContent = `${flatTypeLabel(f.flat_type, true)}, median over the last 12 months. Per square metre removes the effect of flat size.`;
    [priceCard, volumeCard, distCard, rankCard].forEach((c) => c.refreshTable());

    fill(policySlot, policyCard(data, place, what));

    clear(nextSlot);
    if (f.town !== "ALL" && f.flat_type !== "ALL") {
      nextSlot.append(
        nextStep({
          title: `Where could ${place} ${what} go next?`,
          body: "See the six-month outlook, how it was tested, and how wide the range is.",
          href: "#/forecast",
          cta: "Open the forecast",
        }),
      );
    } else {
      nextSlot.append(
        nextStep({
          title: "Pick a town and flat type",
          body: "Choose one above to carry it into the forecast, affordability and fair value steps.",
          href: "#/forecast",
          cta: "Go to the forecast",
        }),
      );
    }
  }

  drawFilters();
  await load();
}

function policyCard(data, place, what) {
  const p = data.policy;
  if (!p) {
    return h(
      "article",
      { class: "card" },
      h("h3", { class: "h3" }, "October 2024 classification change"),
      h("p", { class: "sub" }, "Not enough sales in this slice on both sides of October 2024 to compare."),
    );
  }
  return h(
    "article",
    { class: "card" },
    h("p", { class: "eyebrow" }, "Policy context"),
    h("h3", { class: "h3" }, "Before and after October 2024"),
    h("p", { class: "sub" }, `${place}, ${what}. The first BTO exercise under the Standard, Plus and Prime framework took place in October 2024.`),
    h(
      "ul",
      { class: "breakdown mt-16" },
      h("li", {}, h("span", {}, "12 months before"), h("b", {}, money(p.before.median_price))),
      h("li", {}, h("span", {}, "Change on the year before that"), h("b", {}, pct(p.before.growth_pct))),
      h("li", {}, h("span", {}, "12 months after"), h("b", {}, money(p.after.median_price))),
      h("li", { class: "total" }, h("span", {}, "Change across the marker"), h("b", {}, pct(p.after.growth_pct))),
    ),
    h("div", { class: "mt-16" }, callout("Resale records do not say whether a flat is Standard, Plus or Prime, and the framework applies to new BTO flats. Treat any shift here as an association, not an effect of the policy.")),
  );
}

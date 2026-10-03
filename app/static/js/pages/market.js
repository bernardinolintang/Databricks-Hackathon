import { api } from "../api.js";
import { C, chartCard, columnsOption, histogramOption, lineOption, mount, rankedBarsOption, tooltipHtml, tableView } from "../charts.js";
import { callout, delta, errorBanner, fill, h, nextStep, select, skeleton, statTile } from "../dom.js";
import { flatTypeLabel, int, money, moneyRange, moneyShort, monthLabel, pct, storeyLabel, titleCase, townLabel } from "../format.js";
import { chipGroup, townField } from "../picker.js";
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
      h("h1", { class: "page-title" }, "What’s happening in the market?"),
      h("p", { class: "lede" }, "Pick a town and flat type. Everything on this page updates to match."),
    ),
  );

  const row = h("div", { class: "filters__row" });
  root.append(h("div", { class: "filters" }, h("div", { class: "wrap" }, row)));

  const body = h("div", { class: "fade-on-load" });
  root.append(body);

  const kpiRow = h("div", { class: "grid grid--4" }, [0, 1, 2, 3].map(() => skeleton(124)));
  const headline = h("div");
  body.append(h("section", { class: "wrap section--tight" }, headline), h("section", { class: "wrap section" }, kpiRow));

  let last = null;
  const priceCard = chartCard({
    title: "Median resale price",
    sub: "Median price each month. The shaded band is the middle half of sales.",
    legend: [
      { label: "Median price", color: C.s1 },
      { label: "Middle 50% of sales", color: C.s1Band, kind: "area" },
      { label: "Oct 2024: new flat classification", color: C.faint },
    ],
    height: 380,
    tableView: () =>
      tableView(
        [
          { key: "month", label: "Month", format: monthLabel },
          { key: "median_price", label: "Median", align: "right", format: money },
          { key: "p25_price", label: "Lower quarter", align: "right", format: money },
          { key: "p75_price", label: "Upper quarter", align: "right", format: money },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        [...(last?.series || [])].reverse(),
      ),
  });
  const volumeCard = chartCard({
    title: "Flats sold",
    sub: "Resale flats sold each month.",
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
    title: "Price range",
    sub: "How prices were spread over the last 12 months.",
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
    sub: "Last 12 months.",
    height: 560,
    tableView: () =>
      tableView(
        [
          { key: "town", label: "Town", format: titleCase, primary: true },
          { key: "median_psm", label: "Per sqm", align: "right", format: money },
          { key: "median_price", label: "Median price", align: "right", format: money },
          { key: "yoy_pct", label: "From a year ago", align: "right", format: (v) => pct(v) },
          { key: "transactions", label: "Sales", align: "right", format: int },
        ],
        last?.town_ranking || [],
        { selectedKey: last?.filters.town, keyOf: (r) => r.town, stack: true },
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
  const types = [["ALL", "All"], ...meta.flat_types.map((t) => [t, flatTypeLabel(t)])];
  const storeys = [["ALL", "Any storey"], ...meta.storey_ranges.map((s) => [s, `Storey ${storeyLabel(s)}`])];
  const modelOptions = () => {
    const list = filters.flat_type === "ALL" ? [...new Set(Object.values(meta.flat_models).flat())].sort() : meta.flat_models[filters.flat_type] || [];
    return [["ALL", "Any model"], ...list.map((m) => [m, titleCase(m)])];
  };

  function drawFilters() {
    fill(
      row,
      townField({ id: "f-town", value: filters.town, allowAll: true, getFlatType: () => filters.flat_type, onChange: (v) => set({ town: v }), grow: true }),
      chipGroup({ label: "Flat type", options: types, value: filters.flat_type, onChange: (v) => set({ flat_type: v, flat_model: "ALL" }), grow: true }),
      select({ id: "f-storey", label: "Storey", options: storeys, value: filters.storey, onChange: (v) => set({ storey: v }) }),
      select({ id: "f-model", label: "Flat model", options: modelOptions(), value: filters.flat_model, onChange: (v) => set({ flat_model: v }) }),
      select({ id: "f-from", label: "From", options: years, value: filters.year_from, onChange: (v) => set({ year_from: Number(v) }) }),
      select({ id: "f-to", label: "To", options: years, value: filters.year_to, onChange: (v) => set({ year_to: Number(v) }) }),
    );
  }

  function set(patch) {
    Object.assign(filters, patch);
    if (filters.year_from > filters.year_to) [filters.year_from, filters.year_to] = [filters.year_to, filters.year_from];
    if (patch.town !== undefined && filters.town !== "ALL") update({ town: filters.town });
    if (patch.flat_type !== undefined && filters.flat_type !== "ALL") update({ flatType: filters.flat_type });
    // Only the model list and year order depend on other filters; redraw when they may have changed.
    if ("flat_type" in patch || "year_from" in patch || "year_to" in patch) drawFilters();
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
        ? "Too few recent sales to tell where prices are heading."
        : Math.abs(k.momentum_pct) < 1
          ? "Prices are about the same as three months ago."
          : k.momentum_pct > 0
            ? `Prices are ${pct(k.momentum_pct)} higher than three months ago.`
            : `Prices are ${pct(Math.abs(k.momentum_pct), 1, false)} lower than three months ago.`;
    fill(
      headline,
      h("p", { class: "insight" }, `${place}, ${what}: ${money(k.median_price)}${k.yoy_pct == null ? "" : `, ${pct(k.yoy_pct)} from a year ago`}.`),
      h("p", { class: "insight-sub" }, `${momentumText} Based on ${int(k.transactions_3m)} sales in ${k.window_label}.`),
    );

    fill(
      kpiRow,
      statTile({ label: "Median price", value: money(k.median_price), meta: [k.window_label] }),
      statTile({ label: "From a year ago", value: pct(k.yoy_pct), meta: [`It was ${money(k.median_price_year_ago)}`] }),
      statTile({ label: "Sold in the last 12 months", value: int(k.transactions_12m), meta: [delta(k.transactions_12m_change_pct), "vs the year before"] }),
      statTile({ label: "Price per sqm", value: money(k.median_psm), meta: [k.window_label] }),
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
            { color: C.s1Band, value: p25[i] == null ? null : moneyRange(p25[i], p75[i], true), label: "middle 50%" },
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
        tooltip: (i) => tooltipHtml(moneyRange(dist[i].from, dist[i].to), [{ color: C.s1, value: int(dist[i].count), label: "sales" }]),
      }),
    );
    distCard.el.querySelector(".sub").textContent = `${place}, ${what}. ${data.distribution_label}.`;

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
            { color: C.s1, value: `${money(ranking[i].median_psm)} per sqm`, label: "median" },
            { value: money(ranking[i].median_price), label: "median price" },
            { value: pct(ranking[i].yoy_pct), label: "from a year ago" },
            { value: int(ranking[i].transactions), label: "sales" },
          ]),
      }),
    );
    rankCard.chartEl.style.height = `${Math.max(240, ranking.length * 22 + 20)}px`;
    rankCard.el.querySelector(".sub").textContent = `${flatTypeLabel(f.flat_type, true)}, last 12 months. Per square metre makes towns with bigger flats comparable.`;
    [priceCard, volumeCard, distCard, rankCard].forEach((c) => c.refreshTable());

    fill(policySlot, policyCard(data, place, what));

    fill(
      nextSlot,
      f.town !== "ALL" && f.flat_type !== "ALL"
        ? nextStep({ title: `Where are ${place} prices heading?`, body: "See the six-month forecast and how wide the range is.", href: "#/forecast", cta: "See the forecast" })
        : nextStep({ title: "Pick a town and flat type", body: "Your choice carries over to the forecast, affordability and fair value steps.", href: "#/forecast", cta: "Go to the forecast" }),
    );
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
      h("h3", { class: "h3" }, "Before and after October 2024"),
      h("p", { class: "sub" }, "Too few sales on one side of October 2024 to compare."),
    );
  }
  return h(
    "article",
    { class: "card" },
    h("p", { class: "eyebrow" }, "Policy context"),
    h("h3", { class: "h3" }, "Before and after October 2024"),
    h("p", { class: "sub" }, `${place}, ${what}. HDB’s Standard, Plus and Prime flat categories started with the October 2024 BTO launch.`),
    h(
      "ul",
      { class: "breakdown mt-16" },
      h("li", {}, h("span", {}, "12 months before"), h("b", {}, money(p.before.median_price))),
      h("li", {}, h("span", {}, "Change in that year"), h("b", {}, pct(p.before.growth_pct))),
      h("li", {}, h("span", {}, "12 months after"), h("b", {}, money(p.after.median_price))),
      h("li", { class: "total" }, h("span", {}, "Change after October 2024"), h("b", {}, pct(p.after.growth_pct))),
    ),
    h("div", { class: "mt-16" }, callout("The new categories apply to new BTO flats, and resale records don’t say which category a flat is. So this shows what happened around that date. It doesn’t show the policy caused it.")),
  );
}

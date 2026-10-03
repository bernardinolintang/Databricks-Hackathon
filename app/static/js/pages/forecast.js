import { api } from "../api.js";
import { C, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { callout, errorBanner, fill, h, nextStep, skeleton, table } from "../dom.js";
import { flatTypeLabel, int, money, moneyRange, monthLabel } from "../format.js";
import { chipGroup, townField } from "../picker.js";
import { state, update } from "../state.js";

export async function render(root, { meta }) {
  const series = meta.forecast_series;
  const forecastTowns = Object.keys(series).filter((t) => t !== "ALL");
  let town = series[state.town] ? state.town : "TAMPINES";
  let flatType = pickType(town, state.flatType);

  function pickType(forTown, wanted) {
    const types = series[forTown] || [];
    if (types.includes(wanted)) return wanted;
    return types.includes("4 ROOM") ? "4 ROOM" : types[0];
  }

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 2 · Forecast"),
      h("h1", { class: "page-title" }, "Where could prices be in six months?"),
      h("p", { class: "lede" }, "A six-month outlook for each town. We tested it on past data before showing it here."),
    ),
  );

  const controls = h("div", { class: "filters__row" });
  root.append(h("div", { class: "filters" }, h("div", { class: "wrap" }, controls)));

  const reading = h("div", { class: "reading" }, skeleton(100));
  const chart = chartCard({
    title: "Median price and six-month forecast",
    sub: "Solid line is what flats sold for. Dashed line is the forecast. The shaded area is the likely range.",
    legend: [
      { label: "Sold price (median)", color: C.s1 },
      { label: "Forecast", color: C.s1, dashed: true },
      { label: "Likely range (80%)", color: C.s1Band, kind: "area" },
    ],
    height: 400,
    zoom: true,
    tableView: () => tableView(tableColumns, tableRows()),
  });
  const forecastTable = h("div", {}, skeleton(300));
  const evaluation = h("div", {}, skeleton(300));
  const body = h(
    "div",
    { class: "fade-on-load" },
    h("section", { class: "wrap section--tight" }, reading),
    h("section", { class: "wrap section" }, chart.el),
    h("section", { class: "wrap section--tight" }, h("div", { class: "grid grid--2" }, forecastTable, evaluation)),
    h(
      "section",
      { class: "wrap section" },
      callout("Past prices don’t guarantee future ones. This forecasts the median for the town, so single flats will sell above and below it. It doesn’t know about interest rates, new BTO supply or policy changes."),
    ),
  );
  root.append(body);
  const nextSlot = h("div");
  root.append(nextSlot);

  let last = null;
  const tableColumns = [
    { key: "month", label: "Month", format: monthLabel },
    { key: "actual", label: "Sold", align: "right", format: (v) => (v == null ? "" : money(v)) },
    { key: "forecast", label: "Forecast", align: "right", format: (v) => (v == null ? "" : money(v)) },
    { key: "lower", label: "Low", align: "right", format: (v) => (v == null ? "" : money(v)) },
    { key: "upper", label: "High", align: "right", format: (v) => (v == null ? "" : money(v)) },
  ];
  const tableRows = () => {
    if (!last?.available) return [];
    return [
      ...last.history.map((d) => ({ month: d.month, actual: d.median_price })),
      ...last.forecast.map((d) => ({ month: d.month, forecast: d.forecast_price, lower: d.lower_price, upper: d.upper_price })),
    ].reverse();
  };

  function drawControls() {
    const order = meta.flat_types.filter((t) => (series[town] || []).includes(t));
    const typeOptions = [...((series[town] || []).includes("ALL") ? [["ALL", "All"]] : []), ...order.map((t) => [t, flatTypeLabel(t)])];
    fill(
      controls,
      townField({
        id: "fc-town",
        value: town,
        allowAll: true,
        allLabel: "All of Singapore",
        enabled: forecastTowns,
        getFlatType: () => flatType,
        grow: true,
        onChange: (v) => {
          town = v;
          flatType = pickType(town, flatType);
          if (town !== "ALL") update({ town });
          drawControls();
          load();
        },
      }),
      chipGroup({
        label: "Flat type",
        options: typeOptions,
        value: flatType,
        onChange: (v) => {
          flatType = v;
          if (v !== "ALL") update({ flatType: v });
          load();
        },
      }),
    );
  }

  let token = 0;
  async function load() {
    const mine = ++token;
    body.classList.add("is-loading");
    try {
      const data = await api("forecast", { town, flat_type: flatType });
      if (mine !== token) return;
      last = data;
      draw(data);
    } catch (error) {
      if (mine === token) fill(reading, errorBanner(error.message));
    } finally {
      if (mine === token) body.classList.remove("is-loading");
    }
  }

  function draw(data) {
    if (!data.available) {
      fill(reading, h("p", { class: "insight" }, data.reason));
      fill(forecastTable);
      drawEvaluation(data.evaluation);
      return;
    }
    const r = data.reading;
    fill(
      reading,
      h("p", { class: "insight" }, r.headline),
      h("p", { class: "insight-sub" }, `${r.caveat} Prices averaged ${money(data.recent_level)} over the three months to ${data.last_actual_month}.`),
    );

    const hist = data.history;
    const fc = data.forecast;
    const months = [...hist.map((d) => d.month), ...fc.map((d) => d.month)];
    const n = hist.length;
    const lastActual = [...hist].reverse().find((d) => d.median_price != null)?.median_price ?? data.recent_level;
    const actual = [...hist.map((d) => d.median_price), ...fc.map(() => null)];
    const joinAt = (i) => (i === n - 1 ? lastActual : null);
    const projected = [...hist.map((_, i) => joinAt(i)), ...fc.map((d) => d.forecast_price)];
    const lower = [...hist.map((_, i) => joinAt(i)), ...fc.map((d) => d.lower_price)];
    const upper = [...hist.map((_, i) => joinAt(i)), ...fc.map((d) => d.upper_price)];

    mount(
      chart.chartEl,
      lineOption({
        months,
        series: [
          { name: "Sold price", values: actual, color: C.s1, connectNulls: true },
          { name: "Forecast", values: projected, color: C.s1, dashed: true, endDot: true, connectNulls: false },
        ],
        band: { lower, upper, color: C.s1Band },
        shadeFrom: fc[0].month,
        markers: [{ month: hist[n - 1].month, label: "Latest data" }],
        tooltip: (i) => {
          if (i < n)
            return tooltipHtml(monthLabel(months[i]), [
              { color: C.s1, value: money(actual[i]), label: "median sold price" },
              { value: int(hist[i].transactions), label: "sales" },
            ]);
          const f = fc[i - n];
          return tooltipHtml(`${monthLabel(f.month)} forecast`, [
            { color: C.s1, dashed: true, value: money(f.forecast_price), label: "forecast" },
            { color: C.s1Band, value: moneyRange(f.lower_price, f.upper_price), label: "likely range" },
          ]);
        },
      }),
    );
    chart.refreshTable();

    fill(
      forecastTable,
      h(
        "article",
        { class: "card" },
        h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "Month by month"), h("p", { class: "sub" }, `${data.place}. The range gets wider further out.`))),
        table(
          [
            { key: "month", label: "Month", format: monthLabel, primary: true },
            { key: "forecast_price", label: "Forecast", align: "right", format: money },
            { key: "lower_price", label: "Likely range", align: "right", format: (_, row) => moneyRange(row.lower_price, row.upper_price) },
          ],
          fc,
          { stack: true },
        ),
        h("div", { class: "card__foot" }, `The range comes from how far off past forecasts were for towns with ${data.volume_tier}.`),
      ),
    );
    drawEvaluation(data.evaluation);

    fill(
      nextSlot,
      nextStep({ title: "Can you afford it?", body: `Turn the ${data.place} price into a monthly repayment and upfront cost.`, href: "#/afford", cta: "Check affordability" }),
    );
  }

  function drawEvaluation(ev) {
    const methods = ev.methods;
    const selected = methods.find((m) => m.method === ev.selected_method);
    const ml = methods.find((m) => m.method === "gbm");
    const baselineWon = ev.selected_method === "rolling_3m" && ml;
    const origins = ev.validation_origins;
    fill(
      evaluation,
      h(
        "article",
        { class: "card" },
        h(
          "div",
          { class: "card__head" },
          h(
            "div",
            {},
            h("h3", { class: "h3" }, "How we picked this forecast"),
            h("p", { class: "sub" }, `We tried four methods on ${int(ev.series_count)} town and flat type combinations, starting from ${origins.length} past dates (${monthLabel(origins[0])} to ${monthLabel(origins[origins.length - 1])}), and compared each with what really sold.`),
          ),
        ),
        table(
          [
            { key: "label", label: "Method", primary: true, format: (v, row) => h("span", {}, v, " ", row.method === ev.selected_method ? h("span", { class: "badge" }, "Used") : null) },
            { key: "mape", label: "Average error", align: "right", format: (v) => `${v.toFixed(2)}%` },
            { key: "mae", label: "In dollars", align: "right", format: money },
          ],
          methods,
          { stack: true },
        ),
        h(
          "p",
          { class: "sub mt-16" },
          baselineWon
            ? `The simplest method won. Our machine learning model was ${(ml.mape - selected.mape).toFixed(2)} points behind because it expected prices to keep climbing after they levelled off in 2025. So we use the 3-month average, which mostly says prices stay near where they are.`
            : `${selected.label} beat the simple 3-month average, so we use it here.`,
        ),
        h("div", { class: "card__foot" }, "Average error is the average gap between forecast and real price, as a percentage. All test runs are logged in MLflow."),
      ),
    );
  }

  drawControls();
  await load();
}

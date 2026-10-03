import { api } from "../api.js";
import { C, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { callout, clear, fill, errorBanner, h, nextStep, select, skeleton, table } from "../dom.js";
import { flatTypeLabel, int, money, monthLabel, pct, titleCase } from "../format.js";
import { state, update } from "../state.js";

export async function render(root, { meta }) {
  const series = meta.forecast_series;
  const towns = Object.keys(series).sort((a, b) => (a === "ALL" ? -1 : b === "ALL" ? 1 : a.localeCompare(b)));
  let town = series[state.town] ? state.town : "TAMPINES";
  let flatType = (series[town] || []).includes(state.flatType) ? state.flatType : series[town]?.includes("4 ROOM") ? "4 ROOM" : "ALL";

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 2 · Forecast"),
      h("h1", { class: "page-title" }, "What could prices look like in six months?"),
      h("p", { class: "lede" }, "A town-level outlook built from monthly medians, tested against what actually happened before it is shown to you."),
    ),
  );

  const controls = h("div", { class: "filters__row" });
  root.append(h("div", { class: "filters" }, h("div", { class: "wrap" }, controls)));

  const reading = h("div", {}, skeleton(80));
  const chart = chartCard({
    title: "Monthly median price and six-month forecast",
    sub: "Solid line: recorded sales. Dashed line: forecast. Shaded band: the range that 80% of past forecasts landed within.",
    legend: [
      { label: "Recorded median", color: C.s1 },
      { label: "Forecast", color: C.s1, dashed: true },
      { label: "80% range", color: C.s1Band, kind: "area" },
    ],
    height: 400,
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
      callout(
        "Historical patterns do not guarantee future market movements. The forecast describes where the monthly median may sit; individual flats sell above and below it. Interest rates, new BTO supply and policy changes are not inputs to this model.",
      ),
    ),
  );
  root.append(body);
  const nextSlot = h("div");
  root.append(nextSlot);

  let last = null;
  const tableColumns = [
    { key: "month", label: "Month", format: monthLabel },
    { key: "actual", label: "Recorded", align: "right", format: money },
    { key: "forecast", label: "Forecast", align: "right", format: money },
    { key: "lower", label: "Low (80%)", align: "right", format: money },
    { key: "upper", label: "High (80%)", align: "right", format: money },
  ];
  const tableRows = () => {
    if (!last?.available) return [];
    return [
      ...last.history.map((d) => ({ month: d.month, actual: d.median_price })),
      ...last.forecast.map((d) => ({ month: d.month, forecast: d.forecast_price, lower: d.lower_price, upper: d.upper_price })),
    ].reverse();
  };

  function drawControls() {
    const typeOptions = (series[town] || []).slice().sort((a, b) => (a === "ALL" ? -1 : b === "ALL" ? 1 : a.localeCompare(b)));
    fill(controls, 
      select({
        id: "fc-town",
        label: "Town",
        options: towns.map((t) => [t, t === "ALL" ? "Singapore (all towns)" : titleCase(t)]),
        value: town,
        grow: true,
        onChange: (v) => {
          town = v;
          if (!(series[town] || []).includes(flatType)) flatType = series[town].includes("4 ROOM") ? "4 ROOM" : series[town][0];
          if (town !== "ALL") update({ town });
          drawControls();
          load();
        },
      }),
      select({
        id: "fc-type",
        label: "Flat type",
        options: typeOptions.map((t) => [t, flatTypeLabel(t)]),
        value: flatType,
        grow: true,
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
      clear(forecastTable);
      drawEvaluation(data.evaluation);
      return;
    }
    const r = data.reading;
    fill(reading, h("p", { class: "insight" }, r.headline), h("p", { class: "insight-sub" }, r.caveat, ` Starting level: ${money(data.recent_level)}, the average of the three months to ${data.last_actual_month}.`));

    const hist = data.history;
    const fc = data.forecast;
    const months = [...hist.map((d) => d.month), ...fc.map((d) => d.month)];
    const n = hist.length;
    const lastActual = [...hist].reverse().find((d) => d.median_price != null)?.median_price ?? data.recent_level;
    const actual = [...hist.map((d) => d.median_price), ...fc.map(() => null)];
    const projected = [...hist.map((_, i) => (i === n - 1 ? lastActual : null)), ...fc.map((d) => d.forecast_price)];
    const lower = [...hist.map((_, i) => (i === n - 1 ? lastActual : null)), ...fc.map((d) => d.lower_price)];
    const upper = [...hist.map((_, i) => (i === n - 1 ? lastActual : null)), ...fc.map((d) => d.upper_price)];

    mount(
      chart.chartEl,
      lineOption({
        months,
        series: [
          { name: "Recorded median", values: actual, color: C.s1, connectNulls: true },
          { name: "Forecast", values: projected, color: C.s1, dashed: true, endDot: true, connectNulls: false },
        ],
        band: { lower, upper, color: C.s1Band },
        shadeFrom: fc[0].month,
        markers: [{ month: hist[n - 1].month, label: "Latest data" }],
        tooltip: (i) => {
          if (i < n)
            return tooltipHtml(monthLabel(months[i]), [
              { color: C.s1, value: money(actual[i]), label: "recorded median" },
              { value: int(hist[i].transactions), label: "sales" },
            ]);
          const f = fc[i - n];
          return tooltipHtml(`${monthLabel(f.month)} · forecast`, [
            { color: C.s1, dashed: true, value: money(f.forecast_price), label: "forecast" },
            { color: C.s1Band, value: `${money(f.lower_price)} – ${money(f.upper_price)}`, label: "80% range" },
          ]);
        },
      }),
    );
    chart.refreshTable();

    fill(forecastTable, 
      h(
        "article",
        { class: "card" },
        h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "Month by month"), h("p", { class: "sub" }, `${data.place}. Range widens as the horizon grows.`))),
        table(
          [
            { key: "month", label: "Month", format: monthLabel },
            { key: "forecast_price", label: "Forecast", align: "right", format: money },
            { key: "lower_price", label: "80% range", align: "right", format: (_, row) => `${money(row.lower_price)} – ${money(row.upper_price)}` },
          ],
          fc,
        ),
        h("div", { class: "card__foot" }, `Range drawn from the model’s own past errors for series with ${data.volume_tier}.`),
      ),
    );
    drawEvaluation(data.evaluation);

    fill(nextSlot, 
      nextStep({
        title: "Can your household afford it?",
        body: `Turn the ${data.place} median into a monthly repayment, an upfront cost and a budget.`,
        href: "#/afford",
        cta: "Check affordability",
      }),
    );
  }

  function drawEvaluation(ev) {
    const methods = ev.methods;
    const selected = methods.find((m) => m.method === ev.selected_method);
    const runnerUp = methods.find((m) => m.method !== ev.selected_method);
    const baselineWon = ev.selected_method === "rolling_3m";
    fill(evaluation, 
      h(
        "article",
        { class: "card" },
        h(
          "div",
          { class: "card__head" },
          h(
            "div",
            {},
            h("h3", { class: "h3" }, "How this forecast was chosen"),
            h("p", { class: "sub" }, `Four methods forecast ${int(ev.series_count)} town and flat-type series from ${ev.validation_origins.length} past starting points (${monthLabel(ev.validation_origins[0])} to ${monthLabel(ev.validation_origins[ev.validation_origins.length - 1])}), then were scored against what sold.`),
          ),
        ),
        table(
          [
            { key: "label", label: "Method", format: (v, row) => h("span", {}, v, " ", row.method === ev.selected_method ? h("span", { class: "badge" }, "Used") : null) },
            { key: "mape", label: "Avg error", align: "right", format: (v) => `${v.toFixed(2)}%` },
            { key: "mae", label: "Avg $ error", align: "right", format: money },
          ],
          methods,
        ),
        h(
          "p",
          { class: "sub mt-16" },
          baselineWon
            ? `The simplest method was the most accurate. ${runnerUp.label} came within ${(runnerUp.mape - selected.mape).toFixed(2)} points but leaned high as the market flattened in 2025 and 2026, so FlatFair publishes the 3-month average and is upfront that the outlook is mostly “about where it is now”.`
            : `${selected.label} beat the 3-month average baseline, so it is used for the published forecast.`,
        ),
        h(
          "div",
          { class: "card__foot" },
          "Average error is mean absolute percentage error (MAPE). It is easy to read but weighs a miss on a cheaper flat type more heavily, so dollar error is shown too. Every run is logged in MLflow.",
        ),
      ),
    );
  }

  drawControls();
  await load();
}

// Chart layer on ECharts, following one set of mark specs everywhere:
// 2px lines, hairline solid grid, bars capped at 24px with rounded data ends,
// one crosshair tooltip per chart, and a table view for every chart.

import { h, clear, fill, segmented, table as htmlTable } from "./dom.js";
import { escapeHtml, moneyShort } from "./format.js";

export const C = {
  s1: "#00929c",
  s2: "#c2812e",
  s3: "#cc0000",
  s1Wash: "rgba(0,146,156,0.12)",
  s1Band: "rgba(0,146,156,0.16)",
  grid: "#ececf0",
  axis: "#d2d2d7",
  ink: "#1d1d1f",
  ink2: "#424245",
  muted: "#6e6e73",
  faint: "#86868b",
  rest: "#d9d9de",
  shade: "rgba(0,0,0,0.025)",
};
export const SERIES = [C.s1, C.s2, C.s3];
const FONT = getComputedStyle(document.documentElement).getPropertyValue("--font") || "Inter, sans-serif";

const live = new Set();

export function disposeCharts() {
  for (const { chart, observer } of live) {
    observer.disconnect();
    chart.dispose();
  }
  live.clear();
}

export function mount(el, option) {
  if (!window.echarts) {
    fill(el, h("div", { class: "empty" }, "The chart didn’t load. Switch to Table to see the numbers."));
    return null;
  }
  const existing = window.echarts.getInstanceByDom(el);
  const chart = existing || window.echarts.init(el, null, { renderer: "svg" });
  chart.setOption(option, true);
  if (!existing) {
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);
    live.add({ chart, observer });
  }
  return chart;
}

/** A card holding one chart, with a Chart / Table switch. */
export function chartCard({ title, sub, legend, height = 320, tableView, foot, className = "" }) {
  const chartEl = h("div", { class: "chart", style: { height: `${height}px` }, role: "img", "aria-label": title });
  const tableEl = h("div", { hidden: true });
  const toggle = tableView
    ? segmented(
        [
          ["chart", "Chart"],
          ["table", "Table"],
        ],
        "chart",
        (mode) => {
          const showTable = mode === "table";
          chartEl.hidden = showTable;
          tableEl.hidden = !showTable;
          if (showTable) fill(tableEl, tableView());
        },
        `${title} view`,
      )
    : null;
  const card = h(
    "article",
    { class: `card chart-card ${className}` },
    h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, title), sub ? h("p", { class: "sub" }, sub) : null), toggle),
    legend ? legendRow(legend) : null,
    chartEl,
    tableEl,
    foot ? h("div", { class: "card__foot" }, foot) : null,
  );
  return {
    el: card,
    chartEl,
    refreshTable() {
      if (!tableEl.hidden && tableView) fill(tableEl, tableView());
    },
  };
}

export function legendRow(items) {
  return h(
    "div",
    { class: "chart-legend" },
    items.map((item) =>
      h(
        "span",
        {},
        item.kind === "area"
          ? h("i", { class: "key-area", style: { background: item.color } })
          : item.kind === "dot"
            ? h("i", { class: "key-dot", style: { background: item.color } })
            : h("i", { class: `key-line${item.dashed ? " key-line--dashed" : ""}`, style: { background: item.color, color: item.color } }),
        item.label,
      ),
    ),
  );
}

export { htmlTable as tableView };

// ------------------------------------------------------------------ shared
function tooltipBase(formatter, trigger = "axis") {
  return {
    trigger,
    confine: true,
    backgroundColor: "rgba(255,255,255,0.97)",
    borderColor: "rgba(0,0,0,0.08)",
    borderWidth: 1,
    padding: [10, 12],
    textStyle: { color: C.ink, fontFamily: FONT, fontSize: 13 },
    extraCssText: "border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.10);",
    axisPointer: trigger === "axis" ? { type: "line", lineStyle: { color: C.faint, width: 1, type: "solid" }, z: 0 } : undefined,
    formatter,
  };
}

/** Tooltip body: value first (strong), series name second, keyed by a short line. */
export function tooltipHtml(title, rows) {
  const body = rows
    .filter((r) => r && r.value !== undefined && r.value !== null && r.value !== "n/a")
    .map(
      (r) =>
        `<div class="ff-tooltip__row"><i style="background:${r.color || C.faint}${r.dashed ? ";opacity:.6" : ""}"></i><b>${escapeHtml(r.value)}</b><span>${escapeHtml(r.label)}</span></div>`,
    )
    .join("");
  return `<div class="ff-tooltip"><div class="ff-tooltip__title">${escapeHtml(title)}</div>${body}</div>`;
}

function monthAxis(months, { boundaryGap = false } = {}) {
  const span = months.length;
  return {
    type: "category",
    data: months,
    boundaryGap,
    axisLine: { lineStyle: { color: C.axis } },
    axisTick: { show: false },
    axisLabel: {
      color: C.muted,
      fontSize: 12,
      hideOverlap: true,
      interval: (i, v) => (span > 30 ? v.endsWith("-01") : ["01", "04", "07", "10"].includes(v.slice(5))),
      formatter: (v) => {
        if (span > 30) return v.slice(0, 4);
        const [y, m] = v.split("-");
        return `${["Jan", "", "", "Apr", "", "", "Jul", "", "", "Oct"][Number(m) - 1]} ’${y.slice(2)}`;
      },
    },
  };
}

function valueAxis({ format = moneyShort, scale = true, min, max } = {}) {
  return {
    type: "value",
    scale,
    min,
    max,
    splitNumber: 4,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: C.muted, fontSize: 12, formatter: format },
    splitLine: { lineStyle: { color: C.grid, width: 1, type: "solid" } },
  };
}

function eventMarkers(markers = []) {
  if (!markers.length) return undefined;
  return {
    silent: false,
    symbol: "none",
    animation: false,
    label: { show: true, position: "end", distance: 4, color: C.ink2, fontSize: 11, fontFamily: FONT, formatter: (p) => p.name },
    lineStyle: { color: C.faint, width: 1, type: "solid" },
    emphasis: { disabled: true },
    data: markers.map((m) => ({ xAxis: m.month, name: m.label })),
  };
}

// ------------------------------------------------------------------ line
/**
 * series: [{ name, values, color, dashed, width, endDot, endLabel }]
 * band:   { lower, upper, color, name }      shaded range between two arrays
 * markers:[{ month, label }]                 hairline event markers
 * shadeFrom: month                           tint the region from here on
 */
export function lineOption({ months, series, band, markers, shadeFrom, tooltip, yFormat, yMin }) {
  const out = [];
  if (band) {
    out.push({
      name: "__band_low",
      type: "line",
      data: band.lower,
      stack: "band",
      symbol: "none",
      lineStyle: { opacity: 0 },
      silent: true,
      tooltip: { show: false },
      connectNulls: false,
    });
    out.push({
      name: "__band_span",
      type: "line",
      data: band.upper.map((u, i) => (u == null || band.lower[i] == null ? null : u - band.lower[i])),
      stack: "band",
      symbol: "none",
      lineStyle: { opacity: 0 },
      areaStyle: { color: band.color || C.s1Band },
      silent: true,
      tooltip: { show: false },
    });
  }
  series.forEach((s, idx) => {
    const lastIdx = lastIndex(s.values);
    out.push({
      name: s.name,
      type: "line",
      data: s.values.map((v, i) =>
        s.endDot && i === lastIdx
          ? { value: v, symbol: "circle", symbolSize: 9, itemStyle: { color: s.color, borderColor: "#fff", borderWidth: 2 } }
          : v,
      ),
      showSymbol: true,
      symbol: "none",
      smooth: 0.15,
      connectNulls: s.connectNulls ?? true,
      lineStyle: { color: s.color, width: s.width || 2, type: s.dashed ? [5, 4] : "solid", cap: "round", join: "round" },
      itemStyle: { color: s.color },
      areaStyle: s.area ? { color: s.areaColor || C.s1Wash } : undefined,
      emphasis: { disabled: true },
      z: 3 + idx,
      endLabel: s.endLabel
        ? { show: true, formatter: s.endLabel, color: C.ink2, fontSize: 12, fontWeight: 600, fontFamily: FONT, distance: 8 }
        : undefined,
      markLine: idx === 0 ? eventMarkers(markers) : undefined,
      markArea:
        idx === 0 && shadeFrom
          ? {
              silent: true,
              itemStyle: { color: C.shade },
              label: { show: true, position: "insideTop", color: C.muted, fontSize: 11, fontFamily: FONT, formatter: "Forecast" },
              data: [[{ xAxis: shadeFrom }, { xAxis: months[months.length - 1] }]],
            }
          : undefined,
    });
  });
  const endLabelRoom = series.some((s) => s.endLabel) ? 96 : 16;
  return {
    animationDuration: 450,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: endLabelRoom, top: markers?.length || shadeFrom ? 36 : 20, bottom: 4, containLabel: true },
    xAxis: monthAxis(months),
    yAxis: valueAxis({ format: yFormat, min: yMin }),
    tooltip: tooltipBase((params) => {
      const i = Array.isArray(params) ? params[0]?.dataIndex : params?.dataIndex;
      return i === undefined ? "" : tooltip(i);
    }),
    series: out,
  };
}

function lastIndex(values) {
  for (let i = values.length - 1; i >= 0; i -= 1) if (values[i] !== null && values[i] !== undefined) return i;
  return -1;
}

// ------------------------------------------------------------------ bars
/** Vertical columns over months (volume). */
export function columnsOption({ months, values, color = C.s1, tooltip, yFormat }) {
  return {
    animationDuration: 450,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 16, top: 16, bottom: 4, containLabel: true },
    xAxis: monthAxis(months, { boundaryGap: true }),
    yAxis: valueAxis({ format: yFormat || ((v) => (v >= 1000 ? `${v / 1000}K` : v)), scale: false }),
    tooltip: tooltipBase((params) => tooltip(params[0].dataIndex)),
    series: [
      {
        type: "bar",
        data: values,
        barMaxWidth: 24,
        barCategoryGap: "28%",
        itemStyle: { color, borderRadius: [2, 2, 0, 0] },
        emphasis: { itemStyle: { color: "#007a83" } },
      },
    ],
  };
}

/** Histogram: categories are bins; bars nearly touch with a 2px gap. */
export function histogramOption({ labels, values, tooltip, highlight }) {
  return {
    animationDuration: 450,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 16, top: 16, bottom: 4, containLabel: true },
    xAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: C.axis } },
      axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 12, hideOverlap: true },
    },
    yAxis: valueAxis({ format: (v) => v, scale: false }),
    tooltip: tooltipBase((params) => tooltip(params[0].dataIndex)),
    series: [
      {
        type: "bar",
        data: values.map((v, i) => ({ value: v, itemStyle: { color: highlight && highlight(i) ? C.s1 : highlight ? C.rest : C.s1 } })),
        barCategoryGap: "6%",
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
}

/** Horizontal ranked bars; one item can be emphasised and labelled. */
export function rankedBarsOption({ names, values, emphasise, format, tooltip, labelAll = false, color = C.s1 }) {
  const n = names.length;
  return {
    animationDuration: 450,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: labelAll ? 64 : 72, top: 4, bottom: 4, containLabel: true },
    xAxis: { ...valueAxis({ format, scale: false }), axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: {
      type: "category",
      inverse: true,
      data: names,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: C.ink2,
        fontSize: 12,
        formatter: (v) => v,
        rich: { b: { fontWeight: 700, color: C.ink } },
      },
    },
    tooltip: tooltipBase((p) => tooltip(p.dataIndex), "item"),
    series: [
      {
        type: "bar",
        data: values.map((v, i) => {
          const hit = emphasise ? emphasise(i) : false;
          return {
            value: v,
            itemStyle: { color: emphasise ? (hit ? color : C.rest) : color, borderRadius: [0, 4, 4, 0] },
            label: {
              show: labelAll || hit,
              position: "right",
              color: C.ink,
              fontWeight: 600,
              fontSize: 12,
              fontFamily: FONT,
              formatter: () => format(v),
            },
          };
        }),
        barMaxWidth: n > 15 ? 12 : 18,
        barCategoryGap: "30%",
      },
    ],
  };
}

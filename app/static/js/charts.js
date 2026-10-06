// Chart layer on ECharts, following one set of mark specs everywhere:
// 2px lines, hairline solid grid, bars capped at 24px with rounded data ends,
// one crosshair tooltip per chart, and a table view for every chart.
// Charts over months can be zoomed: scroll or the +/- buttons to zoom, drag to
// move, double-click to reset. The axis switches from years to months as you go in.

import { h, fill, iconSvg, segmented, table as htmlTable } from "./dom.js";
import { escapeHtml, moneyShort } from "./format.js";

export const C = {
  s1: "#00929c",
  s2: "#c2812e",
  s3: "#cc0000",
  s1Wash: "rgba(0,146,156,0.12)",
  s1Band: "rgba(0,146,156,0.16)",
  grid: "#e9ecef",
  axis: "#ced4da",
  ink: "#212529",
  ink2: "#495057",
  muted: "#6c757d",
  faint: "#868e96",
  rest: "#dee2e6",
  shade: "rgba(0,0,0,0.03)",
};
export const SERIES = [C.s1, C.s2, C.s3];
const FONT = getComputedStyle(document.documentElement).getPropertyValue("--font") || "sans-serif";
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Never zoom in past this many months: fewer says nothing about a trend.
const MIN_MONTHS = 6;
// A chart draws itself in once. After that, new data moves the marks to their new places.
const MOTION = { animationDuration: 450, animationDurationUpdate: 520, animationEasingUpdate: "cubicOut" };
const finePointer = () => window.matchMedia("(hover: hover) and (pointer: fine)").matches;

const live = new Set();
// How many months each zoomable chart is showing. The axis label rules read it.
const views = new WeakMap();
const zoomers = new WeakMap();

// A wheel that was scrolling the page a moment ago keeps scrolling the page,
// even when the pointer passes over a chart on the way.
let lastPageWheel = 0;
window.addEventListener(
  "wheel",
  (e) => {
    if (!(e.target instanceof Element) || !e.target.closest(".chart.is-zoomable")) lastPageWheel = performance.now();
  },
  { passive: true, capture: true },
);

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
  // Series keep their ids from one draw to the next, so a new town or filter
  // glides the line to its new shape. A series that is gone is dropped, and the
  // zoom starts over.
  chart.setOption(option, { replaceMerge: ["series", "dataZoom"] });
  if (!existing) {
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el);
    live.add({ chart, observer });
  }
  const view = views.get(option);
  if (view) zoomable(chart, el, view);
  return chart;
}

/** Wire zooming for a chart over months. Called on every mount; listeners attach once. */
function zoomable(chart, el, view) {
  let z = zoomers.get(el);
  if (!z) {
    z = { chart, view, start: 0, end: 100 };
    zoomers.set(el, z);
    el.classList.add("is-zoomable");
    const card = el.closest(".chart-card");
    z.zoomIn = card?.querySelector("[data-zoom='in']");
    z.zoomOut = card?.querySelector("[data-zoom='out']");
    z.reset = card?.querySelector("[data-zoom='reset']");
    z.zoomIn?.addEventListener("click", () => zoomBy(z, 0.6));
    z.zoomOut?.addEventListener("click", () => zoomBy(z, 1 / 0.6));
    z.reset?.addEventListener("click", () => setWindow(z, 0, 100));
    el.addEventListener(
      "wheel",
      (e) => {
        // Left alone, the chart library cancels every wheel over the plot, so
        // the page could not be scrolled past a chart. It never sees the event:
        // zooming is decided here, and anything else is left to the page.
        e.stopPropagation();
        if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
        const out = e.deltaY > 0;
        const now = performance.now();
        // Nothing left to zoom out of, or the page was mid-scroll: let the page have it.
        if ((out && z.end - z.start >= 100) || now - lastPageWheel < 400) {
          lastPageWheel = now;
          return;
        }
        e.preventDefault();
        const box = el.getBoundingClientRect();
        const at = z.chart.convertFromPixel({ gridIndex: 0 }, [e.clientX - box.left, e.clientY - box.top]);
        const anchor = Array.isArray(at) && Number.isFinite(at[0]) ? (Math.max(0, Math.min(z.view.total - 1, at[0])) / Math.max(1, z.view.total - 1)) * 100 : undefined;
        zoomBy(z, out ? 1.25 : 0.8, anchor);
      },
      // Capture, so this runs before the chart library's own listener.
      { passive: false, capture: true },
    );
  }
  // A fresh option (new town, new filter) starts fully zoomed out.
  z.chart = chart;
  z.view = view;
  z.start = 0;
  z.end = 100;
  if (!z.bound || z.bound !== chart) {
    z.bound = chart;
    chart.on("dataZoom", () => {
      // Dragging moves the window without changing its size.
      const zoom = chart.getOption().dataZoom?.[0];
      if (!zoom) return;
      z.start = zoom.start;
      z.end = zoom.end;
      syncZoomControls(z);
    });
    chart.getZr().on("dblclick", () => setWindow(z, 0, 100));
  }
  syncZoomControls(z);
}

function minSpan(z) {
  return Math.min(100, ((MIN_MONTHS - 1) / Math.max(1, z.view.total - 1)) * 100);
}

/** Zoom by `factor` (below 1 zooms in) around `anchor`, a percentage along the
 *  whole series. Without one, the newest months stay put. */
function zoomBy(z, factor, anchor) {
  const span = z.end - z.start;
  const next = Math.max(minSpan(z), Math.min(100, span * factor));
  const pivot = anchor === undefined ? z.end : Math.max(z.start, Math.min(z.end, anchor));
  const start = pivot - ((pivot - z.start) * next) / span;
  setWindow(z, start, start + next);
}

function setWindow(z, start, end) {
  const span = Math.max(minSpan(z), Math.min(100, end - start));
  start = Math.max(0, Math.min(100 - span, start));
  // Set before drawing: the axis label rules read it while the chart renders.
  z.view.visible = Math.max(2, Math.round((span / 100) * (z.view.total - 1)) + 1);
  z.chart.dispatchAction({ type: "dataZoom", start, end: start + span });
}

function syncZoomControls(z) {
  const span = z.end - z.start;
  if (z.zoomOut) z.zoomOut.disabled = span >= 99.9;
  if (z.zoomIn) z.zoomIn.disabled = span <= minSpan(z) + 0.1;
  if (z.reset) z.reset.hidden = span >= 99.9;
}

function zoomOption() {
  // Drag to move needs a mouse. On a touch screen a drag must scroll the page,
  // so there the buttons do the zooming and the newest months stay in view.
  return [{ type: "inside", xAxisIndex: 0, disabled: !finePointer(), zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true, zoomLock: false, throttle: 30 }];
}

/** A card holding one chart, with a Chart / Table switch. `zoom` adds zoom
 *  controls; use it for charts over months. */
export function chartCard({ title, sub, legend, height = 320, tableView, foot, className = "", zoom = false }) {
  const chartEl = h("div", { class: "chart", style: { height: `${height}px` }, role: "img", "aria-label": title });
  const tableEl = h("div", { hidden: true });
  const zoomButtons = zoom
    ? h(
        "div",
        { class: "zoom", role: "group", "aria-label": `Zoom ${title}` },
        h("button", { type: "button", "data-zoom": "out", "aria-label": "Zoom out", title: "Zoom out", disabled: true }, iconSvg("minus")),
        h("button", { type: "button", "data-zoom": "in", "aria-label": "Zoom in", title: "Zoom in" }, iconSvg("plus")),
      )
    : null;
  const zoomFoot = zoom
    ? h(
        "div",
        { class: "chart-foot" },
        h("span", { class: "chart-foot__hint" }, "Scroll to zoom. Drag to move."),
        h("button", { type: "button", "data-zoom": "reset", hidden: true }, "Show all months"),
      )
    : null;
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
          if (zoomButtons) zoomButtons.hidden = showTable;
          if (zoomFoot) zoomFoot.hidden = showTable;
          if (showTable) fill(tableEl, tableView());
        },
        `${title} view`,
      )
    : null;
  const card = h(
    "article",
    { class: `card chart-card ${className}` },
    h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, title), sub ? h("p", { class: "sub" }, sub) : null), h("div", { class: "card__tools" }, zoomButtons, toggle)),
    legend ? legendRow(legend) : null,
    chartEl,
    zoomFoot,
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
    extraCssText: "border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.10);",
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

/** `view.visible` is how many months are on screen; the labels follow it:
 *  years when zoomed out, quarters closer in, every month closest. */
function monthAxis(months, view, { boundaryGap = false } = {}) {
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
      interval: (i, v) => {
        if (view.visible > 30) return v.endsWith("-01");
        if (view.visible > 13) return ["01", "04", "07", "10"].includes(v.slice(5));
        return true;
      },
      formatter: (v) => {
        if (view.visible > 30) return v.slice(0, 4);
        const [y, m] = v.split("-");
        return `${MONTH_NAMES[Number(m) - 1]} ’${y.slice(2)}`;
      },
    },
  };
}

function monthView(months) {
  return { total: months.length, visible: months.length };
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
      id: "__band_low",
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
      id: "__band_span",
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
      id: s.name,
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
  const view = monthView(months);
  const option = {
    ...MOTION,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: endLabelRoom, top: markers?.length || shadeFrom ? 36 : 20, bottom: 4, containLabel: true },
    xAxis: monthAxis(months, view),
    yAxis: valueAxis({ format: yFormat, min: yMin }),
    dataZoom: zoomOption(),
    tooltip: tooltipBase((params) => {
      const i = Array.isArray(params) ? params[0]?.dataIndex : params?.dataIndex;
      return i === undefined ? "" : tooltip(i);
    }),
    series: out,
  };
  views.set(option, view);
  return option;
}

function lastIndex(values) {
  for (let i = values.length - 1; i >= 0; i -= 1) if (values[i] !== null && values[i] !== undefined) return i;
  return -1;
}

// ------------------------------------------------------------------ bars
/** Vertical columns over months (volume). */
export function columnsOption({ months, values, color = C.s1, tooltip, yFormat }) {
  const view = monthView(months);
  const option = {
    ...MOTION,
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 16, top: 16, bottom: 4, containLabel: true },
    xAxis: monthAxis(months, view, { boundaryGap: true }),
    yAxis: valueAxis({ format: yFormat || ((v) => (v >= 1000 ? `${v / 1000}K` : v)), scale: false }),
    dataZoom: zoomOption(),
    tooltip: tooltipBase((params) => tooltip(params[0].dataIndex)),
    series: [
      {
        id: "columns",
        type: "bar",
        data: values,
        barMaxWidth: 24,
        barCategoryGap: "28%",
        itemStyle: { color, borderRadius: [2, 2, 0, 0] },
        emphasis: { itemStyle: { color: "#007a83" } },
      },
    ],
  };
  views.set(option, view);
  return option;
}

/** Histogram: categories are bins; bars nearly touch with a 2px gap. */
export function histogramOption({ labels, values, tooltip, highlight }) {
  return {
    ...MOTION,
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
        id: "bins",
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
    ...MOTION,
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
        id: "bars",
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

// Interactive map of Singapore's HDB towns.
// Shapes come from URA planning areas (via the pipeline); towns are shaded by
// median price in five steps of one hue, light to dark. Every town is a real
// button: hover or focus shows its figures, click or Enter selects it.

import { api } from "./api.js";
import { h } from "./dom.js";
import { flatTypeLabel, int, money, moneyShort, pct, titleCase } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
const RAMP = ["#cfeaec", "#9dd3d8", "#5fb6be", "#22939d", "#066b75"];
const NO_DATA = "#e4e4e9";
const DISABLED = "#ededf1";
const SELECTED = "#cc0000"; // the chosen town is filled solid so the whole area reads at a glance

let mapPromise = null;
/** Town shapes, fetched once. Resolves to { available: false } if the build has no map. */
export function loadMap() {
  mapPromise = mapPromise || api("map").catch(() => ({ available: false }));
  return mapPromise;
}

export function loadTownStats(flatType) {
  return api("town-stats", { flat_type: !flatType || flatType === "ALL" ? "4 ROOM" : flatType });
}

function svg(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) el.setAttribute(k, v);
  return el;
}

/** Quantile breaks so each shade holds roughly the same number of towns. */
function breaksFor(values) {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < RAMP.length) return [];
  return [0.2, 0.4, 0.6, 0.8].map((q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]);
}

function shade(value, breaks) {
  if (value == null) return NO_DATA;
  if (!breaks.length) return RAMP[2];
  let i = 0;
  while (i < breaks.length && value >= breaks[i]) i += 1;
  return RAMP[i];
}

/**
 * createTownMap({ map, onSelect, animate })
 *   .update({ stats, selected, colors, enabled })
 *     stats     /api/town-stats payload
 *     selected  array of town names
 *     colors    optional { TOWN: "#hex" } outline colours for selected towns
 *     enabled   optional Set of selectable towns (others are greyed out)
 */
export function createTownMap({ map, onSelect, onHover, animate = true, label = "Map of Singapore's HDB towns" }) {
  const [, , W, H] = map.view_box;
  const root = h("div", { class: `townmap${animate ? " townmap--animate" : ""}` });
  const stage = h("div", { class: "townmap__stage" });
  const el = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "townmap__svg", role: "group", "aria-label": label, preserveAspectRatio: "xMidYMid meet" });
  const gContext = svg("g", { class: "townmap__context", "aria-hidden": "true" });
  const gTowns = svg("g", { class: "townmap__towns" });
  const gTop = svg("g", { class: "townmap__top" });
  el.append(gContext, gTowns, gTop);

  for (const shape of map.context) gContext.append(svg("path", { d: shape.d }));

  const paths = new Map();
  for (const town of map.towns) {
    const path = svg("path", { d: town.d, class: "townmap__town", "data-town": town.town, tabindex: "0", role: "button" });
    // Sweep in from west to east on first paint.
    path.style.setProperty("--delay", `${Math.round((town.cx / W) * 420)}ms`);
    paths.set(town.town, { path, town });
    gTowns.append(path);
  }

  const tooltip = h("div", { class: "townmap__tooltip", role: "status", hidden: true });
  const labels = h("div", { class: "townmap__labels", "aria-hidden": "true" });
  const legend = h("div", { class: "townmap__legend" });
  stage.append(el, labels, tooltip);
  root.append(stage, legend);

  let state = { stats: null, byTown: new Map(), selected: [], colors: {}, enabled: null, breaks: [] };

  function describe(name) {
    const row = state.byTown.get(name);
    const title = titleCase(name);
    if (state.enabled && !state.enabled.has(name)) return { title, value: "Not available here", sub: "" };
    if (!row) return { title, value: "No sales of this flat type", sub: "" };
    if (row.median_price_12m == null) return { title, value: "Too few sales", sub: `${int(row.transactions_12m)} in 12 months` };
    return {
      title,
      value: money(row.median_price_12m),
      sub: `${row.yoy_pct == null ? "" : `${pct(row.yoy_pct)} on a year ago · `}${int(row.transactions_12m)} sales`,
    };
  }

  function showTooltip(name, clientX, clientY) {
    const d = describe(name);
    tooltip.replaceChildren(h("b", {}, d.title), h("span", { class: "townmap__tooltip-value" }, d.value), d.sub ? h("span", {}, d.sub) : "");
    tooltip.hidden = false;
    const box = stage.getBoundingClientRect();
    let x, y;
    if (clientX == null) {
      const { town } = paths.get(name);
      x = (town.cx / W) * box.width;
      y = (town.cy / H) * box.height;
    } else {
      x = clientX - box.left;
      y = clientY - box.top;
    }
    const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
    // Keep the tooltip inside the map and clear of the finger or pointer.
    const left = Math.max(4, Math.min(box.width - tw - 4, x - tw / 2));
    const top = y - th - 14 < 0 ? y + 18 : y - th - 14;
    tooltip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    onHover?.(name);
  }

  function hideTooltip() {
    tooltip.hidden = true;
    onHover?.(null);
  }

  function choose(name) {
    if (state.enabled && !state.enabled.has(name)) return;
    onSelect?.(name);
  }

  for (const [name, { path }] of paths) {
    path.addEventListener("pointermove", (e) => (e.pointerType === "mouse" ? showTooltip(name, e.clientX, e.clientY) : null));
    path.addEventListener("pointerleave", hideTooltip);
    path.addEventListener("focus", () => showTooltip(name));
    path.addEventListener("blur", hideTooltip);
    path.addEventListener("click", () => choose(name));
    path.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        choose(name);
      }
    });
  }

  function drawLegend() {
    const values = [...state.byTown.values()].map((r) => r.median_price_12m).filter((v) => v != null);
    if (!values.length) {
      legend.replaceChildren(h("span", { class: "townmap__legend-note" }, "No price data for this flat type."));
      return;
    }
    const hasGaps = paths.size > values.length;
    legend.replaceChildren(
      h("span", { class: "townmap__legend-end" }, moneyShort(Math.min(...values))),
      h("span", { class: "townmap__ramp", "aria-hidden": "true" }, RAMP.map((c) => h("i", { style: { background: c } }))),
      h("span", { class: "townmap__legend-end" }, moneyShort(Math.max(...values))),
      hasGaps ? h("span", { class: "townmap__legend-gap" }, h("i", { style: { background: NO_DATA } }), "too few sales") : null,
    );
  }

  function update({ stats, selected, colors, enabled } = {}) {
    if (stats !== undefined) {
      state.stats = stats;
      state.byTown = new Map((stats?.towns || []).map((r) => [r.town, r]));
      state.breaks = breaksFor([...state.byTown.values()].map((r) => r.median_price_12m).filter((v) => v != null));
      drawLegend();
    }
    if (selected !== undefined) state.selected = selected.filter(Boolean);
    if (colors !== undefined) state.colors = colors || {};
    if (enabled !== undefined) state.enabled = enabled;

    labels.replaceChildren();
    for (const [name, { path, town }] of paths) {
      const row = state.byTown.get(name);
      const off = state.enabled && !state.enabled.has(name);
      const isSelected = state.selected.includes(name);
      const ring = state.colors[name] || SELECTED;
      path.style.fill = isSelected ? ring : off ? DISABLED : shade(row ? row.median_price_12m : null, state.breaks);
      path.classList.toggle("is-selected", isSelected);
      path.classList.toggle("is-off", Boolean(off));
      path.style.setProperty("--ring", ring);
      path.setAttribute("aria-pressed", String(isSelected));
      path.setAttribute("aria-disabled", String(Boolean(off)));
      const d = describe(name);
      path.setAttribute("aria-label", `${d.title}: ${d.value}${d.sub ? `, ${d.sub}` : ""}`);
      if (isSelected) {
        gTop.append(path); // paint the outline above its neighbours
        labels.append(
          h(
            "span",
            { class: "townmap__label", style: { left: `${(town.cx / W) * 100}%`, top: `${(town.cy / H) * 100}%`, "--ring": ring } },
            titleCase(name),
          ),
        );
      } else if (path.parentNode !== gTowns) {
        gTowns.append(path);
      }
    }
  }

  return { el: root, update, describe };
}

/** Caption under a map: what the shading means and where the shapes come from. */
export function mapCaption(stats, flatType) {
  const what = flatTypeLabel(!flatType || flatType === "ALL" ? "4 ROOM" : flatType).toLowerCase();
  return `Shaded by median ${what} resale price, ${stats.window_label}. Town outlines follow URA planning areas.`;
}

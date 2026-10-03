// App shell: loads metadata once, routes between pages, runs the Data Health panel.

import { api } from "./api.js";
import { disposeCharts } from "./charts.js";
import { clear, fill, errorBanner, h, iconSvg } from "./dom.js";
import { dateTime, int, monthLabel } from "./format.js";

const PAGES = {
  overview: () => import("./pages/overview.js"),
  market: () => import("./pages/market.js"),
  forecast: () => import("./pages/forecast.js"),
  afford: () => import("./pages/afford.js"),
  value: () => import("./pages/value.js"),
  compare: () => import("./pages/compare.js"),
};
const TITLES = {
  overview: "HDB resale intelligence",
  market: "Market explorer",
  forecast: "Six-month forecast",
  afford: "Affordability",
  value: "Fair value",
  compare: "Compare towns",
};

const view = document.getElementById("view");
let meta = null;
let renderToken = 0;

function currentRoute() {
  const name = (location.hash.replace(/^#\/?/, "").split("?")[0] || "overview").toLowerCase();
  return PAGES[name] ? name : "overview";
}

async function route() {
  const name = currentRoute();
  const token = ++renderToken;
  for (const tab of document.querySelectorAll(".tabs__item")) {
    if (tab.dataset.route === name) {
      tab.setAttribute("aria-current", "page");
      tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    } else tab.removeAttribute("aria-current");
  }
  document.title = `FlatFair · ${TITLES[name]}`;
  disposeCharts();
  clear(view);
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  try {
    const module = await PAGES[name]();
    if (token !== renderToken) return;
    await module.render(view, { meta });
  } catch (error) {
    if (token !== renderToken) return;
    console.error(error);
    fill(view, h("div", { class: "wrap section" }, errorBanner(`Something went wrong loading this page: ${error.message}`)));
  }
}

function renderHealth(m) {
  const q = m.quality;
  const button = document.getElementById("health-button");
  const allPassed = q.checks_passed === q.checks_total;
  button.dataset.state = allPassed ? "ok" : "warn";
  button.querySelector(".health__text").textContent = `Data through ${monthLabel(m.last_complete_month)}`;
  button.setAttribute("aria-label", `Data health: ${q.checks_passed} of ${q.checks_total} checks passed. Open details.`);

  const body = document.getElementById("health-body");
  fill(body, 
    h("p", { class: "eyebrow" }, "Data health"),
    h("h2", { class: "h2", id: "health-title" }, allPassed ? "All quality checks passed" : "Some checks need attention"),
    h(
      "p",
      { class: "sub" },
      `Pulled from data.gov.sg on ${dateTime(q.ingested_at)} via the ${q.ingestion_method === "api" ? "paginated datastore API" : "bulk export"}. `,
      `Source last updated ${dateTime(q.source_last_updated)}.`,
    ),
    h(
      "div",
      { class: "grid grid--2 mt-16" },
      miniStat("Total rows", int(q.total_rows)),
      miniStat("Valid rows", `${int(q.valid_rows)}`),
      miniStat("Invalid rows", int(q.invalid_rows)),
      miniStat("Exact duplicates", int(q.duplicate_rows), "Kept: no transaction ID separates two identical sales"),
      miniStat("Missing values", int(q.missing_values_total)),
      miniStat("Unusual $/sqm", int(q.price_outlier_rows), "Flagged and kept; mostly premium or short-lease flats"),
    ),
    h("h3", { class: "h3 mt-24" }, `Checks (${q.checks_passed}/${q.checks_total})`),
    h(
      "ul",
      { class: "checks mt-8" },
      q.checks.map((c) => h("li", { class: c.passed ? "pass" : "fail" }, iconSvg(c.passed ? "check" : "cross"), h("span", {}, c.description), h("b", {}, c.passed ? "Pass" : `${int(c.failed_rows)} rows`))),
    ),
    h(
      "p",
      { class: "small mt-16" },
      `Coverage ${monthLabel(q.earliest_month)} to ${monthLabel(q.latest_month)}. `,
      `${monthLabel(q.latest_month)} is still being registered, so analysis stops at ${monthLabel(q.last_complete_month)}. `,
      `Excluded from model training: ${int(q.excluded_from_model_rows)} rows (1-room and multi-generation flats, too few sales to model).`,
    ),
  );
}

function miniStat(label, value, note) {
  return h("div", { class: "tile", style: { boxShadow: "none", background: "var(--surface-2)", border: "1px solid var(--hairline)" } }, h("div", { class: "tile__label" }, label), h("div", { class: "tile__value", style: { fontSize: "24px" } }, value), note ? h("div", { class: "tile__meta" }, note) : null);
}

function wireSheet() {
  const sheet = document.getElementById("health-panel");
  const button = document.getElementById("health-button");
  const open = () => {
    sheet.hidden = false;
    sheet.querySelector(".sheet__close").focus();
  };
  const close = () => {
    sheet.hidden = true;
    button.focus();
  };
  button.addEventListener("click", () => (meta ? open() : null));
  sheet.addEventListener("click", (e) => (e.target.closest("[data-close]") ? close() : null));
  document.addEventListener("keydown", (e) => (e.key === "Escape" && !sheet.hidden ? close() : null));
}

async function boot() {
  wireSheet();
  try {
    meta = await api("meta");
    renderHealth(meta);
  } catch (error) {
    const button = document.getElementById("health-button");
    button.dataset.state = "down";
    button.querySelector(".health__text").textContent = "Data unavailable";
    fill(view, h("div", { class: "wrap section" }, errorBanner(`FlatFair could not load its data: ${error.message}`)));
    return;
  }
  window.addEventListener("hashchange", route);
  route();
}

boot();

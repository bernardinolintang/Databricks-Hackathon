// App shell: loads metadata once, routes between pages, runs the Data Health panel.

import { api } from "./api.js";
import { disposeCharts } from "./charts.js";
import { clear, fill, errorBanner, h, iconSvg } from "./dom.js";
import { dateLabel, dateTime, int, monthLabel } from "./format.js";
import { transition } from "./motion.js";
import { disposeMaps } from "./placemap.js";

const info = () => import("./pages/info.js");
const PAGES = {
  overview: () => import("./pages/overview.js"),
  market: () => import("./pages/market.js"),
  forecast: () => import("./pages/forecast.js"),
  afford: () => import("./pages/afford.js"),
  value: () => import("./pages/value.js"),
  compare: () => import("./pages/compare.js"),
  about: info,
  faq: info,
  sources: info,
  terms: info,
  privacy: info,
};
const TITLES = {
  overview: "HDB resale intelligence",
  market: "Market explorer",
  forecast: "Six-month forecast",
  afford: "Affordability",
  value: "Fair value",
  compare: "Compare towns",
  about: "About",
  faq: "Questions and answers",
  sources: "Where the data comes from",
  terms: "Terms of use",
  privacy: "Privacy",
};

const view = document.getElementById("view");
let meta = null;
let renderToken = 0;

// The app draws each page itself, so it also decides where the page starts.
// Left to the browser, a reload restores the old scroll position before the
// content exists and the page opens part of the way down.
if ("scrollRestoration" in history) history.scrollRestoration = "manual";

function currentRoute() {
  const name = (location.hash.replace(/^#\/?/, "").split("?")[0] || "overview").toLowerCase();
  return PAGES[name] ? name : "overview";
}

async function route() {
  const name = currentRoute();
  const token = ++renderToken;
  for (const tab of document.querySelectorAll("[data-route]")) {
    if (tab.dataset.route === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  document.title = `FlatFair · ${TITLES[name]}`;
  try {
    const module = await PAGES[name]();
    if (token !== renderToken) return;
    // Swap the page inside a view transition so sections cross-fade.
    await transition(() => {
      disposeCharts();
      disposeMaps();
      clear(view);
      window.scrollTo({ top: 0, behavior: "instant" });
      // Not awaited: pages paint their frame at once and fill in as data arrives.
      module.render(view, { meta, route: name }).catch((error) => {
        if (token !== renderToken) return;
        console.error(error);
        fill(view, h("div", { class: "wrap section" }, errorBanner(`Something went wrong loading this page: ${error.message}`)));
      });
    });
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
  const lastFull = monthLabel(q.last_complete_month);
  const openMonth = monthLabel(q.latest_month);
  button.dataset.state = allPassed ? "ok" : "warn";
  // The date the source was last refreshed. The month the averages stop at is
  // explained inside the panel, where there is room to say why.
  button.querySelector(".health__text").textContent = `Updated ${dateLabel(q.source_last_updated)}`;
  button.setAttribute("aria-label", `Data updated ${dateLabel(q.source_last_updated)}. ${q.checks_passed} of ${q.checks_total} checks passed. Open details.`);

  const body = document.getElementById("health-body");
  fill(
    body,
    h("p", { class: "eyebrow" }, "Data health"),
    h("h2", { class: "h2", id: "health-title" }, allPassed ? "All checks passed" : "Some checks failed"),
    h(
      "p",
      { class: "sub" },
      `We pulled this from data.gov.sg on ${dateTime(q.ingested_at)}. `,
      `HDB last updated it on ${dateTime(q.source_last_updated)}.`,
    ),
    q.latest_month !== q.last_complete_month
      ? h(
          "div",
          { class: "callout mt-16" },
          iconSvg("info"),
          h(
            "div",
            {},
            h("b", {}, `Prices and trends run up to ${lastFull}. `),
            `${openMonth} has only just started, so averaging it now would give a misleading number. Its sales already appear in the recent sales list on the Fair value page.`,
          ),
        )
      : null,
    h(
      "div",
      { class: "grid grid--2 mt-16" },
      miniStat("Total rows", int(q.total_rows)),
      miniStat("Valid rows", `${int(q.valid_rows)}`),
      miniStat("Invalid rows", int(q.invalid_rows)),
      miniStat("Exact duplicates", int(q.duplicate_rows), "Kept. Two flats can sell at the same price in the same block."),
      miniStat("Missing values", int(q.missing_values_total)),
      miniStat("Unusual prices", int(q.price_outlier_rows), "Flagged and kept. Mostly premium or short-lease flats."),
    ),
    h("h3", { class: "h3 mt-24" }, `Checks (${q.checks_passed}/${q.checks_total})`),
    h(
      "ul",
      { class: "checks mt-8" },
      q.checks.map((c) => h("li", { class: c.passed ? "pass" : "fail" }, iconSvg(c.passed ? "check" : "cross"), h("span", {}, c.description), h("b", {}, c.passed ? "Pass" : `${int(c.failed_rows)} failed`))),
    ),
    h(
      "p",
      { class: "small mt-16" },
      `The data runs from ${monthLabel(q.earliest_month)} to ${openMonth}. `,
      `${int(q.excluded_from_model_rows)} records are left out of the price model because too few 1-room and multi-generation flats are sold.`,
    ),
  );
}

function miniStat(label, value, note) {
  return h("div", { class: "tile tile--plain" }, h("div", { class: "tile__label" }, label), h("div", { class: "tile__value" }, value), note ? h("div", { class: "tile__meta" }, note) : null);
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

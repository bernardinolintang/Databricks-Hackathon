import { api } from "../api.js";
import { C, SERIES, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { callout, errorBanner, fill, h, iconSvg, skeleton, statusPill, toast } from "../dom.js";
import { flatTypeLabel, int, isNum, money, moneyRange, monthLabel, pct, ratio, titleCase } from "../format.js";
import { enter, leave } from "../motion.js";
import { chipGroup, openTownPicker } from "../picker.js";
import { state, update } from "../state.js";
import { createTownMap, loadMap, loadTownStats, mapCaption } from "../townmap.js";

const MAX = 3;

export async function render(root, { meta }) {
  // Slots keep each town's colour fixed: removing one town never repaints the others.
  let slots = normaliseSlots(state.compareSlots || state.compareTowns, meta.towns);
  if (state.town && meta.towns.includes(state.town) && !slots.includes(state.town)) {
    const free = slots.indexOf(null);
    slots[free === -1 ? 0 : free] = state.town;
  }
  let flatType = meta.common_flat_types.includes(state.flatType) ? state.flatType : "4 ROOM";

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 5 · Compare"),
      h("h1", { class: "page-title" }, "How do other towns compare?"),
      h("p", { class: "lede" }, "Put up to three towns side by side. See the price, how it has changed, and what you’d pay each month."),
    ),
  );

  const controls = h("div", { class: "filters__row" });
  root.append(h("div", { class: "filters" }, h("div", { class: "wrap" }, controls)));

  const verdictSlot = h("div", { class: "fill" }, skeleton(260));
  const mapSlot = h("div", { class: "fill" }, skeleton(260));
  const cards = h("div", { class: "grid grid--3", "data-cascade": "" }, [0, 1, 2].map(() => skeleton(380)));
  let last = null;
  const chart = chartCard({
    title: "Prices over the last five years",
    sub: "Median price, averaged over three months.",
    height: 360,
    zoom: true,
    tableView: () => {
      if (!last) return h("div");
      const months = last.series[0]?.points.map((p) => p.month) || [];
      const columns = [{ key: "month", label: "Month", format: monthLabel }, ...last.series.map((s) => ({ key: s.town, label: titleCase(s.town), align: "right", format: money }))];
      const rows = months.map((m, i) => Object.fromEntries([["month", m], ...last.series.map((s) => [s.town, s.points[i]?.median_price_3m])])).reverse();
      return tableView(columns, rows);
    },
  });
  const body = h(
    "div",
    {},
    h("section", { class: "wrap section--tight" }, h("div", { class: "grid grid--2" }, verdictSlot, mapSlot)),
    h("section", { class: "wrap section" }, cards),
    h("section", { class: "wrap section--tight" }, chart.el),
  );
  root.append(
    body,
    h(
      "section",
      { class: "wrap section" },
      callout(
        `Changes compare the median of flats sold in each period, so they partly reflect which flats were sold. Repayments use the loan settings from the Affordability step.${meta.has_location ? " Walking times are estimates from straight-line distance to the nearest MRT or LRT station, across flats sold in the last two years." : ""}`,
      ),
    ),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "next-step" },
        h("div", {}, h("h3", {}, "That’s all five steps"), h("p", {}, "Go back to any step, or try another flat.")),
        h("div", { class: "flex flex--wrap" }, h("a", { class: "btn btn--secondary", href: "#/afford" }, "Back to affordability"), h("a", { class: "btn btn--primary", href: "#/value" }, "Check another flat")),
      ),
    ),
  );

  const colourOf = (town) => SERIES[slots.indexOf(town)] || C.s1;

  // The same map as the picker, on the page: the chosen towns are filled in
  // their colours and a tap adds or removes one.
  let townMap = null;
  const mapCaptionEl = h("p", { class: "small comparemap__note" });
  loadMap().then((map) => {
    if (!map.available) {
      mapSlot.remove();
      verdictSlot.parentNode.classList.remove("grid--2");
      return;
    }
    townMap = createTownMap({ map, animate: false, onSelect: toggleTown, label: "Map of Singapore. Tap a town to add or remove it." });
    fill(
      mapSlot,
      h(
        "article",
        { class: "card comparemap" },
        h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "On the map"), h("p", { class: "sub" }, "Tap a town to add or remove it."))),
        townMap.el,
        mapCaptionEl,
      ),
    );
    drawMap();
  });

  async function drawMap() {
    if (!townMap) return;
    const forType = flatType;
    const stats = await loadTownStats(forType);
    if (forType !== flatType) return;
    const chosen = slots.filter(Boolean);
    townMap.update({ stats, selected: chosen, colors: Object.fromEntries(chosen.map((t) => [t, colourOf(t)])) });
    mapCaptionEl.textContent = mapCaption(stats, forType);
  }

  function toggleTown(town) {
    const at = slots.indexOf(town);
    if (at !== -1) {
      if (slots.filter(Boolean).length === 1) return toast("Keep at least one town.");
      slots[at] = null;
    } else {
      const free = slots.indexOf(null);
      if (free === -1) return toast(`Up to ${MAX} towns. Remove one first.`);
      slots[free] = town;
    }
    save();
  }

  async function pickTowns() {
    const chosen = await openTownPicker({
      title: "Choose towns to compare",
      selected: slots.filter(Boolean),
      multi: true,
      max: MAX,
      flatType,
      // Preview colours in the picker: kept towns hold their slot, new ones take the next free one.
      colorFor: (town, current) => {
        const kept = slots.indexOf(town);
        if (kept !== -1) return SERIES[kept];
        const free = [0, 1, 2].filter((i) => !slots[i] || !current.includes(slots[i]));
        const added = current.filter((t) => !slots.includes(t));
        return SERIES[free[added.indexOf(town)]] || C.s1;
      },
    });
    if (!chosen || !chosen.length) return;
    // Keep towns that stayed in their slot; fill freed slots with the new ones.
    const next = slots.map((t) => (t && chosen.includes(t) ? t : null));
    for (const town of chosen) if (!next.includes(town)) next[next.indexOf(null)] = town;
    slots = next;
    save();
  }

  function drawControls() {
    const chosen = slots.filter(Boolean);
    const chips = h(
      "div",
      { class: "town-chips" },
      slots.map((town, i) =>
        town
          ? h(
              "span",
              { class: "town-chip" },
              h("i", { style: { background: SERIES[i] } }),
              titleCase(town),
              chosen.length > 1
                ? h(
                    "button",
                    {
                      type: "button",
                      "aria-label": `Remove ${titleCase(town)}`,
                      onclick: () => {
                        slots[i] = null;
                        save();
                      },
                    },
                    iconSvg("close"),
                  )
                : null,
            )
          : null,
      ),
      h("button", { class: "btn btn--secondary btn--small", type: "button", onclick: pickTowns }, chosen.length < MAX ? "Add a town" : "Change towns"),
    );
    fill(
      controls,
      h("div", { class: "field field--chips" }, h("span", {}, `Towns (${chosen.length} of ${MAX})`), chips),
      chipGroup({
        label: "Flat type",
        options: meta.common_flat_types.map((t) => [t, flatTypeLabel(t)]),
        value: flatType,
        onChange: (v) => {
          flatType = v;
          update({ flatType: v });
          drawMap();
          load();
        },
      }),
    );
  }

  function save() {
    update({ compareSlots: slots, compareTowns: slots.filter(Boolean) });
    drawControls();
    drawMap();
    load();
  }

  let token = 0;
  async function load() {
    const mine = ++token;
    // What a new town or flat type redraws. The chart is not here: its lines move by themselves.
    const swapped = [verdictSlot, cards];
    try {
      const [data] = await Promise.all([api("compare", { towns: slots.filter(Boolean).join(","), flat_type: flatType, income: state.income, cash: state.cash }), last ? leave(swapped) : null]);
      if (mine !== token) return;
      last = data;
      draw(data);
    } catch (error) {
      if (mine !== token) return;
      fill(verdictSlot, errorBanner(error.message));
    }
    enter(swapped);
  }

  function draw(d) {
    const incomeNote = d.income_source === "yours" ? `your income of ${money(d.monthly_income)} a month` : `the median household income of ${money(d.monthly_income)} a month`;
    fill(
      verdictSlot,
      h(
        "article",
        { class: "card card--pad-lg" },
        h("p", { class: "eyebrow" }, "At a glance"),
        d.verdicts.length ? h("ul", { class: "verdicts" }, d.verdicts.map((v) => h("li", {}, v))) : h("p", { class: "sub" }, "Add another town to compare."),
        h("p", { class: "small mt-16" }, `${flatTypeLabel(d.flat_type, true)}, ${d.window_label}. Repayments are based on ${incomeNote}.`),
      ),
    );

    fill(
      cards,
      d.cards.map((c) => {
        const color = colourOf(c.town);
        if (!c.available) {
          return h("article", { class: "card compare-card", style: { "--accent": color } }, h("h3", { class: "h2" }, titleCase(c.town)), h("p", { class: "sub" }, `No ${flatTypeLabel(d.flat_type, true)} sold here recently.`));
        }
        const o = c.outlook;
        const af = c.affordability;
        const place = c.location;
        return h(
          "article",
          { class: "card compare-card", style: { "--accent": color } },
          h("h3", { class: "h2" }, titleCase(c.town)),
          h("div", { class: "tile__value" }, money(c.median_price)),
          h("p", { class: "small", style: { margin: "2px 0 0" } }, `Median price, ${int(c.transactions_12m)} sold`),
          h(
            "dl",
            { class: "kv" },
            h("dt", {}, "Price per sqm"),
            h("dd", {}, money(c.median_psm)),
            h("dt", {}, "From a year ago"),
            h("dd", {}, pct(c.yoy_pct)),
            h("dt", {}, "Over five years"),
            h("dd", {}, pct(c.change_5y_pct)),
            h("dt", {}, o ? `Forecast for ${o.month}` : "Forecast"),
            h("dd", {}, o ? money(o.forecast_price) : "Too few sales"),
            o ? h("dt", {}, "Likely range") : null,
            o ? h("dd", { style: { fontWeight: 500 } }, moneyRange(o.lower_price, o.upper_price, true)) : null,
            af ? h("dt", {}, "Monthly repayment") : null,
            af ? h("dd", {}, `${money(af.monthly_repayment)} (${ratio(af.repayment_ratio)})`) : null,
            place ? h("dt", { class: "kv__group" }, "Getting around") : null,
            place ? h("dt", {}, "Typical walk to a station") : null,
            place ? h("dd", {}, `${place.train_minutes} min`) : null,
            place && isNum(place.near_train_pct) ? h("dt", {}, `Flats within a ${place.near_train_minutes} min walk`) : null,
            place && isNum(place.near_train_pct) ? h("dd", {}, `${int(place.near_train_pct)}%`) : null,
          ),
          af ? h("div", { class: "mt-16" }, statusPill(af.status, af.status_label)) : null,
        );
      }),
    );

    const withPoints = d.series.filter((s) => s.points.length);
    if (withPoints.length) {
      const months = withPoints[0].points.map((p) => p.month);
      mount(
        chart.chartEl,
        lineOption({
          months,
          series: withPoints.map((s) => ({
            name: titleCase(s.town),
            values: s.points.map((p) => p.median_price_3m),
            color: colourOf(s.town),
            endDot: true,
            endLabel: () => titleCase(s.town),
          })),
          tooltip: (i) =>
            tooltipHtml(
              monthLabel(months[i]),
              withPoints.map((s) => ({ color: colourOf(s.town), value: money(s.points[i]?.median_price_3m), label: titleCase(s.town) })),
            ),
        }),
      );
    }
    chart.refreshTable();
    chart.el.querySelector(".chart-legend")?.remove();
    chart.el.querySelector(".card__head").after(
      h(
        "div",
        { class: "chart-legend" },
        withPoints.map((s) => h("span", {}, h("i", { class: "key-line", style: { background: colourOf(s.town) } }), titleCase(s.town))),
      ),
    );
  }

  drawControls();
  await load();
}

function normaliseSlots(saved, towns) {
  const list = Array.isArray(saved) ? saved : [];
  const slots = [0, 1, 2].map((i) => (towns.includes(list[i]) ? list[i] : null));
  if (!slots.some(Boolean)) return ["TAMPINES", "BEDOK", "PASIR RIS"];
  return slots;
}

import { api } from "../api.js";
import { C, SERIES, chartCard, lineOption, mount, tooltipHtml, tableView } from "../charts.js";
import { callout, clear, fill, errorBanner, h, iconSvg, select, skeleton, statusPill } from "../dom.js";
import { flatTypeLabel, int, money, monthLabel, pct, ratio, titleCase } from "../format.js";
import { state, update } from "../state.js";

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
      h("h1", { class: "page-title" }, "How do the alternatives stack up?"),
      h("p", { class: "lede" }, "Put up to three towns side by side on price, growth, outlook and what the repayment would take from your income."),
    ),
  );

  const controls = h("div", { class: "filters__row" });
  root.append(h("div", { class: "filters" }, h("div", { class: "wrap" }, controls)));

  const verdictSlot = h("div", {}, skeleton(140));
  const cards = h("div", { class: "grid grid--3" }, [0, 1, 2].map(() => skeleton(380)));
  let last = null;
  const chart = chartCard({
    title: "Price trend, last five years",
    sub: "Median over rolling three-month windows.",
    height: 360,
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
    { class: "fade-on-load" },
    h("section", { class: "wrap section--tight" }, verdictSlot),
    h("section", { class: "wrap section" }, cards),
    h("section", { class: "wrap section--tight" }, chart.el),
  );
  root.append(
    body,
    h("section", { class: "wrap section" }, callout("Growth figures compare medians of different sets of sales, so a change partly reflects which flats sold. Outlooks are six-month forecasts with an 80% range; repayments use the default loan assumptions from the Affordability step.")),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "next-step" },
        h("div", {}, h("h3", {}, "That’s the full picture"), h("p", {}, "Market, outlook, affordability, fair value and alternatives. Start again with another flat, or change any step.")),
        h("div", { class: "flex flex--wrap" }, h("a", { class: "btn btn--secondary", href: "#/afford" }, "Revisit affordability"), h("a", { class: "btn btn--primary", href: "#/value" }, "Value another flat")),
      ),
    ),
  );

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
    );
    const addable = meta.towns.filter((t) => !slots.includes(t));
    fill(controls, 
      h("div", { class: "field field--grow" }, h("span", {}, `Towns (${chosen.length} of ${MAX})`), chips),
      chosen.length < MAX
        ? select({
            id: "c-add",
            label: "Add a town",
            options: [["", "Choose…"], ...addable.map((t) => [t, titleCase(t)])],
            value: "",
            onChange: (v) => {
              if (!v) return;
              slots[slots.indexOf(null)] = v;
              save();
            },
          })
        : null,
      select({
        id: "c-type",
        label: "Flat type",
        options: meta.common_flat_types.map((t) => [t, flatTypeLabel(t)]),
        value: flatType,
        onChange: (v) => {
          flatType = v;
          update({ flatType: v });
          load();
        },
      }),
    );
  }

  function save() {
    update({ compareSlots: slots, compareTowns: slots.filter(Boolean) });
    drawControls();
    load();
  }

  let token = 0;
  async function load() {
    const mine = ++token;
    body.classList.add("is-loading");
    try {
      const data = await api("compare", { towns: slots.filter(Boolean).join(","), flat_type: flatType, income: state.income, cash: state.cash });
      if (mine !== token) return;
      last = data;
      draw(data);
    } catch (error) {
      if (mine === token) fill(verdictSlot, errorBanner(error.message));
    } finally {
      if (mine === token) body.classList.remove("is-loading");
    }
  }

  function colourOf(town) {
    return SERIES[slots.indexOf(town)] || C.s1;
  }

  function draw(d) {
    const incomeNote = d.income_source === "yours" ? `your income of ${money(d.monthly_income)} a month` : `the median household income of ${money(d.monthly_income)} a month`;
    fill(verdictSlot, 
      h(
        "article",
        { class: "card card--pad-lg" },
        h("p", { class: "eyebrow" }, "What stands out"),
        d.verdicts.length ? h("ul", { class: "verdicts" }, d.verdicts.map((v) => h("li", {}, v))) : h("p", { class: "sub" }, "Add another town to compare."),
        h("p", { class: "small mt-16" }, `${flatTypeLabel(d.flat_type, true)}, ${d.window_label}. Repayment shares use ${incomeNote}.`),
      ),
    );

    fill(cards, 
      ...d.cards.map((c) => {
        const color = colourOf(c.town);
        if (!c.available) {
          return h("article", { class: "card compare-card", style: { "--accent": color } }, h("h3", { class: "h2" }, titleCase(c.town)), h("p", { class: "sub" }, `No recent ${flatTypeLabel(d.flat_type, true)} sales.`));
        }
        const o = c.outlook;
        const af = c.affordability;
        return h(
          "article",
          { class: "card compare-card", style: { "--accent": color } },
          h("h3", { class: "h2" }, titleCase(c.town)),
          h("div", { class: "tile__value" }, money(c.median_price)),
          h("p", { class: "small", style: { margin: "2px 0 0" } }, `median ${flatTypeLabel(d.flat_type).toLowerCase()}, ${int(c.transactions_12m)} sales`),
          h(
            "dl",
            { class: "kv" },
            h("dt", {}, "Price per sqm"),
            h("dd", {}, money(c.median_psm)),
            h("dt", {}, "Year on year"),
            h("dd", {}, pct(c.yoy_pct)),
            h("dt", {}, "Five years"),
            h("dd", {}, pct(c.change_5y_pct)),
            h("dt", {}, `Outlook, ${o ? o.month : "six months"}`),
            h("dd", {}, o ? money(o.forecast_price) : "Too few sales"),
            o ? h("dt", {}, "80% range") : null,
            o ? h("dd", { style: { fontWeight: 500 } }, `${money(o.lower_price)} – ${money(o.upper_price)}`) : null,
            af ? h("dt", {}, "Monthly repayment") : null,
            af ? h("dd", {}, `${money(af.monthly_repayment)} · ${ratio(af.repayment_ratio)}`) : null,
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

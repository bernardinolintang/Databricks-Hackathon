import { api } from "../api.js";
import { C, chartCard, mount, rankedBarsOption, tooltipHtml, tableView } from "../charts.js";
import { callout, clear, fill, errorBanner, h, moneyInput, nextStep, numberInput, select, skeleton, statusPill, table } from "../dom.js";
import { flatTypeLabel, int, money, monthLabel, pct, storeyLabel, titleCase } from "../format.js";
import { state, update } from "../state.js";

export async function render(root, { meta }) {
  const valueTypes = meta.common_flat_types;
  const flat = {
    town: meta.towns.includes(state.town) ? state.town : "TAMPINES",
    flat_type: valueTypes.includes(state.flatType) ? state.flatType : "4 ROOM",
    floor_area: null,
    storey_range: null,
    remaining_lease: null,
    flat_model: null,
    asking_price: state.askingPrice,
  };
  let typical = null;
  let importanceRows = [];

  // Deep links: #/value?town=TAMPINES&type=4%20ROOM&area=95&storey=10%20TO%2012&lease=72&ask=690000
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const fromLink = params.has("area") || params.has("ask");
  if (params.get("town") && meta.towns.includes(params.get("town").toUpperCase())) flat.town = params.get("town").toUpperCase();
  if (params.get("type") && valueTypes.includes(params.get("type").toUpperCase())) flat.flat_type = params.get("type").toUpperCase();
  const linked = {
    floor_area: Number(params.get("area")) || null,
    storey_range: meta.storey_ranges.includes((params.get("storey") || "").toUpperCase()) ? params.get("storey").toUpperCase() : null,
    remaining_lease: Number(params.get("lease")) || null,
    flat_model: params.get("model") ? params.get("model").toUpperCase() : null,
  };
  if (params.get("ask")) flat.asking_price = Number(params.get("ask")) || null;

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 4 · Fair value"),
      h("h1", { class: "page-title" }, "Is the asking price in line?"),
      h("p", { class: "lede" }, "Describe the flat. FlatFair estimates what it would sell for today, shows the range similar sales fall in, and lists the closest recent transactions."),
    ),
  );

  const form = h("div", { class: "card stack" }, skeleton(420));
  const result = h("div", { class: "stack fade-on-load" }, skeleton(300), skeleton(260));
  root.append(h("section", { class: "wrap section" }, h("div", { class: "grid grid--side" }, h("div", { style: { position: "sticky", top: "calc(var(--nav-h) + 16px)" } }, form), result)));

  const compsSlot = h("div", {}, skeleton(320));
  const importance = chartCard({
    title: "What drives estimates overall",
    sub: "How much worse the model gets when each input is scrambled, as a share of the total.",
    height: 260,
    tableView: () =>
      tableView(
        [
          { key: "label", label: "Input" },
          { key: "share_pct", label: "Share", align: "right", format: (v) => `${v.toFixed(1)}%` },
        ],
        importanceRows,
      ),
  });
  const accuracySlot = h("div");
  root.append(
    h("section", { class: "wrap section" }, compsSlot),
    h("section", { class: "wrap section--tight" }, h("div", { class: "grid grid--2" }, importance.el, accuracySlot)),
    h(
      "section",
      { class: "wrap section" },
      callout(
        "Fair value estimates are statistical estimates from historical open data. They cannot see renovation quality, the exact unit, its facing or view, noise, nearby amenities changing, or how a negotiation goes. Treat the range, not the single number, as the answer.",
      ),
    ),
    nextStep({ title: "Weigh up the alternatives", body: "Put this town next to two others on price, growth, outlook and what you can afford.", href: "#/compare", cta: "Compare towns" }),
  );

  async function loadTypical(resetFields) {
    try {
      typical = await api("fair-value/typical", { town: flat.town, flat_type: flat.flat_type });
    } catch (error) {
      fill(form, errorBanner(error.message));
      return false;
    }
    if (resetFields || flat.floor_area == null) {
      flat.floor_area = typical.floor_area_sqm;
      flat.storey_range = typical.storey_range;
      flat.remaining_lease = typical.remaining_lease_years;
      flat.flat_model = typical.flat_model;
    } else if (!typical.flat_models.includes(flat.flat_model)) {
      flat.flat_model = typical.flat_model;
    }
    drawForm();
    return true;
  }

  function drawForm() {
    const storeys = meta.storey_ranges.map((s) => [s, `Storey ${storeyLabel(s)}`]);
    fill(form, 
      h("h2", { class: "h3" }, "The flat"),
      select({
        id: "v-town",
        label: "Town",
        options: meta.towns.map((t) => [t, titleCase(t)]),
        value: flat.town,
        onChange: async (v) => {
          flat.town = v;
          update({ town: v });
          if (await loadTypical(true)) estimate();
        },
      }),
      select({
        id: "v-type",
        label: "Flat type",
        options: valueTypes.map((t) => [t, flatTypeLabel(t)]),
        value: flat.flat_type,
        onChange: async (v) => {
          flat.flat_type = v;
          update({ flatType: v });
          if (await loadTypical(true)) estimate();
        },
      }),
      numberInput({
        id: "v-area",
        label: "Floor area",
        value: flat.floor_area,
        step: 1,
        min: 20,
        max: 300,
        suffix: "sqm",
        hint: typical ? `Most ${flatTypeLabel(flat.flat_type, true)} here: ${int(typical.floor_area_range[0])}–${int(typical.floor_area_range[1])} sqm` : null,
        onChange: (v) => set({ floor_area: v }),
      }),
      select({ id: "v-storey", label: "Storey", options: storeys, value: flat.storey_range, onChange: (v) => set({ storey_range: v }) }),
      numberInput({
        id: "v-lease",
        label: "Remaining lease",
        value: flat.remaining_lease,
        step: 1,
        min: 1,
        max: 99,
        suffix: "years",
        hint: typical ? `Recent sales here: ${Math.round(typical.lease_range[0])}–${Math.round(typical.lease_range[1])} years left` : null,
        onChange: (v) => set({ remaining_lease: v }),
      }),
      select({
        id: "v-model",
        label: "Flat model",
        options: (typical?.flat_models || [flat.flat_model]).map((m) => [m, titleCase(m)]),
        value: flat.flat_model,
        onChange: (v) => set({ flat_model: v }),
      }),
      moneyInput({ id: "v-ask", label: "Asking price (optional)", value: flat.asking_price, placeholder: "e.g. 690000", hint: "Compared against the expected range", onChange: (v) => set({ asking_price: v }) }),
      typical ? h("p", { class: "hint" }, `Pre-filled with a typical ${flatTypeLabel(flat.flat_type).toLowerCase()} flat in ${titleCase(flat.town)} (${int(typical.sales)} sales in the last two years). Change anything.`) : null,
    );
  }

  function set(patch) {
    Object.assign(flat, patch);
    if ("asking_price" in patch) update({ askingPrice: flat.asking_price });
    estimate();
  }

  let token = 0;
  async function estimate() {
    if (!flat.floor_area || !flat.remaining_lease) return;
    const mine = ++token;
    result.classList.add("is-loading");
    try {
      const data = await api("fair-value", {
        town: flat.town,
        flat_type: flat.flat_type,
        floor_area: flat.floor_area,
        storey_range: flat.storey_range,
        remaining_lease: flat.remaining_lease,
        flat_model: flat.flat_model,
        asking_price: flat.asking_price,
      });
      if (mine !== token) return;
      draw(data);
    } catch (error) {
      if (mine === token) fill(result, errorBanner(error.message));
    } finally {
      if (mine === token) result.classList.remove("is-loading");
    }
  }

  function draw(d) {
    const [low, high] = d.range;
    const cmp = d.comparison;
    const f = d.flat;

    // Range bar scale: pad around the range and the asking price.
    const points = [low, high, d.estimate, cmp?.asking_price].filter(Boolean);
    const span = Math.max(...points) - Math.min(...points);
    const lo = Math.min(...points) - span * 0.25;
    const hi = Math.max(...points) + span * 0.25;
    const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;

    const summary = h(
      "article",
      { class: "card card--pad-lg" },
      h("div", { class: "value-hero" }, h("span", { class: "value-hero__label" }, `Estimated market value, ${d.valuation_month}`), h("span", { class: "value-hero__num" }, money(d.estimate))),
      h("p", { class: "value-hero__range" }, `Expected range ${money(low)} – ${money(high)}`),
      h(
        "div",
        { class: "range-bar", role: "img", "aria-label": `Expected range ${money(low)} to ${money(high)}${cmp ? `, asking price ${money(cmp.asking_price)}` : ""}` },
        h("div", { class: "range-bar__track" }),
        h("div", { class: "range-bar__band", style: { left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` } }),
        h("div", { class: "range-bar__tick", style: { left: pos(d.estimate) } }),
        h("span", { class: "range-bar__label range-bar__label--bottom", style: { left: pos(low) } }, money(low)),
        h("span", { class: "range-bar__label range-bar__label--bottom", style: { left: pos(high) } }, money(high)),
        cmp ? h("div", { class: "range-bar__ask", style: { left: pos(cmp.asking_price) } }) : null,
        cmp ? h("span", { class: "range-bar__label range-bar__label--top", style: { left: pos(cmp.asking_price) } }, `Asking ${money(cmp.asking_price)}`) : null,
      ),
      cmp
        ? h(
            "div",
            { class: "flex flex--wrap mt-16" },
            statusPill(cmp.position, cmp.label),
            h("span", { class: "muted" }, `${pct(cmp.difference_pct)} · ${money(Math.abs(cmp.difference))} ${cmp.difference >= 0 ? "above" : "below"} the estimate`),
          )
        : h("p", { class: "sub mt-16" }, "Add an asking price to see where it sits against the range."),
      h(
        "p",
        { class: "small mt-16" },
        `${Math.round(d.interval_level * 100)}% of recent ${d.interval_basis === "ALL" ? "" : `${flatTypeLabel(d.interval_basis).toLowerCase()} `}sales in testing sold within this range of their estimate. `,
        `${titleCase(f.town)}, ${flatTypeLabel(f.flat_type).toLowerCase()}, ${int(f.floor_area_sqm)} sqm, storey ${storeyLabel(f.storey_range)}, ${Math.round(f.remaining_lease_years)} years left, ${titleCase(f.flat_model)}.`,
      ),
    );

    const typicalLine = `${titleCase(d.typical.town)} ${flatTypeLabel(d.typical.flat_type).toLowerCase()} typical: ${int(d.typical.floor_area_sqm)} sqm, storey ${storeyLabel(d.typical.storey_range)}, ${Math.round(d.typical.remaining_lease_years)} years left, worth about ${money(d.typical.estimate)}.`;
    const maxEffect = Math.max(1, ...d.drivers.map((x) => Math.abs(x.effect)));
    const drivers = h(
      "article",
      { class: "card" },
      h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "What moves this estimate"), h("p", { class: "sub" }, typicalLine))),
      d.drivers.length
        ? d.drivers.map((x) =>
            h(
              "div",
              { class: "driver" },
              h("div", {}, h("div", { style: { fontWeight: 600 } }, x.label), h("div", { class: "small" }, `${x.yours} vs ${x.typical}`)),
              h("div", { class: "driver__bar", "aria-hidden": "true" }, h("i", { class: x.effect >= 0 ? "pos" : "neg", style: { width: `${(Math.abs(x.effect) / maxEffect) * 50}%` } })),
              h("div", { class: "driver__val" }, `${x.effect >= 0 ? "+" : "−"}${money(Math.abs(x.effect))}`),
            ),
          )
        : h("p", { class: "sub" }, "This flat matches the typical one on every input. Change its size, storey or remaining lease to see what each difference is worth."),
      h("div", { class: "card__foot" }, "Each line swaps one input back to the typical value and measures the change. Effects interact, so they do not add up exactly to the difference."),
    );
    fill(result, summary, drivers);

    fill(compsSlot, 
      h(
        "article",
        { class: "card" },
        h(
          "div",
          { class: "card__head" },
          h("div", {}, h("h3", { class: "h3" }, "Most comparable recent sales"), h("p", { class: "sub" }, `Same town and flat type, last 24 months, ranked by closeness in size, storey, remaining lease and date.`)),
        ),
        d.comparables.length
          ? table(
              [
                { key: "month", label: "Sold", format: monthLabel },
                { key: "block", label: "Address", format: (v, row) => `Blk ${v} ${titleCase(row.street_name)}` },
                { key: "storey_range", label: "Storey", format: storeyLabel },
                { key: "floor_area_sqm", label: "Area", align: "right", format: (v) => `${int(v)} sqm` },
                { key: "remaining_lease_years", label: "Lease left", align: "right", format: (v) => `${Math.round(v)} yrs` },
                { key: "resale_price", label: "Price", align: "right", format: money },
                { key: "price_per_sqm", label: "$/sqm", align: "right", format: money },
                { key: "similarity", label: "Match", align: "right", format: (v) => h("span", { class: "badge" }, `${int(v)}%`) },
              ],
              d.comparables,
            )
          : h("div", { class: "empty" }, h("h3", {}, "No close matches"), "There were no sales of this flat type in this town over the last 24 months."),
      ),
    );

    importanceRows = d.importance;
    const imp = d.importance.filter((x) => x.share_pct > 0);
    mount(
      importance.chartEl,
      rankedBarsOption({
        names: imp.map((x) => x.label),
        values: imp.map((x) => x.share_pct),
        format: (v) => `${v.toFixed(0)}%`,
        labelAll: true,
        tooltip: (i) => tooltipHtml(imp[i].label, [{ color: C.s1, value: `${imp[i].share_pct.toFixed(1)}%`, label: "share of importance" }]),
      }),
    );
    importance.refreshTable();

    const acc = d.accuracy;
    fill(accuracySlot, 
      h(
        "article",
        { class: "card" },
        h("h3", { class: "h3" }, "How accurate is it?"),
        h(
          "p",
          { class: "sub" },
          `Trained on sales up to ${monthLabel(previousMonth(acc.holdout_period[0]))}, then tested on ${int(acc.holdout_rows)} sales from ${monthLabel(acc.holdout_period[0])} to ${monthLabel(acc.holdout_period[1])} that it never saw.`,
        ),
        h(
          "ul",
          { class: "breakdown mt-16" },
          h("li", {}, h("span", {}, "Typical error (median)"), h("b", {}, `${acc.median_ape.toFixed(1)}%`)),
          h("li", {}, h("span", {}, "Sales estimated within 10%"), h("b", {}, `${acc.within_10pct.toFixed(0)}%`)),
          h("li", {}, h("span", {}, "Average error, gradient boosting"), h("b", {}, `${acc.mape.toFixed(1)}%`)),
          h("li", {}, h("span", {}, "Average error, “$ per sqm × size” rule of thumb"), h("b", {}, `${acc.baseline_mape.toFixed(1)}%`)),
        ),
      ),
    );
  }

  if (await loadTypical(false)) {
    if (fromLink) {
      for (const [key, value] of Object.entries(linked)) if (value) flat[key] = value;
      drawForm();
    }
    await estimate();
  }
}

function previousMonth(ym) {
  const [y, m] = ym.split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
}


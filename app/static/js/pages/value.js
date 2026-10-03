import { api } from "../api.js";
import { C, chartCard, mount, rankedBarsOption, tooltipHtml, tableView } from "../charts.js";
import { callout, errorBanner, fill, h, moneyInput, nextStep, numberInput, select, skeleton, statusPill, table } from "../dom.js";
import { flatTypeLabel, int, money, moneyRange, monthLabel, pct, storeyLabel, titleCase } from "../format.js";
import { chipGroup, townField } from "../picker.js";
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
      h("h1", { class: "page-title" }, "Is the asking price fair?"),
      h("p", { class: "lede" }, "Describe the flat. We’ll estimate what it would sell for today and show the closest recent sales."),
    ),
  );

  const form = h("div", { class: "card stack" }, skeleton(420));
  const result = h("div", { class: "stack fade-on-load" }, skeleton(300), skeleton(260));
  root.append(h("section", { class: "wrap section" }, h("div", { class: "grid grid--side" }, h("div", { class: "side-sticky" }, form), result)));

  const compsSlot = h("div", {}, skeleton(320));
  const importance = chartCard({
    title: "What matters most to price",
    sub: "How much each detail affects the estimate, across all flats.",
    height: 260,
    tableView: () =>
      tableView(
        [
          { key: "label", label: "Detail" },
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
      callout("This is an estimate from past sales. It can’t see renovation, the exact unit, which way it faces, the view or the noise. Go by the range more than the single number."),
    ),
    nextStep({ title: "Look at other towns", body: "Compare this town with two others on price, growth and what you’d pay each month.", href: "#/compare", cta: "Compare towns" }),
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
    fill(
      form,
      h("h2", { class: "h3" }, "The flat"),
      townField({
        id: "v-town",
        value: flat.town,
        getFlatType: () => flat.flat_type,
        onChange: async (v) => {
          flat.town = v;
          update({ town: v });
          if (await loadTypical(true)) estimate();
        },
      }),
      chipGroup({
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
        hint: typical ? `Most here are ${int(typical.floor_area_range[0])} to ${int(typical.floor_area_range[1])} sqm` : null,
        onChange: (v) => set({ floor_area: v }),
      }),
      select({ id: "v-storey", label: "Storey", options: storeys, value: flat.storey_range, onChange: (v) => set({ storey_range: v }) }),
      numberInput({
        id: "v-lease",
        label: "Lease left",
        value: flat.remaining_lease,
        step: 1,
        min: 1,
        max: 99,
        suffix: "years",
        hint: typical ? `Recent sales here had ${Math.round(typical.lease_range[0])} to ${Math.round(typical.lease_range[1])} years left` : null,
        onChange: (v) => set({ remaining_lease: v }),
      }),
      select({
        id: "v-model",
        label: "Flat model",
        options: (typical?.flat_models || [flat.flat_model]).map((m) => [m, titleCase(m)]),
        value: flat.flat_model,
        onChange: (v) => set({ flat_model: v }),
      }),
      moneyInput({ id: "v-ask", label: "Asking price (optional)", value: flat.asking_price, placeholder: "e.g. 690000", hint: "We’ll show where it sits in the range", onChange: (v) => set({ asking_price: v }) }),
      typical ? h("p", { class: "hint" }, `Filled in with a typical ${flatTypeLabel(flat.flat_type).toLowerCase()} flat in ${titleCase(flat.town)}. Change anything to match yours.`) : null,
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
      h("div", { class: "value-hero" }, h("span", { class: "value-hero__label" }, `Estimated value, ${d.valuation_month}`), h("span", { class: "value-hero__num" }, money(d.estimate))),
      h("p", { class: "value-hero__range" }, `Usual range: ${moneyRange(low, high)}`),
      h(
        "div",
        { class: "range-bar", role: "img", "aria-label": `Usual range ${moneyRange(low, high)}${cmp ? `, asking price ${money(cmp.asking_price)}` : ""}` },
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
            h("span", { class: "muted" }, `${money(Math.abs(cmp.difference))} ${cmp.difference >= 0 ? "above" : "below"} the estimate (${pct(cmp.difference_pct)})`),
          )
        : h("p", { class: "sub mt-16" }, "Add an asking price to see where it sits."),
      h(
        "p",
        { class: "small mt-16" },
        `In testing, ${Math.round(d.interval_level * 100)}% of ${d.interval_basis === "ALL" ? "" : `${flatTypeLabel(d.interval_basis).toLowerCase()} `}flats sold within this range. `,
        `${titleCase(f.town)}, ${flatTypeLabel(f.flat_type).toLowerCase()}, ${int(f.floor_area_sqm)} sqm, storey ${storeyLabel(f.storey_range)}, ${Math.round(f.remaining_lease_years)} years left, ${titleCase(f.flat_model)}.`,
      ),
    );

    const typicalLine = `A typical ${flatTypeLabel(d.typical.flat_type).toLowerCase()} flat in ${titleCase(d.typical.town)} is ${int(d.typical.floor_area_sqm)} sqm, storey ${storeyLabel(d.typical.storey_range)}, with ${Math.round(d.typical.remaining_lease_years)} years left. It’s worth about ${money(d.typical.estimate)}.`;
    const maxEffect = Math.max(1, ...d.drivers.map((x) => Math.abs(x.effect)));
    const drivers = h(
      "article",
      { class: "card" },
      h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "What changes the price"), h("p", { class: "sub" }, typicalLine))),
      d.drivers.length
        ? d.drivers.map((x) =>
            h(
              "div",
              { class: "driver" },
              h("div", {}, h("div", { style: { fontWeight: 600 } }, x.label), h("div", { class: "small" }, `${x.yours.replace("storey ", "Storey ")} vs ${x.typical}`)),
              h("div", { class: "driver__bar", "aria-hidden": "true" }, h("i", { class: x.effect >= 0 ? "pos" : "neg", style: { width: `${(Math.abs(x.effect) / maxEffect) * 50}%` } })),
              h("div", { class: "driver__val" }, `${x.effect >= 0 ? "+" : "-"}${money(Math.abs(x.effect))}`),
            ),
          )
        : h("p", { class: "sub" }, "Your flat matches the typical one. Change the size, storey or lease to see what each is worth."),
      h("div", { class: "card__foot" }, "Each line shows the difference that one detail makes compared with the typical flat. They overlap a little, so they won’t add up exactly."),
    );
    fill(result, summary, drivers);

    fill(
      compsSlot,
      h(
        "article",
        { class: "card" },
        h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "Closest recent sales"), h("p", { class: "sub" }, "Same town and flat type, sold in the last two years. Closest match first."))),
        d.comparables.length
          ? table(
              [
                { key: "block", label: "Address", primary: true, format: (v, row) => `Blk ${v} ${titleCase(row.street_name)}` },
                { key: "month", label: "Sold", format: monthLabel },
                { key: "resale_price", label: "Price", align: "right", format: money },
                { key: "storey_range", label: "Storey", format: storeyLabel },
                { key: "floor_area_sqm", label: "Size", align: "right", format: (v) => `${int(v)} sqm` },
                { key: "remaining_lease_years", label: "Lease left", align: "right", format: (v) => `${Math.round(v)} years` },
                { key: "price_per_sqm", label: "Per sqm", align: "right", format: money },
                { key: "similarity", label: "Match", align: "right", format: (v) => h("span", { class: "badge" }, `${int(v)}%`) },
              ],
              d.comparables,
              { stack: true },
            )
          : h("div", { class: "empty" }, h("h3", {}, "No close matches"), "No flats of this type were sold in this town in the last two years."),
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
        tooltip: (i) => tooltipHtml(imp[i].label, [{ color: C.s1, value: `${imp[i].share_pct.toFixed(1)}%`, label: "of the effect on price" }]),
      }),
    );
    importance.refreshTable();

    const acc = d.accuracy;
    fill(
      accuracySlot,
      h(
        "article",
        { class: "card" },
        h("h3", { class: "h3" }, "How accurate is it?"),
        h("p", { class: "sub" }, `We tested it on ${int(acc.holdout_rows)} flats sold from ${monthLabel(acc.holdout_period[0])} to ${monthLabel(acc.holdout_period[1])}. The model had not seen any of them.`),
        h(
          "ul",
          { class: "breakdown mt-16" },
          h("li", {}, h("span", {}, "Typical miss"), h("b", {}, `${acc.median_ape.toFixed(1)}%`)),
          h("li", {}, h("span", {}, "Estimates within 10% of the real price"), h("b", {}, `${acc.within_10pct.toFixed(0)}%`)),
          h("li", {}, h("span", {}, "Average miss, this model"), h("b", {}, `${acc.mape.toFixed(1)}%`)),
          h("li", {}, h("span", {}, "Average miss, price per sqm times size"), h("b", {}, `${acc.baseline_mape.toFixed(1)}%`)),
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

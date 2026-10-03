import { api } from "../api.js";
import { C, chartCard, mount, rankedBarsOption, tooltipHtml, tableView } from "../charts.js";
import { callout, errorBanner, fill, h, iconSvg, moneyInput, nextStep, numberInput, select, skeleton, statusPill, table } from "../dom.js";
import { flatTypeLabel, int, isNum, metresLabel, money, moneyRange, monthLabel, pct, storeyLabel, streetLabel, titleCase, walkLabel } from "../format.js";
import { chipGroup, townField } from "../picker.js";
import { createPlaceMap } from "../placemap.js";
import { state, update } from "../state.js";

const NEARBY_ICONS = { train: "train", bus: "bus", school: "school", shop: "shop", park: "park" };

export async function render(root, { meta }) {
  const valueTypes = meta.common_flat_types;
  const flat = {
    town: meta.towns.includes(state.town) ? state.town : "TAMPINES",
    flat_type: valueTypes.includes(state.flatType) ? state.flatType : "4 ROOM",
    street_name: null,
    block: null,
    floor_area: null,
    storey_range: null,
    remaining_lease: null,
    flat_model: null,
    asking_price: state.askingPrice,
  };
  let typical = null;
  let streets = [];
  let importanceRows = [];

  // Deep links: #/value?town=TAMPINES&type=4%20ROOM&street=TAMPINES%20ST%2011&block=101&area=95&storey=10%20TO%2012&lease=72&ask=690000
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const fromLink = params.has("area") || params.has("ask") || params.has("block");
  if (params.get("town") && meta.towns.includes(params.get("town").toUpperCase())) flat.town = params.get("town").toUpperCase();
  if (params.get("type") && valueTypes.includes(params.get("type").toUpperCase())) flat.flat_type = params.get("type").toUpperCase();
  const linked = {
    floor_area: Number(params.get("area")) || null,
    storey_range: meta.storey_ranges.includes((params.get("storey") || "").toUpperCase()) ? params.get("storey").toUpperCase() : null,
    remaining_lease: Number(params.get("lease")) || null,
    flat_model: params.get("model") ? params.get("model").toUpperCase() : null,
  };
  if (params.get("ask")) flat.asking_price = Number(params.get("ask")) || null;
  // The block chosen last time is kept, as long as the town still matches.
  const remembered = params.get("block") ? { town: flat.town, street_name: (params.get("street") || "").toUpperCase(), block: params.get("block").toUpperCase() } : state.address;
  if (meta.has_location && remembered && remembered.town === flat.town && remembered.street_name && remembered.block) {
    flat.street_name = remembered.street_name;
    flat.block = remembered.block;
  }

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 4 · Fair value"),
      h("h1", { class: "page-title" }, "Is the asking price fair?"),
      h(
        "p",
        { class: "lede" },
        meta.has_location
          ? "Describe the flat. We’ll estimate what it would sell for today, show what’s within walking distance and list the closest recent sales."
          : "Describe the flat. We’ll estimate what it would sell for today and show the closest recent sales.",
      ),
    ),
  );

  const form = h("div", { class: "card stack" }, skeleton(420));
  const result = h("div", { class: "stack fade-on-load" }, skeleton(300), skeleton(260));
  root.append(h("section", { class: "wrap section" }, h("div", { class: "grid grid--side" }, h("div", { class: "side-sticky" }, form), result)));

  // ------------------------------------------------------------ location
  const nearbySlot = h("div", {}, skeleton(420));
  const hoverRow = (index) => {
    for (const row of compsSlot.querySelectorAll("tbody tr")) row.classList.toggle("is-hot", Number(row.dataset.sale) === index);
  };
  const placeMap = meta.has_location ? createPlaceMap({ onSaleHover: hoverRow }) : null;
  const mapNote = h("p", { class: "small", style: { margin: "10px 0 0" } });
  if (placeMap) {
    root.append(
      h(
        "div",
        { class: "band band--teal" },
        h(
          "section",
          { class: "wrap section" },
          h("div", { class: "section-head" }, h("div", {}, h("p", { class: "eyebrow" }, "Location"), h("h2", { class: "h2" }, "What’s within walking distance"))),
          h(
            "div",
            { class: "grid grid--wide-right" },
            nearbySlot,
            h("article", { class: "card" }, placeMap.el, placeMap.legend, mapNote),
          ),
        ),
      ),
    );
  }

  const compsSlot = h("div", {}, skeleton(320));
  const importance = chartCard({
    title: "What matters most to price",
    sub: "How much each detail affects the estimate, across all flats.",
    height: 300,
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

  // ------------------------------------------------------------ form
  async function loadStreets() {
    if (!meta.has_location) return;
    try {
      streets = (await api("blocks", { town: flat.town })).streets;
    } catch {
      streets = [];
    }
    // A remembered block that this town does not have is dropped quietly.
    const street = streets.find((s) => s.street_name === flat.street_name);
    if (!street) flat.street_name = flat.block = null;
    else if (!street.blocks.some((b) => b.block === flat.block)) flat.block = null;
  }

  async function loadTypical(resetFields) {
    try {
      typical = await api("fair-value/typical", { town: flat.town, flat_type: flat.flat_type, block: flat.block ? flat.block : null, street_name: flat.block ? flat.street_name : null });
    } catch (error) {
      fill(form, errorBanner(error.message));
      return false;
    }
    if (resetFields || flat.floor_area == null) {
      flat.floor_area = typical.floor_area_sqm;
      flat.storey_range = typical.storey_range;
      flat.remaining_lease = typical.remaining_lease_years;
      flat.flat_model = typical.flat_model;
      // What is known about the chosen block beats the town's typical flat.
      const known = typical.prefill;
      if (known) {
        flat.remaining_lease = known.remaining_lease_years;
        if (known.floor_area_sqm) flat.floor_area = known.floor_area_sqm;
        if (known.flat_model) flat.flat_model = known.flat_model;
      }
    } else if (!typical.flat_models.includes(flat.flat_model)) {
      flat.flat_model = typical.flat_model;
    }
    drawForm();
    return true;
  }

  function addressFields() {
    if (!meta.has_location || !streets.length) return null;
    const street = streets.find((s) => s.street_name === flat.street_name);
    const blocks = street ? street.blocks : [];
    return [
      select({
        id: "v-street",
        label: "Street (optional)",
        options: [["", "Any street"], ...streets.map((s) => [s.street_name, s.label])],
        value: flat.street_name || "",
        onChange: (v) => {
          flat.street_name = v || null;
          flat.block = null;
          rememberAddress();
          refresh(true);
        },
      }),
      h(
        "label",
        { class: "field", for: "v-block" },
        h("span", {}, "Block"),
        h(
          "select",
          {
            class: "select",
            id: "v-block",
            disabled: !street,
            onchange: (e) => {
              flat.block = e.target.value || null;
              rememberAddress();
              refresh(true);
            },
          },
          h("option", { value: "", selected: !flat.block }, street ? "Choose a block" : "Pick a street first"),
          blocks.map((b) => h("option", { value: b.block, selected: b.block === flat.block }, `Blk ${b.block}`)),
        ),
        h("span", { class: "hint" }, flat.block ? "Lease and location are filled in from this block." : "Adds the block’s location and lease to the estimate."),
      ),
    ];
  }

  function rememberAddress() {
    update({ address: flat.block ? { town: flat.town, street_name: flat.street_name, block: flat.block } : null });
  }

  function drawForm() {
    const storeys = meta.storey_ranges.map((s) => [s, `Storey ${storeyLabel(s)}`]);
    const known = typical?.prefill;
    fill(
      form,
      h("h2", { class: "h3" }, "The flat"),
      townField({
        id: "v-town",
        value: flat.town,
        getFlatType: () => flat.flat_type,
        onChange: async (v) => {
          flat.town = v;
          flat.street_name = flat.block = null;
          update({ town: v, address: null });
          await loadStreets();
          refresh(true);
        },
      }),
      addressFields(),
      chipGroup({
        label: "Flat type",
        options: valueTypes.map((t) => [t, flatTypeLabel(t)]),
        value: flat.flat_type,
        onChange: (v) => {
          flat.flat_type = v;
          update({ flatType: v });
          refresh(true);
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
        hint: known ? `From ${known.label}’s lease` : typical ? `Recent sales here had ${Math.round(typical.lease_range[0])} to ${Math.round(typical.lease_range[1])} years left` : null,
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
      typical
        ? h(
            "p",
            { class: "hint" },
            known && known.sales_of_type
              ? `Filled in from ${flatTypeLabel(flat.flat_type).toLowerCase()} flats sold in ${known.label}. Change anything to match yours.`
              : `Filled in with a typical ${flatTypeLabel(flat.flat_type).toLowerCase()} flat in ${titleCase(flat.town)}. Change anything to match yours.`,
          )
        : null,
    );
  }

  function set(patch) {
    Object.assign(flat, patch);
    if ("asking_price" in patch) update({ askingPrice: flat.asking_price });
    estimate();
  }

  /** Town, flat type or block changed: refill the form, then re-estimate. */
  async function refresh(resetFields) {
    if (await loadTypical(resetFields)) estimate();
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
        block: flat.block ? flat.block : null,
        street_name: flat.block ? flat.street_name : null,
      });
      if (mine !== token) return;
      draw(data);
    } catch (error) {
      if (mine === token) fill(result, errorBanner(error.message));
    } finally {
      if (mine === token) result.classList.remove("is-loading");
    }
  }

  // ------------------------------------------------------------ results
  function draw(d) {
    const [low, high] = d.range;
    const cmp = d.comparison;
    const f = d.flat;
    const place = d.location;

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
        `${place ? `${place.block.label}, ` : ""}${titleCase(f.town)}, ${flatTypeLabel(f.flat_type).toLowerCase()}, ${int(f.floor_area_sqm)} sqm, storey ${storeyLabel(f.storey_range)}, ${Math.round(f.remaining_lease_years)} years left, ${titleCase(f.flat_model)}.`,
        d.location_in_model && !place ? ` No block chosen, so this assumes a typical spot in ${titleCase(f.town)}.` : "",
      ),
    );

    const typicalLine = `A typical ${flatTypeLabel(d.typical.flat_type).toLowerCase()} flat in ${titleCase(d.typical.town)} is ${int(d.typical.floor_area_sqm)} sqm, storey ${storeyLabel(d.typical.storey_range)}, with ${Math.round(d.typical.remaining_lease_years)} years left. It’s worth about ${money(d.typical.estimate)}.`;
    const shown = d.drivers.filter((x) => x.effect !== 0);
    const maxEffect = Math.max(1, ...shown.map((x) => Math.abs(x.effect)));
    const drivers = h(
      "article",
      { class: "card" },
      h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "What changes the price"), h("p", { class: "sub" }, typicalLine))),
      shown.length
        ? shown.map((x) =>
            h(
              "div",
              { class: "driver" },
              h("div", {}, h("div", { style: { fontWeight: 700 } }, x.label), h("div", { class: "small" }, `${x.yours.replace("storey ", "Storey ")} vs ${x.typical}`)),
              h("div", { class: "driver__bar", "aria-hidden": "true" }, h("i", { class: x.effect >= 0 ? "pos" : "neg", style: { width: `${(Math.abs(x.effect) / maxEffect) * 50}%` } })),
              h("div", { class: "driver__val" }, `${x.effect >= 0 ? "+" : "-"}${money(Math.abs(x.effect))}`),
            ),
          )
        : h("p", { class: "sub" }, "Your flat matches the typical one. Change the size, storey or lease to see what each is worth."),
      h("div", { class: "card__foot" }, "Each line shows the difference that one detail makes compared with the typical flat. They overlap a little, so they won’t add up exactly."),
    );
    fill(result, summary, drivers);

    drawLocation(d);
    drawComparables(d);

    importanceRows = d.importance;
    const imp = d.importance.filter((x) => x.share_pct >= 0.3);
    importance.chartEl.style.height = `${Math.max(260, imp.length * 30 + 12)}px`;
    mount(
      importance.chartEl,
      rankedBarsOption({
        names: imp.map((x) => x.label),
        values: imp.map((x) => x.share_pct),
        format: (v) => `${v.toFixed(v < 1 ? 1 : 0)}%`,
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
          isNum(acc.flat_only_median_ape) && d.location_in_model ? h("li", {}, h("span", {}, "Typical miss without location"), h("b", {}, `${acc.flat_only_median_ape.toFixed(1)}%`)) : null,
          h("li", {}, h("span", {}, "Estimates within 10% of the real price"), h("b", {}, `${acc.within_10pct.toFixed(0)}%`)),
          h("li", {}, h("span", {}, "Average miss, this model"), h("b", {}, `${acc.mape.toFixed(1)}%`)),
          h("li", {}, h("span", {}, "Average miss, price per sqm times size"), h("b", {}, `${acc.baseline_mape.toFixed(1)}%`)),
        ),
      ),
    );
  }

  function drawLocation(d) {
    if (!placeMap) return;
    const place = d.location;
    const sales = d.comparables.map((row) => ({
      lat: row.latitude,
      lon: row.longitude,
      label: `Blk ${row.block} ${streetLabel(row.street_name)}`,
      detail: `${money(row.resale_price)}, sold ${monthLabel(row.month)}`,
    }));
    placeMap.show({
      home: place ? { lat: place.block.lat, lon: place.block.lon, label: place.block.label, approximate: place.block.approximate } : null,
      rings: place?.rings,
      markers: place?.markers,
      connectors: place?.connectors,
      sales,
    });

    if (!place) {
      mapNote.textContent = "The numbered pins are the closest recent sales listed below.";
      fill(
        nearbySlot,
        h(
          "article",
          { class: "card" },
          h("h3", { class: "h3" }, "Choose the block to see what’s nearby"),
          h("p", { class: "sub" }, `Pick the street and block in the form. You’ll see the walk to the MRT, bus stops, schools, shops and parks, and the estimate will use that block’s location.`),
          h("p", { class: "sub mt-16" }, `For now the estimate assumes a typical spot in ${titleCase(d.flat.town)}, and the map shows where the closest recent sales are.`),
        ),
      );
      return;
    }
    const walk = place.walk;
    mapNote.textContent = `Walking times are estimates. We take the straight-line distance, add ${Math.round((walk.detour_factor - 1) * 100)}% for the real route and assume ${walk.speed_m_per_min} m a minute. Hover a place in the list to see its line on the map.`;
    fill(
      nearbySlot,
      h(
        "article",
        { class: "card" },
        h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, `Near ${place.block.label}`), h("p", { class: "sub" }, place.block.approximate ? "This block’s position is approximate." : "Estimated walking time from the block."))),
        h(
          "ul",
          { class: "nearby" },
          place.groups.map((group) =>
            h(
              "li",
              {},
              h("span", { class: "nearby__icon", "aria-hidden": "true" }, iconSvg(NEARBY_ICONS[group.key] || "home")),
              h(
                "div",
                {},
                h("div", { class: "nearby__label" }, group.label),
                group.items.map((item) =>
                  h(
                    "div",
                    {
                      class: "nearby__row",
                      tabindex: isNum(item.lat) ? "0" : null,
                      onmouseenter: () => placeMap.focusPlace(item),
                      onfocus: () => placeMap.focusPlace(item),
                      onmouseleave: () => placeMap.focusPlace(null),
                      onblur: () => placeMap.focusPlace(null),
                    },
                    h("b", {}, item.name, item.kind && !item.name.includes(item.kind) && item.kind !== "Park connector" && item.kind !== "Primary" ? h("small", {}, ` ${item.kind}`) : null),
                    h("span", {}, walkLabel(item.minutes), h("small", {}, ` ${metresLabel(item.metres)}`)),
                  ),
                ),
                group.note ? h("p", { class: "nearby__note" }, group.note) : null,
              ),
            ),
          ),
        ),
      ),
    );
  }

  function drawComparables(d) {
    const located = d.comparables.some((row) => isNum(row.latitude));
    const withDistance = d.comparables.some((row) => isNum(row.distance_m));
    const withTrain = d.comparables.some((row) => isNum(row.train_minutes));
    const columns = [
      {
        key: "block",
        label: "Address",
        primary: true,
        format: (v, row) => h("span", { class: "flex", style: { gap: "10px" } }, placeMap && located ? h("span", { class: "pin pin--sale", "aria-hidden": "true" }, String(d.comparables.indexOf(row) + 1)) : null, `Blk ${v} ${streetLabel(row.street_name)}`),
      },
      { key: "month", label: "Sold", format: monthLabel },
      { key: "resale_price", label: "Price", align: "right", format: money },
      { key: "storey_range", label: "Storey", format: storeyLabel },
      { key: "floor_area_sqm", label: "Size", align: "right", format: (v) => `${int(v)} sqm` },
      { key: "remaining_lease_years", label: "Lease left", align: "right", format: (v) => `${Math.round(v)} years` },
      { key: "price_per_sqm", label: "Per sqm", align: "right", format: money },
      withTrain ? { key: "train_minutes", label: "Walk to train", align: "right", format: (v) => (isNum(v) ? `${v} min` : "n/a") } : null,
      withDistance ? { key: "distance_m", label: "From your block", align: "right", format: (v) => (isNum(v) ? (v < 15 ? "Same block" : metresLabel(v)) : "n/a") } : null,
      { key: "similarity", label: "Match", align: "right", format: (v) => h("span", { class: "badge" }, `${int(v)}%`) },
    ].filter(Boolean);
    fill(
      compsSlot,
      h(
        "article",
        { class: "card" },
        h(
          "div",
          { class: "card__head" },
          h(
            "div",
            {},
            h("h3", { class: "h3" }, "Closest recent sales"),
            h(
              "p",
              { class: "sub" },
              withDistance
                ? "Same town and flat type, sold in the last two years. Sales nearer your block count as a closer match."
                : "Same town and flat type, sold in the last two years. Closest match first.",
              placeMap && located ? " The numbers match the pins on the map." : "",
            ),
          ),
        ),
        d.comparables.length
          ? table(columns, d.comparables, {
              stack: true,
              rowAttrs: (row, i) => ({ "data-sale": i, onmouseenter: () => placeMap?.highlightSale(i), onmouseleave: () => placeMap?.highlightSale(null) }),
            })
          : h("div", { class: "empty" }, h("h3", {}, "No close matches"), "No flats of this type were sold in this town in the last two years."),
      ),
    );
  }

  await loadStreets();
  if (await loadTypical(false)) {
    if (fromLink) {
      for (const [key, value] of Object.entries(linked)) if (value) flat[key] = value;
      drawForm();
    }
    await estimate();
  }
}

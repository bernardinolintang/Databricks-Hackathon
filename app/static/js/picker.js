// Town and flat-type controls.
//   townField()      a form field that opens the map picker
//   openTownPicker() the picker itself: map on one side, towns by region on the other
//   chipGroup()      one-tap choice chips (used for flat type)
// The picker is a centred dialog on wide screens and a bottom sheet on phones.

import { h, iconSvg } from "./dom.js";
import { flatTypeLabel, moneyShort, titleCase } from "./format.js";
import { createTownMap, loadMap, loadTownStats, mapCaption } from "./townmap.js";

const PIN = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 18s5.5-5.2 5.5-9.6A5.5 5.5 0 0 0 4.5 8.4C4.5 12.8 10 18 10 18z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><circle cx="10" cy="8.3" r="2" fill="currentColor"/></svg>';
const REGION_ORDER = ["NORTH REGION", "NORTH-EAST REGION", "EAST REGION", "CENTRAL REGION", "WEST REGION"];

function townName(value, allLabel) {
  return !value || value === "ALL" ? allLabel : titleCase(value);
}

/**
 * A field that shows the chosen town and opens the map picker.
 * `enabled` (optional array) limits which towns can be picked.
 */
export function townField({ id, label = "Town", value, allowAll = false, allLabel = "All towns", getFlatType, enabled, onChange, grow = false }) {
  const text = h("span", { class: "townfield__text" }, townName(value, allLabel));
  const button = h(
    "button",
    {
      class: "select townfield",
      type: "button",
      id,
      "aria-haspopup": "dialog",
      onclick: async () => {
        const chosen = await openTownPicker({
          title: "Choose a town",
          selected: value && value !== "ALL" ? [value] : [],
          allowAll,
          allLabel,
          enabled,
          flatType: getFlatType?.(),
        });
        if (chosen === undefined) return;
        value = chosen;
        text.textContent = townName(value, allLabel);
        onChange(value);
      },
    },
    h("span", { class: "townfield__pin", html: PIN }),
    text,
  );
  return h("div", { class: `field${grow ? " field--grow" : ""}` }, h("label", { for: id }, label), button);
}

/** One-tap choice chips, e.g. flat type. Behaves as a radio group. */
export function chipGroup({ label, options, value, onChange }) {
  const group = h("div", { class: "chips", role: "radiogroup", "aria-label": label });
  for (const [val, text] of options) {
    const chip = h(
      "button",
      {
        type: "button",
        class: "chip",
        role: "radio",
        "aria-checked": String(val === value),
        tabindex: val === value ? "0" : "-1",
        onclick: () => {
          if (val === value) return;
          value = val;
          for (const other of group.children) {
            const on = other === chip;
            other.setAttribute("aria-checked", String(on));
            other.tabIndex = on ? 0 : -1;
          }
          onChange(val);
        },
      },
      text,
    );
    group.append(chip);
  }
  group.addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const chips = [...group.children];
    const next = chips[(chips.indexOf(document.activeElement) + (e.key === "ArrowRight" ? 1 : -1) + chips.length) % chips.length];
    next.focus();
    next.click();
    e.preventDefault();
  });
  // The chips wrap, so the chosen one is always on screen. (This used to call
  // scrollIntoView on it, which also scrolled the page down on load.)
  return h("div", { class: "field field--chips" }, h("span", {}, label), group);
}

/**
 * Open the picker. Resolves to:
 *   single mode  the chosen town, "ALL", or undefined if dismissed
 *   multi mode   the array of chosen towns, or undefined if dismissed
 */
export async function openTownPicker({ title, selected = [], multi = false, max = 3, allowAll = false, allLabel = "All towns", enabled, flatType, colors, colorFor }) {
  const [map, stats] = await Promise.all([loadMap(), loadTownStats(flatType)]);
  const enabledSet = enabled ? new Set(enabled) : null;
  let chosen = [...selected];
  const trigger = document.activeElement;

  return new Promise((resolve) => {
    const byTown = new Map(stats.towns.map((r) => [r.town, r]));
    const regions = new Map();
    const shapes = map.available ? map.towns : [];
    const regionOf = new Map(shapes.map((t) => [t.town, t.region]));
    const allTowns = shapes.length ? shapes.map((t) => t.town) : stats.towns.map((r) => r.town);
    for (const town of allTowns.sort()) {
      const region = regionOf.get(town) || "TOWNS";
      regions.set(region, [...(regions.get(region) || []), town]);
    }

    const count = h("span", { class: "modal__count" });
    const done = h("button", { class: "btn btn--primary btn--small", type: "button", onclick: () => close(chosen) }, "Done");
    const listEl = h("div", { class: "townlist" });
    const colorOf = (town) => (colorFor ? colorFor(town, chosen) : colors?.[town]);

    const townMap = map.available
      ? createTownMap({ map, animate: false, onSelect: toggle, label: "Map of Singapore. Choose a town." })
      : null;

    function refresh() {
      const ringColors = Object.fromEntries(chosen.map((t) => [t, colorOf(t) || "#c3141e"]));
      townMap?.update({ stats, selected: chosen, colors: ringColors, enabled: enabledSet });
      for (const button of listEl.querySelectorAll("[data-town]")) {
        const on = chosen.includes(button.dataset.town);
        button.setAttribute("aria-pressed", String(on));
        button.style.setProperty("--ring", ringColors[button.dataset.town] || "transparent");
      }
      if (multi) {
        count.textContent = `${chosen.length} of ${max} chosen`;
        done.disabled = chosen.length === 0;
      }
    }

    function toggle(town) {
      if (enabledSet && !enabledSet.has(town)) return;
      if (!multi) return close(town);
      if (chosen.includes(town)) chosen = chosen.filter((t) => t !== town);
      else if (chosen.length < max) chosen = [...chosen, town];
      else {
        count.textContent = `Up to ${max} towns. Remove one first.`;
        return;
      }
      refresh();
    }

    if (allowAll) {
      listEl.append(h("button", { class: "townlist__all", type: "button", onclick: () => close("ALL") }, allLabel));
    }
    const ordered = [...regions.keys()].sort((a, b) => (REGION_ORDER.indexOf(a) + 99) % 99 - (REGION_ORDER.indexOf(b) + 99) % 99);
    for (const region of ordered) {
      listEl.append(h("h4", { class: "townlist__region" }, region === "TOWNS" ? "Towns" : titleCase(region.replace(" REGION", ""))));
      const grid = h("div", { class: "townlist__grid" });
      for (const town of regions.get(region)) {
        const row = byTown.get(town);
        const off = enabledSet && !enabledSet.has(town);
        grid.append(
          h(
            "button",
            { class: "townlist__item", type: "button", "data-town": town, disabled: off, "aria-pressed": "false", onclick: () => toggle(town) },
            h("span", { class: "townlist__name" }, titleCase(town)),
            h("span", { class: "townlist__price" }, off ? "n/a" : row?.median_price_12m != null ? moneyShort(row.median_price_12m) : "n/a"),
          ),
        );
      }
      listEl.append(grid);
    }

    const closeButton = h("button", { class: "sheet__close modal__close", type: "button", "aria-label": "Close", onclick: () => close(undefined) }, iconSvg("close"));
    const panel = h(
      "div",
      { class: "modal__panel", role: "dialog", "aria-modal": "true", "aria-labelledby": "picker-title" },
      h(
        "header",
        { class: "modal__head" },
        h("div", {}, h("h2", { class: "h2", id: "picker-title" }, title), h("p", { class: "sub" }, multi ? `Pick up to ${max}. ` : "", map.available ? mapCaption(stats, flatType) : `Median ${flatTypeLabel(stats.flat_type).toLowerCase()} price, ${stats.window_label}.`)),
        closeButton,
      ),
      h("div", { class: `modal__body${townMap ? "" : " modal__body--list"}` }, townMap ? h("div", { class: "modal__map" }, townMap.el) : null, listEl),
      multi ? h("footer", { class: "modal__foot" }, count, done) : null,
    );
    const modal = h("div", { class: "modal" }, h("div", { class: "modal__backdrop", onclick: () => close(undefined) }), panel);

    function onKey(e) {
      if (e.key === "Escape") close(undefined);
      if (e.key !== "Tab") return;
      // Keep focus inside the dialog.
      const focusable = [...panel.querySelectorAll("button:not([disabled]), [tabindex='0']")].filter((el) => el.offsetParent !== null || el.ownerSVGElement);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    }

    function close(result) {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("has-modal");
      modal.remove();
      trigger?.focus?.();
      resolve(result);
    }

    document.addEventListener("keydown", onKey);
    document.body.classList.add("has-modal");
    document.body.append(modal);
    refresh();
    closeButton.focus();
  });
}

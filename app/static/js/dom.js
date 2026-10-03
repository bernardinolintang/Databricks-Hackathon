// Tiny DOM helpers. Text always goes in through textContent, never innerHTML,
// because town names and other labels come from data.

import { deltaClass, pct } from "./format.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") {
      // Custom properties ("--accent") only apply through setProperty.
      for (const [prop, val] of Object.entries(value)) {
        if (val === null || val === undefined) continue;
        if (prop.startsWith("--")) el.style.setProperty(prop, val);
        else el.style[prop] = val;
      }
    }
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "html") el.innerHTML = value; // only for trusted static markup (icons)
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** Replace an element's children, skipping null/false like h() does. */
export function fill(el, ...children) {
  clear(el);
  append(el, children);
  return el;
}

const ICONS = {
  arrow: '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1.5 9 7H1z" fill="currentColor"/></svg>',
  check: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.25" fill="currentColor"/><path d="m4.8 8.2 2.1 2.1 4.3-4.4" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  alert: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.25" fill="currentColor"/><path d="M8 4.3v4.4" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/><circle cx="8" cy="11.3" r="1" fill="#fff"/></svg>',
  cross: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.25" fill="currentColor"/><path d="m5.4 5.4 5.2 5.2m0-5.2-5.2 5.2" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>',
  info: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10 9v5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="10" cy="6.3" r="1" fill="currentColor"/></svg>',
  shield: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2 3.5 4.6v4.6c0 4 2.8 7.4 6.5 8.8 3.7-1.4 6.5-4.8 6.5-8.8V4.6z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="m7 10 2.1 2.1L13.3 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  close: '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  dot: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.25" fill="currentColor"/><circle cx="8" cy="8" r="2.5" fill="#fff"/></svg>',
};

export function icon(name) {
  return h("span", { class: `icon icon--${name}`, html: ICONS[name], style: { display: "inline-flex" } });
}

export function iconSvg(name) {
  const tpl = document.createElement("template");
  tpl.innerHTML = ICONS[name];
  return tpl.content.firstChild;
}

/** Signed change with a direction glyph. Colour marks direction only, never good/bad. */
export function delta(value, { digits = 1, suffix = "" } = {}) {
  const cls = deltaClass(value);
  return h("span", { class: `delta delta--${cls}` }, cls === "flat" ? null : iconSvg("arrow"), `${pct(value, digits)}${suffix}`);
}

export function statTile({ label, value, meta, title }) {
  return h(
    "div",
    { class: "tile", title },
    h("div", { class: "tile__label" }, label),
    h("div", { class: "tile__value" }, value),
    meta ? h("div", { class: "tile__meta" }, meta) : null,
  );
}

export function select({ id, label, options, value, onChange, grow = false, labelHidden = false }) {
  const control = h(
    "select",
    { class: "select", id, onchange: (e) => onChange(e.target.value) },
    options.map((opt) => {
      const [val, text] = Array.isArray(opt) ? opt : [opt, opt];
      return h("option", { value: val, selected: String(val) === String(value) }, text);
    }),
  );
  return h("label", { class: `field${grow ? " field--grow" : ""}`, for: id }, h("span", { class: labelHidden ? "sr-only" : null }, label), control);
}

export function moneyInput({ id, label, value, onChange, hint, placeholder, step = 1000, suffix }) {
  const input = h("input", {
    class: "input num",
    id,
    type: "number",
    inputmode: "numeric",
    min: 0,
    step,
    value: value ?? "",
    placeholder: placeholder || "",
  });
  input.addEventListener("change", () => onChange(input.value === "" ? null : Number(input.value)));
  const wrapped = suffix
    ? h("div", { class: "input-suffix" }, input, h("b", {}, suffix))
    : h("div", { class: "input-prefix" }, h("b", {}, "$"), input);
  return h("label", { class: "field", for: id }, h("span", {}, label), wrapped, hint ? h("span", { class: "hint" }, hint) : null);
}

export function numberInput({ id, label, value, onChange, hint, step = 1, min = 0, max, suffix }) {
  const input = h("input", { class: "input num", id, type: "number", inputmode: "decimal", min, max, step, value: value ?? "" });
  input.addEventListener("change", () => onChange(input.value === "" ? null : Number(input.value)));
  return h(
    "label",
    { class: "field", for: id },
    h("span", {}, label),
    suffix ? h("div", { class: "input-suffix" }, input, h("b", {}, suffix)) : input,
    hint ? h("span", { class: "hint" }, hint) : null,
  );
}

export function segmented(options, value, onChange, label) {
  const group = h("div", { class: "segmented", role: "group", "aria-label": label });
  for (const [val, text] of options) {
    group.append(
      h(
        "button",
        {
          type: "button",
          "aria-pressed": String(val === value),
          onclick: () => {
            for (const b of group.querySelectorAll("button")) b.setAttribute("aria-pressed", "false");
            group.querySelector(`[data-val="${CSS.escape(val)}"]`).setAttribute("aria-pressed", "true");
            onChange(val);
          },
          "data-val": val,
        },
        text,
      ),
    );
  }
  return group;
}

export function statusPill(status, label) {
  const map = { comfortable: ["good", "check"], stretch: ["warn", "alert"], over: ["bad", "cross"], below: ["neutral", "dot"], within: ["neutral", "dot"], above: ["neutral", "dot"] };
  const [tone, glyph] = map[status] || ["neutral", "dot"];
  return h("span", { class: `status status--${tone}` }, iconSvg(glyph), label);
}

export function callout(text, { tone = "", glyph = "info" } = {}) {
  return h("div", { class: `callout${tone ? ` callout--${tone}` : ""}` }, iconSvg(glyph), h("div", {}, text));
}

export function nextStep({ title, body, href, cta }) {
  return h(
    "section",
    { class: "wrap section" },
    h("div", { class: "next-step" }, h("div", {}, h("h3", {}, title), h("p", {}, body)), h("a", { class: "btn btn--primary", href }, cta)),
  );
}

export function skeleton(height, extra = {}) {
  return h("div", { class: "skeleton", style: { height: `${height}px`, ...extra }, "aria-hidden": "true" });
}

export function errorBanner(message) {
  return h("div", { class: "error-banner", role: "alert" }, message);
}

let toastTimer;
export function toast(message) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: "toast", role: "status" }, message);
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 4200);
}

export function table(columns, rows, { selectedKey, keyOf, stack = false } = {}) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: `table${stack ? " table--stack" : ""}` },
      h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.align === "right" ? "r" : null, scope: "col" }, c.label)))),
      h(
        "tbody",
        {},
        rows.map((row) =>
          h(
            "tr",
            { class: keyOf && selectedKey && keyOf(row) === selectedKey ? "is-selected" : null },
            columns.map((c) => h("td", { class: c.align === "right" ? "r" : null, "data-label": c.label, "data-primary": c.primary ? "" : null }, c.format ? c.format(row[c.key], row) : row[c.key] ?? "n/a")),
          ),
        ),
      ),
    ),
  );
}

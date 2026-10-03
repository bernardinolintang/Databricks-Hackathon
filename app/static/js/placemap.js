// Street map around one flat, drawn with Leaflet on OneMap's base map
// (Singapore Land Authority). It shows the flat, rings for a 5 and 10 minute
// walk, the places nearby, park connectors and the recent sales being compared.
// Leaflet is loaded the first time a map is needed, so other pages stay light.

import { h, iconSvg } from "./dom.js";
import { metresLabel, walkLabel } from "./format.js";

const LEAFLET_JS = "/static/vendor/leaflet/leaflet.js";
const LEAFLET_CSS = "/static/vendor/leaflet/leaflet.css";
const TILES = "https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png";
// OneMap's terms ask for this credit, logo included, on every map.
const CREDIT =
  '<img src="https://www.onemap.gov.sg/web-assets/images/logo/om_logo.png" alt="">&nbsp;<a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">OneMap</a>&nbsp;&copy;&nbsp;contributors&nbsp;&#124;&nbsp;<a href="https://www.sla.gov.sg/" target="_blank" rel="noopener noreferrer">Singapore Land Authority</a>';
const SINGAPORE = [
  [1.13, 103.56],
  [1.49, 104.14],
];
const CONNECTOR_COLOUR = "#198754";

/** The layers a visitor can switch on and off, in legend order. */
export const LAYERS = [
  { key: "train", label: "Train", icon: "train", colour: "#c3141e" },
  { key: "bus", label: "Bus stops", icon: "bus", colour: "#0a676d" },
  { key: "school", label: "Schools", icon: "school", colour: "#6f42c1" },
  { key: "shop", label: "Shops and food", icon: "shop", colour: "#b3600a" },
  { key: "park", label: "Parks", icon: "park", colour: "#198754" },
  { key: "connector", label: "Park connectors", line: true, colour: CONNECTOR_COLOUR },
  { key: "sale", label: "Recent sales", colour: "#212529" },
];
const LAYER_OF = { train: "train", bus: "bus", school: "school", mall: "shop", hawker: "shop", park: "park" };

let leaflet = null;
function loadLeaflet() {
  leaflet =
    leaflet ||
    new Promise((resolve, reject) => {
      if (window.L) return resolve(window.L);
      document.head.append(h("link", { rel: "stylesheet", href: LEAFLET_CSS }));
      const script = h("script", { src: LEAFLET_JS });
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("The map could not be loaded."));
      document.head.append(script);
    });
  leaflet.catch(() => (leaflet = null));
  return leaflet;
}

const live = new Set();
/** Tear down every map on the page; called when the page changes. */
export function disposeMaps() {
  for (const dispose of live) dispose();
  live.clear();
}

function pin(L, kind, content, size = 28) {
  const el = h("span", { class: `pin pin--${kind}` });
  if (typeof content === "string") el.textContent = content;
  else if (content) el.append(content);
  return L.divIcon({ className: "", html: el.outerHTML, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
}

function tip(title, detail) {
  const el = h("span", {}, title, detail ? h("small", {}, detail) : null);
  return el.innerHTML;
}

/**
 * createPlaceMap() -> { el, legend, show(data), focusPlace(place), highlightSale(i) }
 *   show({ home, rings, markers, connectors, sales })
 *     home        { lat, lon, label } or null (no block chosen: the map frames the sales)
 *     rings       [{ minutes, metres }]
 *     markers     [{ category, kind, name, lat, lon, metres, minutes }]
 *     connectors  [{ name, path: [[lat, lon], ...] }]
 *     sales       [{ lat, lon, label, detail }] numbered in the order given
 */
export function createPlaceMap({ onSaleHover } = {}) {
  const canvas = h("div", { class: "placemap__canvas" }, h("div", { class: "placemap__fallback" }, "Loading the map…"));
  const el = h("div", { class: "placemap" }, canvas);
  const legend = h("div", { class: "maplegend", role: "group", "aria-label": "Show on the map" });
  const hidden = new Set();
  let map = null;
  let L = null;
  let groups = {};
  let salePins = [];
  let trace = null;
  let pending = null;
  let home = null;

  function drawLegend(present) {
    legend.replaceChildren(
      ...LAYERS.filter((layer) => present.has(layer.key)).map((layer) =>
        h(
          "button",
          {
            class: "chip",
            type: "button",
            "aria-pressed": String(!hidden.has(layer.key)),
            onclick: (e) => {
              const show = hidden.has(layer.key);
              if (show) hidden.delete(layer.key);
              else hidden.add(layer.key);
              e.currentTarget.setAttribute("aria-pressed", String(show));
              const group = groups[layer.key];
              if (group && map) (show ? group.addTo(map) : group.remove());
            },
          },
          h("i", { class: layer.line ? "is-line" : null, style: { "--dot": layer.colour } }),
          layer.label,
        ),
      ),
    );
  }

  async function ensureMap() {
    if (map) return map;
    try {
      L = await loadLeaflet();
    } catch (error) {
      canvas.replaceChildren(h("div", { class: "placemap__fallback" }, "The map didn’t load. The distances beside it still apply."));
      return null;
    }
    if (!el.isConnected) return null;
    canvas.replaceChildren();
    map = L.map(canvas, { zoomControl: true, scrollWheelZoom: false, minZoom: 11, maxZoom: 19, maxBounds: SINGAPORE, maxBoundsViscosity: 0.8, attributionControl: true });
    map.attributionControl.setPrefix(false);
    L.tileLayer(TILES, { detectRetina: true, minZoom: 11, maxZoom: 19, attribution: CREDIT }).addTo(map);
    // Scrolling the page must not zoom the map by accident: click it first.
    map.on("click", () => map.scrollWheelZoom.enable());
    canvas.addEventListener("mouseleave", () => map.scrollWheelZoom.disable());
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(canvas);
    live.add(() => {
      observer.disconnect();
      map.remove();
      map = null;
    });
    return map;
  }

  async function show(data) {
    pending = data;
    if (!(await ensureMap()) || pending !== data) return;
    for (const group of Object.values(groups)) group.remove();
    trace?.remove();
    trace = null;
    groups = Object.fromEntries(LAYERS.map((layer) => [layer.key, L.layerGroup()]));
    const base = L.layerGroup();
    groups.base = base;
    salePins = [];
    home = data.home || null;
    const present = new Set();
    const frame = [];

    for (const line of data.connectors || []) {
      L.polyline(line.path, { color: CONNECTOR_COLOUR, weight: 4, opacity: 0.8, lineCap: "round" }).bindTooltip(tip("Park connector", line.name), { className: "placetip", sticky: true }).addTo(groups.connector);
      present.add("connector");
    }
    if (home) {
      for (const ring of data.rings || []) {
        L.circle([home.lat, home.lon], { radius: ring.metres, color: "#0a676d", weight: 1.5, dashArray: "5 6", fillColor: "#0c8188", fillOpacity: 0.05, interactive: false }).addTo(base);
        // Label each ring at its top edge.
        const top = home.lat + ring.metres / 110574;
        L.marker([top, home.lon], { icon: L.divIcon({ className: "", html: `<span class="ringlabel">${ring.minutes} min walk</span>`, iconSize: [0, 0], iconAnchor: [34, 9] }), interactive: false, keyboard: false }).addTo(base);
        frame.push([top, home.lon], [home.lat - ring.metres / 110574, home.lon]);
      }
    }
    for (const place of data.markers || []) {
      const layer = LAYER_OF[place.category];
      if (!layer) continue;
      present.add(layer);
      const small = place.category === "bus";
      const marker = L.marker([place.lat, place.lon], {
        icon: pin(L, place.category, iconSvg(LAYERS.find((l) => l.key === layer).icon), small ? 18 : 28),
        keyboard: false,
        zIndexOffset: small ? 0 : 200,
      }).bindTooltip(tip(place.name, `${walkLabel(place.minutes)} (${metresLabel(place.metres)})`), { className: "placetip", direction: "top", offset: [0, small ? -8 : -14] });
      marker.addTo(groups[layer]);
    }
    (data.sales || []).forEach((sale, i) => {
      if (!Number.isFinite(sale.lat) || !Number.isFinite(sale.lon)) {
        salePins.push(null);
        return;
      }
      present.add("sale");
      const marker = L.marker([sale.lat, sale.lon], { icon: pin(L, "sale", String(i + 1)), keyboard: false, zIndexOffset: 400 })
        .bindTooltip(tip(sale.label, sale.detail), { className: "placetip", direction: "top", offset: [0, -14] })
        .addTo(groups.sale);
      marker.on("mouseover", () => onSaleHover?.(i));
      marker.on("mouseout", () => onSaleHover?.(null));
      salePins.push(marker);
      frame.push([sale.lat, sale.lon]);
    });
    if (home) {
      L.marker([home.lat, home.lon], { icon: pin(L, "home", iconSvg("home"), 36), keyboard: false, zIndexOffset: 800 })
        .bindTooltip(tip(home.label, home.approximate ? "Approximate position" : "This flat"), { className: "placetip", direction: "top", offset: [0, -18] })
        .addTo(base);
      frame.push([home.lat, home.lon]);
    }

    base.addTo(map);
    for (const layer of LAYERS) if (present.has(layer.key) && !hidden.has(layer.key)) groups[layer.key].addTo(map);
    drawLegend(present);
    map.invalidateSize();
    if (frame.length) map.fitBounds(L.latLngBounds(frame).pad(0.12), { maxZoom: 17, animate: false });
  }

  /** Draw the walk from the flat to one place, and say how long it takes. */
  function focusPlace(place) {
    trace?.remove();
    trace = null;
    if (!map || !home || !place || !Number.isFinite(place.lat)) return;
    trace = L.layerGroup([
      L.polyline(
        [
          [home.lat, home.lon],
          [place.lat, place.lon],
        ],
        { color: "#212529", weight: 3, dashArray: "2 7", lineCap: "round", interactive: false },
      ),
      L.marker([(home.lat + place.lat) / 2, (home.lon + place.lon) / 2], {
        icon: L.divIcon({ className: "", html: `<span class="ringlabel">${walkLabel(place.minutes)}</span>`, iconSize: [0, 0], iconAnchor: [34, 9] }),
        interactive: false,
        keyboard: false,
      }),
    ]).addTo(map);
    const bounds = L.latLngBounds([
      [home.lat, home.lon],
      [place.lat, place.lon],
    ]);
    if (!map.getBounds().contains(bounds)) map.fitBounds(bounds.pad(0.35), { maxZoom: 17 });
  }

  function highlightSale(index) {
    salePins.forEach((marker, i) => marker?.getElement()?.querySelector(".pin")?.classList.toggle("is-hot", i === index));
  }

  return { el, legend, show, focusPlace, highlightSale };
}

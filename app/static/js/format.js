// Number, money and label formatting shared by every page.

const money0 = new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD", currencyDisplay: "narrowSymbol", maximumFractionDigits: 0 });
const int0 = new Intl.NumberFormat("en-SG", { maximumFractionDigits: 0 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const isNum = (v) => typeof v === "number" && Number.isFinite(v);

export function money(v) {
  return isNum(v) ? money0.format(v) : "–";
}

/** $638K / $1.03M, for axes and dense lists. */
export function moneyShort(v) {
  if (!isNum(v)) return "–";
  const abs = Math.abs(v);
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(abs >= 1e7 ? 1 : 2).replace(/\.?0+$/, "")}M`;
  if (abs >= 1e3) return `$${Math.round(v / 1e3)}K`;
  return `$${Math.round(v)}`;
}

export function int(v) {
  return isNum(v) ? int0.format(v) : "–";
}

export function pct(v, digits = 1, signed = true) {
  if (!isNum(v)) return "–";
  const s = v.toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function ratio(v, digits = 0) {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : "–";
}

/** "2026-09" -> "Sep 2026" */
export function monthLabel(ym) {
  if (!ym) return "–";
  const [y, m] = String(ym).split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

export function monthShort(ym) {
  const [y, m] = String(ym).split("-").map(Number);
  return `${MONTHS[m - 1]} ’${String(y).slice(2)}`;
}

/** "KALLANG/WHAMPOA" -> "Kallang/Whampoa", "4 ROOM" -> "4-room" */
export function titleCase(name) {
  if (!name) return "";
  if (name === "ALL") return "All";
  if (/^\d ROOM$/.test(name)) return `${name[0]}-room`;
  if (name === "MULTI-GENERATION") return "Multi-generation";
  const KEEP = new Set(["DBSS"]);
  return name
    .split(/([\s/-])/)
    .map((part) => {
      if (!/[A-Za-z0-9]/.test(part)) return part;
      if (KEEP.has(part) || /^[A-Z]\d?$/.test(part)) return part;
      return part[0].toUpperCase() + part.slice(1).toLowerCase();
    })
    .join("");
}

/** "07 TO 09" -> "7–9" */
export function storeyLabel(range) {
  if (!range) return "–";
  return String(range)
    .split(" TO ")
    .map((n) => String(Number(n)))
    .join("–");
}

export function flatTypeLabel(name, plural = false) {
  if (!name || name === "ALL") return plural ? "all flats" : "All flat types";
  const base = titleCase(name);
  return plural ? `${base} flats` : base;
}

export function townLabel(name) {
  return !name || name === "ALL" ? "Singapore" : titleCase(name);
}

export function deltaClass(v, flatBand = 0.5) {
  if (!isNum(v)) return "flat";
  if (Math.abs(v) < flatBand) return "flat";
  return v > 0 ? "up" : "down";
}

export function dateTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

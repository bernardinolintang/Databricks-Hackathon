// The buyer's journey state. Choosing Tampines 4-room on one page carries to
// the next, which is what turns six pages into one story. Persisted per
// browser as a convenience only; the app works without storage.

const KEY = "flatfair.journey.v1";

const defaults = {
  town: "TAMPINES",
  flatType: "4 ROOM",
  income: 9000,
  cash: 200000,
  maxRepayment: null,
  askingPrice: null,
  compareTowns: ["TAMPINES", "BEDOK", "PASIR RIS"],
};

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...defaults, ...JSON.parse(raw) } : { ...defaults };
  } catch {
    return { ...defaults };
  }
}

export const state = load();

export function update(patch) {
  Object.assign(state, patch);
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable (private mode): state still lives for this visit */
  }
}

export function reset() {
  Object.assign(state, defaults);
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

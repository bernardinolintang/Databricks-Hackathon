import { api } from "../api.js";
import { callout, errorBanner, fill, h, iconSvg, moneyInput, nextStep, numberInput, skeleton, statusPill, table } from "../dom.js";
import { flatTypeLabel, int, money, ratio, titleCase, townLabel } from "../format.js";
import { chipGroup, townField } from "../picker.js";
import { state, update } from "../state.js";

export async function render(root, { meta }) {
  const a = meta.assumptions;
  const bench = meta.income_benchmark;
  const inputs = {
    income: state.income ?? 9000,
    cash: state.cash ?? 200000,
    flat_type: meta.common_flat_types.includes(state.flatType) ? state.flatType : "4 ROOM",
    town: state.town || "ALL",
    price: null,
    max_repayment: state.maxRepayment,
    rate: a.annual_interest_rate,
    tenure: a.tenure_years,
    ltv: a.loan_to_value,
  };

  root.append(
    h(
      "section",
      { class: "wrap page-head" },
      h("p", { class: "eyebrow" }, "Step 3 · Affordability"),
      h("h1", { class: "page-title" }, "Can you afford it?"),
      h("p", { class: "lede" }, "Put in your income and savings. You’ll see the monthly repayment, the cash you need upfront, and which towns fit your budget."),
    ),
  );

  const form = h("div", { class: "card stack" });
  const results = h("div", { class: "stack fade-on-load" }, skeleton(260), skeleton(320));
  // The form only sticks beside the results on wide screens. In one column it
  // must scroll away, or the results slide over it.
  root.append(h("section", { class: "wrap section" }, h("div", { class: "grid grid--side" }, h("div", { class: "side-sticky" }, form), results)));

  const rankingSlot = h("div", {}, skeleton(420));
  root.append(
    h("section", { class: "wrap section" }, rankingSlot),
    h(
      "section",
      { class: "wrap section--tight" },
      callout("These numbers are a guide and not financial advice. They leave out housing grants, CPF rules, loan eligibility, legal and agent fees, and renovation. Check hdb.gov.sg for the latest rules before you commit."),
    ),
    nextStep({ title: "Found a flat you like?", body: "See if its asking price matches what similar flats sold for.", href: "#/value", cta: "Check a flat’s price" }),
  );

  function drawForm() {
    fill(
      form,
      h("h2", { class: "h3" }, "Your household"),
      moneyInput({
        id: "a-income",
        label: "Monthly household income",
        value: inputs.income,
        step: 100,
        hint: bench ? `Singapore median: ${money(bench.monthly_income)} (SingStat ${bench.year}, with employer CPF)` : "Total monthly income of everyone on the loan",
        onChange: (v) => change({ income: v }),
      }),
      moneyInput({ id: "a-cash", label: "Cash and CPF savings", value: inputs.cash, hint: "Goes to the downpayment and stamp duty first", onChange: (v) => change({ cash: v ?? 0 }) }),
      chipGroup({ label: "Flat type", options: meta.common_flat_types.map((t) => [t, flatTypeLabel(t)]), value: inputs.flat_type, onChange: (v) => change({ flat_type: v }) }),
      townField({ id: "a-town", value: inputs.town, allowAll: true, getFlatType: () => inputs.flat_type, onChange: (v) => change({ town: v, price: null }) }),
      moneyInput({ id: "a-price", label: "Price to check (optional)", value: inputs.price, placeholder: "Town median", onChange: (v) => change({ price: v }) }),
      moneyInput({ id: "a-cap", label: "Most you want to pay a month (optional)", value: inputs.max_repayment, step: 50, placeholder: "No limit", onChange: (v) => change({ max_repayment: v }) }),
      h(
        "details",
        { class: "advanced" },
        h("summary", {}, "Loan settings"),
        h(
          "div",
          { class: "stack mt-16" },
          numberInput({ id: "a-rate", label: "Interest rate", value: +(inputs.rate * 100).toFixed(2), step: 0.05, min: 0, max: 20, suffix: "% a year", onChange: (v) => change({ rate: v == null ? a.annual_interest_rate : v / 100 }) }),
          numberInput({ id: "a-tenure", label: "Loan period", value: inputs.tenure, step: 1, min: 5, max: 35, suffix: "years", onChange: (v) => change({ tenure: v ?? a.tenure_years }) }),
          numberInput({ id: "a-ltv", label: "Loan as a share of price", value: Math.round(inputs.ltv * 100), step: 5, min: 5, max: 100, suffix: "%", onChange: (v) => change({ ltv: v == null ? a.loan_to_value : v / 100 }) }),
          h("p", { class: "hint" }, `Set to an HDB loan by default: ${(a.annual_interest_rate * 100).toFixed(1)}% interest, ${a.tenure_years} years, borrowing up to ${Math.round(a.loan_to_value * 100)}% of the price.`),
        ),
      ),
    );
  }

  function change(patch) {
    Object.assign(inputs, patch);
    update({
      income: inputs.income,
      cash: inputs.cash,
      flatType: inputs.flat_type,
      town: inputs.town === "ALL" ? state.town : inputs.town,
      maxRepayment: inputs.max_repayment,
    });
    if ("town" in patch) drawForm();
    load();
  }

  let token = 0;
  async function load() {
    const mine = ++token;
    if (!inputs.income || inputs.income <= 0) {
      fill(results, errorBanner("Enter your monthly household income to see the numbers."));
      return;
    }
    results.classList.add("is-loading");
    try {
      const data = await api("affordability", {
        income: inputs.income,
        cash: inputs.cash ?? 0,
        flat_type: inputs.flat_type,
        town: inputs.town,
        price: inputs.price,
        max_repayment: inputs.max_repayment,
        rate: inputs.rate,
        tenure: inputs.tenure,
        ltv: inputs.ltv,
      });
      if (mine !== token) return;
      draw(data);
    } catch (error) {
      if (mine === token) fill(results, errorBanner(error.message));
    } finally {
      if (mine === token) results.classList.remove("is-loading");
    }
  }

  function draw(d) {
    const r = d.result;
    const as = d.assumptions;
    const place = townLabel(d.inputs.town);
    const what = flatTypeLabel(d.inputs.flat_type, true);
    // The meter runs from 0 to 50% of income.
    const meterWidth = Math.min(r.repayment_ratio / 0.5, 1) * 100;

    const headline = h(
      "article",
      { class: "card card--pad-lg" },
      h("div", { class: "flex flex--between flex--wrap" }, h("span", { class: "value-hero__label" }, "Monthly repayment"), statusPill(r.status, r.status_label)),
      h("div", { class: "value-hero__num mt-8" }, money(r.monthly_repayment)),
      h(
        "p",
        { class: "value-hero__range" },
        `That’s ${ratio(r.repayment_ratio)} of your income, for a ${money(d.price)} ${titleCase(d.inputs.flat_type).toLowerCase()} flat`,
        d.inputs.town === "ALL" ? "" : ` in ${place}`,
        ` (${d.price_source}).`,
      ),
      h(
        "div",
        { class: "meter", role: "img", "aria-label": `Repayment takes ${ratio(r.repayment_ratio)} of income. The limit is ${ratio(as.msr_limit)}.` },
        h("div", { class: "meter__fill", "data-status": r.status, style: { width: `${meterWidth}%` } }),
        h("div", { class: "meter__mark meter__mark--soft", style: { left: `${(as.comfortable_ratio / 0.5) * 100}%` } }, h("span", {}, `${ratio(as.comfortable_ratio)} comfortable`)),
        h("div", { class: "meter__mark", style: { left: `${(as.msr_limit / 0.5) * 100}%` } }, h("span", {}, `${ratio(as.msr_limit)} limit`)),
      ),
      h(
        "p",
        { class: "small" },
        `Home loan repayments for HDB flats can’t go above ${ratio(as.msr_limit)} of your monthly income (the Mortgage Servicing Ratio). The ${ratio(as.comfortable_ratio)} “comfortable” mark is our own rule of thumb.`,
      ),
    );

    const breakdown = h(
      "article",
      { class: "card" },
      h("div", { class: "card__head" }, h("div", {}, h("h3", { class: "h3" }, "The numbers"), h("p", { class: "sub" }, `${what} in ${place}, ${d.window_label}.`))),
      h(
        "ul",
        { class: "breakdown" },
        h("li", {}, h("span", {}, "Price"), h("b", {}, money(r.price))),
        h("li", {}, h("span", {}, `Downpayment (${Math.round((1 - as.loan_to_value) * 100)}%)`), h("b", {}, money(r.min_downpayment))),
        h("li", {}, h("span", {}, "Buyer’s stamp duty"), h("b", {}, money(r.stamp_duty))),
        h("li", { class: "total" }, h("span", {}, "Cash and CPF needed upfront"), h("b", {}, money(r.upfront_needed))),
        r.upfront_shortfall > 0
          ? h("li", {}, h("span", { style: { color: "var(--critical-ink)" } }, "You’re short by"), h("b", { style: { color: "var(--critical-ink)" } }, money(r.upfront_shortfall)))
          : h("li", {}, h("span", {}, "Your savings cover this"), h("b", {}, iconSvg("check"))),
        h("li", {}, h("span", {}, `Loan at ${(as.annual_interest_rate * 100).toFixed(2)}% over ${as.tenure_years} years`), h("b", {}, money(r.loan))),
        h("li", {}, h("span", {}, "Price compared with yearly income"), h("b", {}, `${r.price_to_income.toFixed(1)} times`)),
      ),
      h("div", { class: "card__foot" }, "Any savings left after the upfront cost go towards a smaller loan."),
    );

    const b = d.budget;
    const budget = h(
      "article",
      { class: "card" },
      h("h3", { class: "h3" }, "Your budget"),
      h("div", { class: "tile__value" }, b.max_price > 0 ? `Up to ${money(b.max_price)}` : "Not enough saved yet"),
      h(
        "p",
        { class: "sub" },
        b.max_price > 0
          ? `Your ${b.limited_by === "upfront cash" ? "savings" : "monthly repayment"} set this limit. Paying up to ${money(b.repayment_cap)} a month covers a loan of about ${money(Math.round(b.max_loan / 1000) * 1000)}.`
          : `You need at least ${Math.round((1 - as.loan_to_value) * 100)}% of the price plus stamp duty upfront.`,
      ),
    );

    const gap = d.benchmark ? Math.abs(d.benchmark.income_vs_benchmark_pct).toFixed(0) : null;
    const benchCard = d.benchmark
      ? h(
          "article",
          { class: "card" },
          h("h3", { class: "h3" }, "Compared with the median household"),
          h(
            "p",
            { class: "sub" },
            `The median household earned ${money(d.benchmark.monthly_income)} a month in ${d.benchmark.year} (SingStat, including employer CPF). `,
            `Yours is ${gap}% ${d.benchmark.income_vs_benchmark_pct >= 0 ? "higher" : "lower"}. `,
            `On the median income, this flat would take ${ratio(d.benchmark.repayment_ratio)} of monthly pay.`,
          ),
        )
      : h("article", { class: "card" }, h("h3", { class: "h3" }, "No income benchmark"), h("p", { class: "sub" }, "SingStat wasn’t reachable when this data was built. Your own numbers still work."));

    fill(results, headline, h("div", { class: "grid grid--2" }, budget, benchCard), breakdown);
    drawRanking(d);
  }

  function drawRanking(d) {
    const rows = d.ranking;
    fill(
      rankingSlot,
      h(
        "article",
        { class: "card" },
        h(
          "div",
          { class: "card__head" },
          h(
            "div",
            {},
            h("p", { class: "eyebrow" }, "Where can I afford?"),
            h("h3", { class: "h2" }, `${int(d.within_reach_count)} of ${rows.length} towns fit your budget`),
            h("p", { class: "sub" }, `${flatTypeLabel(d.inputs.flat_type, true)} at each town’s median price, ${d.window_label}. Sorted by how much of your income the repayment takes. Towns with fewer than 20 sales are left out.`),
          ),
        ),
        table(
          [
            { key: "town", label: "Town", primary: true, format: (v, row) => h("button", { class: "rank-list__name", type: "button", style: { border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", fontWeight: 600 }, onclick: () => change({ town: v, price: null }) }, `${row.rank}. ${titleCase(v)}`) },
            { key: "median_price", label: "Median price", align: "right", format: money },
            { key: "monthly_repayment", label: "Repayment", align: "right", format: (v) => `${money(v)} a month` },
            { key: "repayment_ratio", label: "Share of income", align: "right", format: (v) => ratio(v) },
            { key: "upfront_needed", label: "Upfront", align: "right", format: money },
            {
              key: "status",
              label: "Fit",
              format: (v, row) =>
                row.within_reach
                  ? statusPill(row.status, row.status_label)
                  : statusPill("over", row.upfront_shortfall > 0 ? "Savings short" : row.status === "over" ? "Over the 30% limit" : "Over your limit"),
            },
          ],
          rows,
          { selectedKey: d.inputs.town, keyOf: (row) => row.town, stack: true },
        ),
      ),
    );
  }

  drawForm();
  await load();
}

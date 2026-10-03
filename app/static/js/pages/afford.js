import { api } from "../api.js";
import { callout, clear, fill, errorBanner, h, iconSvg, moneyInput, nextStep, numberInput, select, skeleton, statusPill, table } from "../dom.js";
import { flatTypeLabel, int, money, ratio, titleCase, townLabel } from "../format.js";
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
      h("h1", { class: "page-title" }, "Can your household afford it?"),
      h("p", { class: "lede" }, "Enter your own numbers. Every formula is shown, every assumption can be changed, and nothing you type leaves this page except to do the sums."),
    ),
  );

  const form = h("div", { class: "card stack" });
  const results = h("div", { class: "stack fade-on-load" }, skeleton(260), skeleton(320));
  root.append(h("section", { class: "wrap section" }, h("div", { class: "grid grid--side" }, h("div", { style: { position: "sticky", top: "calc(var(--nav-h) + 16px)" } }, form), results)));

  const rankingSlot = h("div", {}, skeleton(420));
  root.append(
    h("section", { class: "wrap section" }, rankingSlot),
    h(
      "section",
      { class: "wrap section--tight" },
      callout(
        "Affordability calculations are informational and not financial advice. They leave out housing grants, CPF usage limits and accrued interest, loan eligibility checks, legal and agent fees, and renovation. Check the latest rules on hdb.gov.sg before committing.",
      ),
    ),
    nextStep({ title: "Found a flat you like?", body: "Check whether its asking price is in line with similar recent sales.", href: "#/value", cta: "Estimate fair value" }),
  );

  function drawForm() {
    fill(form, 
      h("h2", { class: "h3" }, "Your household"),
      moneyInput({
        id: "a-income",
        label: "Monthly household income",
        value: inputs.income,
        step: 100,
        hint: bench ? `Singapore’s median: ${money(bench.monthly_income)} (SingStat ${bench.year}, includes employer CPF)` : "Gross monthly income of everyone on the loan",
        onChange: (v) => change({ income: v }),
      }),
      moneyInput({ id: "a-cash", label: "Cash and CPF for the purchase", value: inputs.cash, hint: "Used for the downpayment and stamp duty first", onChange: (v) => change({ cash: v ?? 0 }) }),
      select({ id: "a-type", label: "Flat type", options: meta.common_flat_types.map((t) => [t, flatTypeLabel(t)]), value: inputs.flat_type, onChange: (v) => change({ flat_type: v }) }),
      select({ id: "a-town", label: "Town", options: [["ALL", "All towns"], ...meta.towns.map((t) => [t, titleCase(t)])], value: inputs.town, onChange: (v) => change({ town: v, price: null }) }),
      moneyInput({ id: "a-price", label: "Price to test (optional)", value: inputs.price, placeholder: "Town median", onChange: (v) => change({ price: v }) }),
      moneyInput({ id: "a-cap", label: "Most you want to repay a month (optional)", value: inputs.max_repayment, step: 50, placeholder: "No extra cap", onChange: (v) => change({ max_repayment: v }) }),
      h(
        "details",
        { class: "advanced" },
        h("summary", {}, "Loan assumptions"),
        h(
          "div",
          { class: "stack mt-16" },
          numberInput({ id: "a-rate", label: "Interest rate", value: +(inputs.rate * 100).toFixed(2), step: 0.05, min: 0, max: 20, suffix: "% p.a.", onChange: (v) => change({ rate: v == null ? a.annual_interest_rate : v / 100 }) }),
          numberInput({ id: "a-tenure", label: "Loan tenure", value: inputs.tenure, step: 1, min: 5, max: 35, suffix: "years", onChange: (v) => change({ tenure: v ?? a.tenure_years }) }),
          numberInput({ id: "a-ltv", label: "Loan-to-value limit", value: Math.round(inputs.ltv * 100), step: 5, min: 5, max: 100, suffix: "%", onChange: (v) => change({ ltv: v == null ? a.loan_to_value : v / 100 }) }),
          h("p", { class: "hint" }, `Defaults model an HDB housing loan: ${(a.annual_interest_rate * 100).toFixed(1)}% interest, ${a.tenure_years} years, ${Math.round(a.loan_to_value * 100)}% loan-to-value.`),
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
      fill(results, errorBanner("Enter a monthly household income to see the numbers."));
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
    const meterWidth = Math.min(r.repayment_ratio / 0.5, 1) * 100;

    const headline = h(
      "article",
      { class: "card card--pad-lg" },
      h("div", { class: "flex flex--between flex--wrap" }, h("span", { class: "value-hero__label" }, "Estimated monthly repayment"), statusPill(r.status, r.status_label)),
      h("div", { class: "value-hero__num mt-8" }, money(r.monthly_repayment)),
      h(
        "p",
        { class: "value-hero__range" },
        `${ratio(r.repayment_ratio)} of your monthly income for a ${money(d.price)} ${titleCase(d.inputs.flat_type).toLowerCase()} flat`,
        d.inputs.town === "ALL" ? "" : ` in ${place}`,
        ` (${d.price_source}).`,
      ),
      h(
        "div",
        { class: "meter", role: "img", "aria-label": `Repayment takes ${ratio(r.repayment_ratio)} of income` },
        h("div", { class: "meter__fill", "data-status": r.status, style: { width: `${meterWidth}%` } }),
        h("div", { class: "meter__mark meter__mark--soft", style: { left: `${(as.comfortable_ratio / 0.5) * 100}%` } }, h("span", {}, `${ratio(as.comfortable_ratio)} comfortable*`)),
        h("div", { class: "meter__mark", style: { left: `${(as.msr_limit / 0.5) * 100}%` } }, h("span", {}, `${ratio(as.msr_limit)} MSR cap`)),
      ),
      h(
        "p",
        { class: "small" },
        `The Mortgage Servicing Ratio caps repayments for HDB flats at ${ratio(as.msr_limit)} of gross monthly income. *“Comfortable” at ${ratio(as.comfortable_ratio)} or less is FlatFair’s illustrative threshold, not a rule.`,
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
        h("li", {}, h("span", {}, `Minimum downpayment (${Math.round((1 - as.loan_to_value) * 100)}%)`), h("b", {}, money(r.min_downpayment))),
        h("li", {}, h("span", {}, "Buyer’s stamp duty"), h("b", {}, money(r.stamp_duty))),
        h("li", { class: "total" }, h("span", {}, "Upfront cash and CPF needed"), h("b", {}, money(r.upfront_needed))),
        r.upfront_shortfall > 0
          ? h("li", {}, h("span", { style: { color: "var(--critical-ink)" } }, "Short of the upfront amount by"), h("b", { style: { color: "var(--critical-ink)" } }, money(r.upfront_shortfall)))
          : h("li", {}, h("span", {}, "Your savings cover the upfront amount"), h("b", {}, iconSvg("check"))),
        h("li", {}, h("span", {}, `Loan at ${(as.annual_interest_rate * 100).toFixed(2)}% over ${as.tenure_years} years`), h("b", {}, money(r.loan))),
        h("li", {}, h("span", {}, "Price ÷ annual household income"), h("b", {}, `${r.price_to_income.toFixed(1)} years`)),
      ),
      h("div", { class: "card__foot" }, `Repayment = loan × r ÷ (1 − (1 + r)^−n), with r the monthly rate and n the number of months. Savings beyond the upfront amount reduce the loan.`),
    );

    const b = d.budget;
    const budget = h(
      "article",
      { class: "card" },
      h("h3", { class: "h3" }, "Your estimated budget"),
      h("div", { class: "tile__value" }, b.max_price > 0 ? `Up to ${money(b.max_price)}` : "Not enough for the upfront cost yet"),
      h(
        "p",
        { class: "sub" },
        b.max_price > 0
          ? `Limited by your ${b.limited_by}. Repayments capped at ${money(b.repayment_cap)} a month allow a loan of about ${money(Math.round(b.max_loan / 1000) * 1000)}.`
          : `Every purchase needs at least ${Math.round((1 - as.loan_to_value) * 100)}% of the price plus stamp duty upfront.`,
      ),
    );

    const benchCard = d.benchmark
      ? h(
          "article",
          { class: "card" },
          h("h3", { class: "h3" }, "Against Singapore’s median household"),
          h(
            "p",
            { class: "sub" },
            `The median resident employed household earned ${money(d.benchmark.monthly_income)} a month in ${d.benchmark.year} (SingStat ${d.benchmark.table_id}, including employer CPF). `,
            `Your income is ${Math.abs(d.benchmark.income_vs_benchmark_pct).toFixed(0)}% ${d.benchmark.income_vs_benchmark_pct >= 0 ? "above" : "below"} that. `,
            `At the median income this flat would take ${ratio(d.benchmark.repayment_ratio)} of monthly income and ${d.benchmark.price_to_income.toFixed(1)} years of income.`,
          ),
        )
      : h("article", { class: "card" }, h("h3", { class: "h3" }, "Official income benchmark unavailable"), h("p", { class: "sub" }, "SingStat could not be reached when the data was built. Your own figures still work."));

    fill(results, headline, h("div", { class: "grid grid--2" }, budget, benchCard), breakdown);
    drawRanking(d);
  }

  function drawRanking(d) {
    const rows = d.ranking;
    fill(rankingSlot, 
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
            h("h3", { class: "h2" }, `${int(d.within_reach_count)} of ${rows.length} towns within reach for ${flatTypeLabel(d.inputs.flat_type, true)}`),
            h(
              "p",
              { class: "sub" },
              `Ranked by the share of your income the repayment would take at each town’s median price (${d.window_label}). “Within reach” means the repayment fits your cap and your savings cover the downpayment and stamp duty. Towns with fewer than 20 sales are left out.`,
            ),
          ),
        ),
        table(
          [
            { key: "rank", label: "#", format: (v) => h("span", { class: "muted num" }, v) },
            { key: "town", label: "Town", format: (v) => h("button", { class: "rank-list__name", type: "button", style: { border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", fontWeight: 500 }, onclick: () => change({ town: v, price: null }) }, titleCase(v)) },
            { key: "median_price", label: "Median price", align: "right", format: money },
            { key: "monthly_repayment", label: "Repayment", align: "right", format: (v) => `${money(v)}/mo` },
            { key: "repayment_ratio", label: "Of income", align: "right", format: (v) => ratio(v) },
            { key: "upfront_needed", label: "Upfront", align: "right", format: money },
            {
              key: "status",
              label: "Status",
              format: (v, row) =>
                row.within_reach
                  ? statusPill(row.status, row.status_label)
                  : statusPill("over", row.upfront_shortfall > 0 ? "Savings short" : row.status === "over" ? "Above the MSR limit" : "Over your cap"),
            },
          ],
          rows,
          { selectedKey: d.inputs.town, keyOf: (row) => row.town },
        ),
      ),
    );
  }

  drawForm();
  await load();
}

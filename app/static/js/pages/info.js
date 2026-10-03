// The pages behind the footer links: About, Questions and answers, Data
// sources, Terms of use and Privacy. Figures quoted here are read from the
// build's metadata, so they stay in step with the data.

import { callout, h } from "../dom.js";
import { dateLabel, int, monthLabel } from "../format.js";

const REPO = "https://github.com/bernardinolintang/Databricks-Hackathon";
const dataset = (id) => `https://data.gov.sg/datasets/${id}/view`;
const out = (href, text) => h("a", { href, target: "_blank", rel: "noopener" }, text);

function head(tag, title, lede) {
  return h("section", { class: "wrap page-head" }, h("p", { class: "eyebrow" }, tag), h("h1", { class: "page-title" }, title), lede ? h("p", { class: "lede" }, lede) : null);
}

function facts(meta) {
  const q = meta.quality;
  const acc = meta.fair_value_accuracy;
  const a = meta.assumptions;
  return {
    records: int(q.total_rows),
    from: monthLabel(q.earliest_month),
    lastFull: monthLabel(meta.last_complete_month),
    openMonth: monthLabel(q.latest_month),
    updated: dateLabel(q.source_last_updated),
    checks: q.checks_total,
    towns: meta.towns.length,
    miss: acc.median_ape.toFixed(1),
    within10: acc.within_10pct.toFixed(0),
    tested: int(acc.n),
    forecastError: meta.forecast_mape.toFixed(1),
    forecastStarts: meta.forecast_origins,
    rate: (a.annual_interest_rate * 100).toFixed(1),
    years: a.tenure_years,
    loanShare: Math.round(a.loan_to_value * 100),
    limit: Math.round(a.msr_limit * 100),
    blocks: meta.has_location ? int(meta.location.blocks) : null,
    walkSpeed: meta.has_location ? meta.location.walk_speed_m_per_min : null,
    detour: meta.has_location ? Math.round((meta.location.detour_factor - 1) * 100) : null,
  };
}

// ------------------------------------------------------------------ about
function about(meta) {
  const f = facts(meta);
  return [
    head("About", "About FlatFair", "FlatFair helps people buying an HDB resale flat see what flats really sell for, what they can afford and whether an asking price makes sense."),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "prose" },
        h("h2", {}, "Why we built it"),
        h("p", {}, `A resale flat is the biggest thing most households will ever buy. Every sale is public, but the records sit in a table of ${f.records} rows that few buyers will ever open. FlatFair reads that table for you and answers the questions a buyer asks.`),
        h("h2", {}, "What you can do here"),
        h(
          "ul",
          {},
          h("li", {}, h("a", { href: "#/market" }, "Market"), ": see prices and sales in any town, for any flat type."),
          h("li", {}, h("a", { href: "#/forecast" }, "Forecast"), ": see where the median price may be in six months, with a range."),
          h("li", {}, h("a", { href: "#/afford" }, "Affordability"), ": turn a price into a monthly repayment and the cash you need upfront."),
          h("li", {}, h("a", { href: "#/value" }, "Fair value"), meta.has_location ? ": check an asking price against similar sales, and see what is within walking distance of the block." : ": check an asking price against similar sales."),
          h("li", {}, h("a", { href: "#/compare" }, "Compare"), ": put up to three towns side by side."),
        ),
        h("h2", {}, "Who made it"),
        h("p", {}, "FlatFair is a student project for the Databricks AI Social Impact Challenge Singapore 2026. It is not affiliated with or endorsed by HDB or any government agency. For rules, grants and eligibility, go to ", out("https://www.hdb.gov.sg", "hdb.gov.sg"), "."),
        h("h2", {}, "How it works"),
        h(
          "p",
          {},
          `The data pipeline runs on Databricks. It pulls HDB’s resale records from data.gov.sg, runs ${f.checks} checks on them, and stores each stage as a Delta table in Unity Catalog. `,
          f.blocks ? `It places ${f.blocks} blocks on the map and measures the walk from each to trains, schools, shops and parks. ` : "",
          `Two models are trained and logged in MLflow: a six-month forecast for each town, and a price estimate for a single flat. On ${f.tested} sales it had never seen, the price estimate was typically ${f.miss}% off.`,
        ),
        h("p", {}, "The ", h("a", { href: "#/faq" }, "questions and answers"), " page explains each number in plain words, and ", h("a", { href: "#/sources" }, "data sources"), " lists where everything comes from."),
        h("h2", {}, "What it can’t do"),
        h("p", {}, "The estimate can’t see inside a flat. Renovation, the view, the exact unit and noise all move a price and none of them are in the records. Treat the range as the answer and the single number as its middle."),
        h("h2", {}, "Get in touch"),
        h("p", {}, "Found a mistake or have a suggestion? Open an issue on ", out(REPO, "GitHub"), "."),
      ),
    ),
  ];
}

// ------------------------------------------------------------------ questions
function faq(meta) {
  const f = facts(meta);
  const groups = [
    [
      "The data",
      [
        ["Where do the prices come from?", [`From HDB’s resale flat prices on data.gov.sg, which lists every resale registered since ${f.from}. FlatFair pulls the whole set each time its pipeline runs. There are ${f.records} records in this build.`]],
        [
          "It says updated in one month but prices stop at the month before. Why?",
          [
            `The source was last updated on ${f.updated}. ${f.openMonth} had only just started then, so it holds a small part of the month’s sales.`,
            `Averaging a few days of sales gives a jumpy price and a sales count that looks like a crash. So prices, trends and forecasts stop at the last full month, ${f.lastFull}. The newest sales still show up in the list of recent sales on the Fair value page.`,
          ],
        ],
        ["Why does a town sometimes show “too few sales”?", ["A median from a handful of sales says more about those few flats than about the town. When there are too few, FlatFair leaves the number out."]],
        ["Is the price what the buyer really paid?", ["It is the resale price registered with HDB. It leaves out stamp duty, legal and agent fees, and renovation."]],
        ["What checks are run on the data?", [`${f.checks} checks run on every record, for example that every price is above zero and no sale is dated in the future. Odd records are flagged and kept, with the reason. Open the data health panel at the top of any page to see the results.`]],
      ],
    ],
    [
      "The price estimate",
      [
        [
          "How is the estimate worked out?",
          [
            `A model learns from every past sale how much each detail is worth: the town, flat type and model, size, storey and years of lease left${meta.has_location ? ", and what is near the block" : ""}.`,
            "Prices move over time, so the model works on prices relative to the market level in the month of each sale. Your estimate is then brought to today’s level.",
          ],
        ],
        ["How accurate is it?", [`It was tested on ${f.tested} flats sold in the most recent six months, which it had not seen. Its typical miss was ${f.miss}%, and ${f.within10}% of its estimates were within 10% of the real price.`]],
        ["What is the usual range?", ["In testing, 8 in 10 flats sold inside this range. An asking price above it is not wrong, but it is higher than most similar flats fetched."]],
        ["Why is the asking price different from the estimate?", ["Sellers price in things the records can’t show, such as renovation, the view or a corner unit. The estimate is what flats with the same recorded details sold for."]],
        meta.has_location ? ["Does location within a town matter?", ["Yes. Two flats with the same details can differ in price because one is a short walk from the MRT and the other is not. When you choose the block, the estimate uses that block’s location. Without a block it assumes a typical spot in the town."]] : null,
      ],
    ],
    meta.has_location
      ? [
          "Location and walking times",
          [
            ["How are walking times worked out?", [`They are estimates. We measure the straight-line distance from the block, add ${f.detour}% because real routes bend, and assume a pace of ${f.walkSpeed} m a minute. A real walk can be shorter or longer, for example where a road or canal has to be crossed.`]],
            ["What counts as nearby?", ["The nearest MRT or LRT station exit, bus stops within 400 m, primary schools within 1 km, and the nearest mall, hawker centre, park and park connector."]],
            ["Why primary schools within 1 km?", ["MOE gives priority for Primary 1 places to children living within 1 km of a school, then to those within 2 km. Check the school’s own page before relying on it, as distances here are approximate."]],
            ["How do you know where a block is?", [`From HDB’s building outlines on data.gov.sg. Each of the ${f.blocks} blocks with a resale record is matched to its outline, and its position is the middle of that outline.`]],
          ],
        ]
      : null,
    [
      "The forecast",
      [
        ["How is the forecast made?", [`Four methods were tried, from the plain average of the last three months to a machine learning model. Each was tested from ${f.forecastStarts} past starting points against what really sold. The one with the smallest error is used. Its average error was ${f.forecastError}%.`]],
        ["Can I count on it?", ["No. It is a reading of where prices are heading if nothing changes. It doesn’t know about interest rates, new flat supply or policy changes, and it forecasts a town’s median price, so single flats will sell above and below it."]],
      ],
    ],
    [
      "Affordability",
      [
        ["What loan does it assume?", [`An HDB housing loan: ${f.rate}% interest a year over ${f.years} years, borrowing up to ${f.loanShare}% of the price. You can change all three under Loan settings.`]],
        ["What is the limit on repayments?", [`Home loan repayments for an HDB flat can’t go above ${f.limit}% of your gross monthly income. This is the Mortgage Servicing Ratio.`]],
        ["Does it include grants?", ["No. Housing grants, CPF rules and loan eligibility depend on your household and are not in the sums. Use HDB’s own calculators and your HFE letter for those."]],
      ],
    ],
    [
      "About this site",
      [
        ["Is this an HDB website?", ["No. FlatFair is a student project. It uses public data that HDB and other agencies publish, and it is not affiliated with or endorsed by any of them."]],
        ["Do you keep the income and savings I type in?", ["There are no accounts. Your numbers are kept in your own browser so they carry from one page to the next, and they are sent to FlatFair’s server only to do the sums. See the ", h("a", { href: "#/privacy" }, "privacy page"), " for the details."]],
        ["Can I use the numbers for a decision?", ["Use them to get your bearings, then check with HDB, your bank and a property agent or lawyer. This is a guide and not financial advice."]],
      ],
    ],
  ];

  return [
    head("Help", "Questions and answers", "How each number is worked out, and what it does and doesn’t tell you."),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "prose" },
        groups.filter(Boolean).map(([title, items]) => [
          h("h2", { class: "faq-group" }, title),
          items.filter(Boolean).map(([question, answer]) => h("details", { class: "faq" }, h("summary", {}, question), h("div", { class: "faq__body" }, answer.length && typeof answer[0] === "string" && answer.every((part) => typeof part === "string") ? answer.map((text) => h("p", {}, text)) : h("p", {}, answer)))),
        ]),
      ),
    ),
  ];
}

// ------------------------------------------------------------------ sources
function sources(meta) {
  const s = meta.sources;
  const rows = [];
  const add = (title, use, publisher, href, linkText = "Open the dataset") => rows.push(h("li", {}, h("b", {}, title), h("span", {}, `${use} ${publisher}.`), out(href, linkText)));

  add(s.hdb_resale.name, "Every resale price, flat detail and sale month.", s.hdb_resale.publisher, dataset(s.hdb_resale.dataset_id));
  if (s.income) add("Key indicators on household employment income", "The median household income used as a yardstick for affordability.", s.income.publisher, `https://tablebuilder.singstat.gov.sg/table/TS/${s.income.table_id}`, "Open the table");
  if (s.planning_areas) add(s.planning_areas.name, "The town outlines on the map of Singapore.", s.planning_areas.publisher, dataset(s.planning_areas.dataset_id));
  if (s.hdb_buildings) add(s.hdb_buildings.name, "Where each block is.", s.hdb_buildings.publisher, dataset(s.hdb_buildings.dataset_id));
  const uses = {
    mrt_exits: "MRT and LRT station exits.",
    bus_stops: "Bus stops.",
    schools: "Schools and their addresses.",
    hawker_centres: "Hawker centres.",
    parks: "Parks.",
    park_connectors: "Park connector routes.",
  };
  for (const [key, use] of Object.entries(uses)) {
    const source = s.places?.[key];
    if (source) add(source.name, use, source.publisher, dataset(source.dataset_id));
  }
  if (s.places?.malls) add(s.places.malls.name, "Shopping malls. No agency publishes a list, so these come from OpenStreetMap.", s.places.malls.publisher, "https://www.openstreetmap.org/copyright", "Licence");
  if (meta.has_location) add("OneMap", "The street map behind the pins, and the position of each school from its postal code.", "Singapore Land Authority", "https://www.onemap.gov.sg/", "Open OneMap");

  return [
    head("Data", "Where the data comes from", "Everything on FlatFair is built from open data that anyone can download."),
    h("section", { class: "wrap section" }, h("article", { class: "card" }, h("ul", { class: "sourcelist" }, rows))),
    h(
      "section",
      { class: "wrap section--tight" },
      h(
        "div",
        { class: "prose" },
        h("h2", {}, "Licences"),
        h("p", {}, "Data from data.gov.sg and SingStat is used under the ", out("https://data.gov.sg/open-data-licence", "Singapore Open Data Licence"), ". Mall locations are © OpenStreetMap contributors, under the Open Database Licence. Map tiles are © OneMap and the Singapore Land Authority."),
        h("h2", {}, "How fresh it is"),
        h("p", {}, `HDB last updated the resale records on ${dateLabel(meta.quality.source_last_updated)}. This build pulled them on ${dateLabel(meta.quality.ingested_at)}. Open the data health panel at the top of the page for the checks that ran.`),
      ),
    ),
  ];
}

// ------------------------------------------------------------------ terms and privacy
function terms() {
  return [
    head("Terms", "Terms of use", "The short version: FlatFair is a guide. Check anything important with HDB and a professional before you commit."),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "prose" },
        h("h2", {}, "What FlatFair is"),
        h("p", {}, "FlatFair is a student project that summarises public data about HDB resale flats. It is not run by, affiliated with or endorsed by HDB or any government agency."),
        h("h2", {}, "Not advice"),
        h("p", {}, "Nothing here is financial, legal or property advice. Estimates, forecasts and affordability figures are worked out from past sales and from assumptions you can see and change. They can be wrong for your flat and your household."),
        h("h2", {}, "The data"),
        h("p", {}, "The data comes from the agencies listed under ", h("a", { href: "#/sources" }, "data sources"), ". It can be late, incomplete or corrected after the fact. Rules on loans, grants and eligibility change, and the current ones are on ", out("https://www.hdb.gov.sg", "hdb.gov.sg"), "."),
        h("h2", {}, "No guarantee"),
        h("p", {}, "The site is provided as it is, with no promise that it is accurate, complete or always available. You use it at your own risk, and the team is not liable for decisions made with it."),
        h("h2", {}, "Reusing what you see"),
        h("p", {}, "The underlying data stays under its own licences, linked from the data sources page. If you quote a figure, please say it came from FlatFair and when."),
      ),
    ),
  ];
}

function privacy(meta) {
  return [
    head("Privacy", "Privacy", "FlatFair has no accounts and no trackers. Here is exactly what happens to what you type."),
    h(
      "section",
      { class: "wrap section" },
      h(
        "div",
        { class: "prose" },
        h("h2", {}, "What stays in your browser"),
        h("p", {}, "Your town, flat type, income, savings and asking price are saved in your browser’s local storage, so they carry from one page to the next. They stay on your device. Clearing your browser’s site data removes them."),
        h("h2", {}, "What is sent to the server"),
        h("p", {}, "To work out a repayment or an estimate, the numbers you enter are sent to FlatFair’s server as part of the request. The server does the sum and sends back the answer. It does not save your numbers in a database."),
        h("p", {}, "Like most websites, the hosting service keeps short-lived access logs. A log line includes the web address requested, and that address contains the numbers you entered. The logs are not linked to a name or an account."),
        meta.has_location ? h("h2", {}, "Maps") : null,
        meta.has_location ? h("p", {}, "The street map on the Fair value page is drawn from OneMap, run by the Singapore Land Authority. When you open that map, your browser asks OneMap directly for the map images of the area, so OneMap sees your IP address and the area shown.") : null,
        h("h2", {}, "What we don’t do"),
        h("ul", {}, h("li", {}, "No sign-up, and nothing that asks for your name, NRIC, phone number or email."), h("li", {}, "No advertising or analytics cookies."), h("li", {}, "No selling or sharing of anything you enter.")),
        h("h2", {}, "Questions"),
        h("p", {}, "Open an issue on ", out(REPO, "GitHub"), "."),
      ),
    ),
    h("section", { class: "wrap section--tight" }, callout("FlatFair is a student project and this page describes how it works today. It is not a legal document.")),
  ];
}

const PAGES = { about, faq, sources, terms, privacy };

export async function render(root, { meta, route }) {
  const parts = (PAGES[route] || about)(meta);
  root.append(...parts);
}

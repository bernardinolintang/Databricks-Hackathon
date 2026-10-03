# Demo script (about 5 minutes)

**Persona:** *"We're a couple, both 29, earning $9,000 a month together, with $200,000 in cash and CPF. We like Tampines and want a 4-room resale flat."*

Before going live: open the app in a fresh browser window (no saved state), then click the Data Health chip so the panel is warm.

| # | Scene | Presenter | Click path | Say |
|---|---|---|---|---|
| 0 | Hook | A | Overview | "Resale prices are up 56% since 2017; median household income is up 33%. Buyers have the data but not the answers. FlatFair turns 241,822 official transactions into a decision." |
| 1 | The market | A | Overview → **Explore the market** (Tampines, 4-room pre-selected) | "Tampines 4-room median is $671k, up 1.7% on a year ago, with flat momentum. The band is the middle half of sales; the marker is the Oct 2024 classification change, shown as context, not cause." |
| 2 | The forecast | A → B | **Open the forecast** | "Our gradient-boosted model came second. The simplest method, a 3-month average, won a six-origin backtest across 104 series, so that's what we publish. The 80% range comes from its own past errors. Every run is in MLflow." |
| 3 | Affordability | B | **Check affordability**, income 9000, savings 200000 | "$2,176 a month, 24% of income: comfortable, and under the 30% MSR cap. Their budget is about $733k, limited by upfront cash. *Where can I afford?* puts 17 of 25 towns within reach." |
| 4 | Fair value | B → C | **Estimate fair value**: 95 sqm, storey 10–12, 72 years left, asking $690,000 | "Estimated $662k, range $612k–$710k. The asking price is 4% above the estimate, inside the expected range. Higher floor adds about $9k over a typical Tampines 4-room. These five sales are the closest comparables. Tested on 13,589 sales it never saw: median error 3.9%." |
| 5 | Alternatives | C | **Compare towns**: Tampines, Bedok, Pasir Ris | "Bedok is $72k cheaper and takes 20% of income. Tampines grew most over five years. The decision is theirs, now with evidence." |
| 6 | How it's built | C | Show Databricks: notebooks, Delta tables with comments/tags, lineage, MLflow runs | "Bronze/silver/gold in Unity Catalog, nine quality checks with nothing deleted, MLflow for both models, and the app on Databricks Apps." |

## Fallbacks

* **Live app fails:** the same app is at the Vercel URL. Screenshots of every page are in `docs/screenshots/`.
* **Databricks quota hit:** show the MLflow screenshots and notebook outputs. The app keeps serving from the published bundle.
* **Most failure-prone step:** a live pipeline rerun (network + compute). Don't do it live; show the ingestion log table and the Data Health panel instead.

## Likely questions

| Question | Answer |
|---|---|
| Why didn't you use the ML model for the forecast? | We did train one. It lost the backtest narrowly because it learned 2020–24 momentum and the market flattened. Publishing the winner, with the scorecard visible, is the honest choice; the pipeline re-selects automatically each run. |
| How do you handle outliers? | We flag, not delete. 1,078 unusual $/sqm sales turned out to be premium DBSS or short-lease flats the model can explain, so they stay. 318 exact duplicates stay too: there's no transaction ID, so they can be genuine twin sales. |
| Is the fair value a valuation? | No. It's a statistical estimate with an 80% range. It can't see renovation, view or negotiation, and the UI says so on every result. |
| Does the 2024 classification change affect resale prices? | The framework applies to new BTO flats and resale records have no classification field. We show before/after medians as an association only. |
| Where's the income data from? | SingStat Table Builder M810361, median household employment income including employer CPF, pulled by API. |
| Could HDB or a bank adopt this? | Everything runs on public data and a Free Edition workspace, refreshes monthly with one job, and needs no personal data. A counsellor could use the affordability and fair-value steps with a client today. |
| What would you build next? | BTO supply impact on nearby resale prices, grants in the affordability step, and a Genie space so analysts can ask questions of the gold tables in plain English. |

## Demo readiness checklist (from the DAISI guide)

| Item | Status |
|---|---|
| Deployment owner can sign in and open every resource | **Team:** confirm in the final workspace |
| App, pipeline and data ready in the final workspace | Notebooks 00–07 + `app.yaml` ready. **Team:** run them in the final workspace and deploy the app |
| Main journey tested from a fresh browser session | Done locally (headless Chrome, clean profile) and by `tests/test_api.py::test_demo_journey`. **Team:** repeat on the deployed URL |
| No token, password, private key or personal data visible | Repo scanned before push; the app collects no identity; no secrets are needed (both data APIs are public) |
| Team can explain problem, user, architecture, Databricks contribution and handoffs | This script; presenters A/B/C above |
| Third-party datasets, libraries, models and templates credited | README §17 and app footer |
| Screenshot or recording for the most failure-prone step | `docs/screenshots/`; record a 60-second screen capture of scenes 3–4 before Demo Day |
| Final link, repository and materials accessible to judges | Public GitHub repo + Vercel URL; deck PDF in `docs/` |

# Demo script (about 5 minutes)

**Persona:** *"We're a couple, both 29, earning $9,000 a month together, with $200,000 in cash and CPF. We like Tampines and want a 4-room resale flat."*

Before going live: open the app in a fresh browser window (no saved state), then click the Data Health chip so the panel is warm.

| # | Scene | Presenter | Click path | Say |
|---|---|---|---|---|
| 0 | Hook | A | Overview | "Resale prices are up 56% since 2017. Household income is up 33%. Buyers have the data but no easy way to use it. FlatFair turns 241,920 HDB records into answers." |
| 1 | The map | A | Overview, tap **Tampines** on the map | "Every town is on the map, shaded by price. Tap one and the whole town lights up with its numbers. The shapes come from URA's open boundary data, so there's no map service behind it." |
| 2 | The market | A | **See Tampines** | "A 4-room flat in Tampines is $671k, up 1.7% from a year ago, and flat over the last three months. The band is the middle half of sales. The marker is the October 2024 flat classification change, shown for context." |
| 3 | The forecast | A to B | **See the forecast** | "We tried four methods on 104 town and flat type combinations, from six past dates. The simplest one won, a 3-month average, so that's what we show. Our machine learning model came second. Every test run is in MLflow." |
| 4 | Affordability | B | **Check affordability**, income 9000, savings 200000 | "$2,176 a month, 24% of income, under the 30% limit. Their budget is about $733k. 17 of 25 towns fit." |
| 5 | Fair value | B to C | **Check a flat's price**: street **Tampines Ave 4**, block **802**, storey 10 to 12, asking $650,000 | "They found a flat at Blk 802. Picking the block fills in that block's lease, size and model: 57 years, 93 sqm, New Generation. Estimated at $624k, usual range $587k to $657k. The asking price is about 4% above the estimate and inside the range. Being at this block is worth about $61k against a typical spot in Tampines; the older flat model takes off about $42k and the shorter lease about $28k." |
| 5b | Location | C | Scroll to **What's within walking distance**; hover **Tampines West MRT** in the list | "Here's why. Tampines West MRT is a one-minute walk, a primary school four minutes, a mall five. The rings are a 5 and 10 minute walk, the green lines are park connectors, and the numbered pins are the five closest recent sales, each with its distance from this block. On 13,588 sales the model had never seen, its typical miss was 3.0%. Without location it was 3.9%." |
| 6 | Alternatives | C | **Compare towns**: Tampines, Bedok, Pasir Ris | "Bedok is $72k cheaper, takes 20% of their income, and a typical flat there is a 10 minute walk from a station. Tampines went up the most in five years. Now they can decide with evidence." |
| 7 | How it's built | C | Show Databricks: notebooks, Delta tables with comments and tags, lineage, MLflow runs | "Bronze, silver and gold tables in Unity Catalog. Nine quality checks, nothing deleted. MLflow for both models. The app runs on Databricks Apps." |

On a phone the six sections sit in a tab bar at the bottom, and the town picker opens as a sheet with the map on top.

## Fallbacks

* **Live app fails:** the same app is at the Vercel URL. Screenshots of every page are in `docs/screenshots/`.
* **Databricks quota hit:** show the MLflow screenshots and notebook outputs. The app keeps serving from the published bundle.
* **Picking the flat live:** use the deep link `#/value?town=TAMPINES&type=4%20ROOM&street=TAMPINES%20AVE%204&block=802&storey=10%20TO%2012&ask=650000`.
* **The street map does not load** (OneMap unreachable): the "What's nearby" list, the distances in the table and the estimate do not depend on it. Say so and carry on.
* **Most failure-prone step:** a live pipeline rerun (network + compute). Don't do it live; show the ingestion log table and the Data Health panel instead.

## Likely questions

| Question | Answer |
|---|---|
| Why didn't you use the ML model for the forecast? | We did train one. It lost the backtest narrowly because it learned 2020 to 2024 momentum and the market flattened. We show the winner and the scorecard. The pipeline picks again on every run. |
| How do you handle outliers? | We flag them and keep them. 1,075 unusual $/sqm sales turned out to be premium DBSS or short-lease flats the model can explain, so they stay. 318 exact duplicates stay too: there's no transaction ID, so they can be genuine twin sales. |
| Is the fair value a valuation? | No. It's a statistical estimate with an 80% range. It can't see renovation, view or negotiation, and the UI says so on every result. |
| Does the 2024 classification change affect resale prices? | The framework applies to new BTO flats and resale records have no classification field. We show before/after medians as an association only. |
| Where's the income data from? | SingStat Table Builder M810361, median household employment income including employer CPF, pulled by API. |
| Could HDB or a bank adopt this? | Everything runs on public data and a Free Edition workspace, refreshes monthly with one job, and needs no personal data. A counsellor could use the affordability and fair-value steps with a client today. |
| Do you need a maps API? | No key anywhere. The town map is drawn from URA planning area boundaries, simplified in our pipeline to 34 KB. The street map on the Fair value page uses OneMap's public base map from the Singapore Land Authority. |
| How do you know where a block is? | From HDB's own building outlines on data.gov.sg. Resale records name the street and the outlines use a street code, so the pipeline works out which code each street uses. All 9,755 blocks are placed. We checked 40 against OneMap: 6 m apart on average, never more than 36 m. |
| Are the walking times real routes? | No, they're estimates and the app says so: straight-line distance plus 30%, at 80 m a minute. Real routing needs a service with a login. It's on the list. |
| Does location really change the price? | Yes, and we measured it. The same model without location misses by 3.9% on unseen sales; with location, 3.0%. The walk to the MRT matters most, then distance to the city centre. |
| What would you build next? | Real walking routes, BTO supply impact on nearby resale prices now that blocks are placed, grants in the affordability step, and a Genie space so analysts can ask questions of the gold tables in plain English. |

## Demo readiness checklist (from the DAISI guide)

| Item | Status |
|---|---|
| Deployment owner can sign in and open every resource | **Team:** confirm in the final workspace |
| App, pipeline and data ready in the final workspace | Notebooks 00 to 07 + `app.yaml` ready. **Team:** run them in the final workspace and deploy the app |
| Main journey tested from a fresh browser session | Done: `tests/ui_check.py` loads every page in a clean Chrome session at nine screen sizes, and `tests/test_api.py::test_demo_journey` walks the journey. **Team:** repeat on the deployed URL |
| No token, password, private key or personal data visible | Repo scanned before push; the app collects no identity; no secrets are needed (both data APIs are public) |
| Team can explain problem, user, architecture, Databricks contribution and handoffs | This script; presenters A/B/C above |
| Third-party datasets, libraries, models and templates credited | README section 17, the app footer and the app's Data sources page |
| Screenshot or recording for the most failure-prone step | `docs/screenshots/`; record a 60-second screen capture of scenes 3 and 4 before Demo Day |
| Final link, repository and materials accessible to judges | Vercel URL is public. GitHub repo is **private**: make it public or add judges. Deck: `submission/FlatFair_Round1_Deck.pdf` |

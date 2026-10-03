# Product specification

## Product

FlatFair is a decision tool for HDB resale buyers, not a price dashboard. It connects five questions in one journey, and each step carries the buyer's choices into the next:

**market intelligence → forecast → personal affordability → property valuation → comparable sales → alternatives**

The test: a young couple considering a 4-room flat in Tampines can, in about three minutes, see the market, a tested six-month outlook, what they can afford, whether a specific asking price is in line, and how two other towns compare.

## MVP (built)

| Area | Included |
|---|---|
| Pipeline | data.gov.sg ingestion (bulk + paged API, retries, rate-limit handling, schema and row-count checks, audit log, file fallback); bronze/silver/gold Delta; 9 quality checks; flags not deletes; partial-month handling; SingStat income ingestion; URA boundary ingestion for the town map; block locations from HDB building outlines; nearby places from LTA, MOE, NEA, NParks and OpenStreetMap |
| Market | KPIs (median, YoY, volume, $/sqm), price trend with interquartile band, volume, distribution, $/sqm town ranking; filters for town, flat type, storey, flat model and year range; Oct 2024 marker with a before/after association |
| Forecast | 6-month town × flat type forecast; 4 methods compared by rolling-origin backtest; MLflow; empirical 80% range; generated plain-English reading |
| Affordability | Repayment, upfront cash, stamp duty, MSR comparison, budget, official income benchmark, *Where can I afford?* ranking, editable assumptions |
| Fair value | Gradient-boosted model vs ridge vs rule of thumb, with and without location; holdout scoring; expected range; asking-price position; local and global explanations; 5 comparables |
| Location | Optional street and block picker that fills in the lease; "What's nearby" in five rows (train, bus, schools, shops and food, parks) with estimated walking times; street map with 5 and 10 minute rings, place pins, park connectors and numbered pins for the comparables; distance from the block for each comparable; location as an input to the price model |
| Compare | Up to 3 towns: price, $/sqm, YoY, 5-year change, outlook, repayment share, typical walk to a station, generated takeaways, trend chart, the towns on a map that adds or removes them on a tap |
| Product | Map-based town picker on every page, Data Health panel, zoomable time charts, About / Questions / Data sources / Terms / Privacy pages, error and empty states, table view for every chart, layouts from 360 px phones to 2560 px monitors, journey state carried across pages |
| Platform | Databricks notebooks 00 to 07, MLflow, UC model registry, table comments and tags, SQL views (lineage), Databricks Apps config; Vercel public demo |

## Deliberately after the MVP

| Feature | Why it waits |
|---|---|
| BTO supply impact on nearby resale (stretch goal) | Blocks are now placed, so the missing piece is HDB supply data; a causal claim needs careful design |
| Real walking routes | Needs a routing service (OneMap routing asks for a token). Estimated times from straight-line distance are shown and labelled as estimates |
| Naming how good a school is, or which bus services stop nearby | Ranking schools is contentious and outside open data; bus services need LTA DataMall, which requires a key |
| HDB Annual Report and planning-area population context | Contextual rather than decision-changing; adds ingestion of PDF / non-API sources |
| SHAP explanations | Permutation importance plus the per-flat "what moves this estimate" view already explains estimates without extra dependencies |
| Town-level income benchmarks | SingStat publishes household income by planning area only in census years; mixing years would mislead |
| Genie space and Lakeview dashboard | SQL views exist; building them in the final workspace is a Demo Day polish task |
| Grants (EHG, CPF Housing Grant) in affordability | Eligibility rules are detailed; a wrong grant estimate is worse than none |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| data.gov.sg throttling or unreachable from the workspace | Bulk snapshot (1 request) by default; retries with backoff; paged fallback; uploaded-CSV path |
| Source schema change | Columns are checked against config before use; missing columns fail loudly, new ones are logged and kept |
| Free Edition quota exhaustion before the demo | Pipeline runs in minutes; app serves from a bundle, not the warehouse; Vercel copy of the app as backup |
| Model pickle incompatibility between training and app | `scikit-learn==1.7.2` pinned in the notebooks and `requirements.txt` |
| Over-claiming | Ranges everywhere, generated language avoids certainty, baseline published when it wins, policy shown as association only, disclaimers on every model page |
| Mix effects in town medians | Rankings use 4-room only; movers need 100+ sales; documented in the UI |
| A place source or OneMap unreachable | Each source is skipped with a note; school positions are cached; the whole places step is optional and the app hides what depends on it |
| Too much information on the Fair value page | Location is opt-in (pick a block), summarised in five rows, and the map layers can be switched off one by one |

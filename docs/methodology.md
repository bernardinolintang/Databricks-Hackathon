# Methodology

All numbers below come from the run on data pulled 3 October 2026 (241,920 transactions, Jan 2017 to Oct 2026; analysis through Sep 2026).

## 1. Cleaning (bronze → silver)

| Field | Raw form | Silver |
|---|---|---|
| `month` | `"2017-01"` | first-of-month date; `year`, `quarter`, `months_since_start` (0 = Jan 2017) |
| `remaining_lease` | `"61 years 04 months"`, `"70 years"`, `"61 years 1 month"` | `remaining_lease_years` (decimal); derived as 99 − (sale year − commencement year) if unreadable, with `remaining_lease_source` |
| `storey_range` | `"10 TO 12"` | `storey_low`, `storey_high`, `storey_mid` |
| `floor_area_sqm`, `resale_price` | text, mixed formats (`44`, `163.00`, `232000.0`) | float |
| `town`, `flat_type`, `flat_model` | text | trimmed, upper-case; `MULTI GENERATION` unified with `MULTI-GENERATION` |

Validity checks, each with a named reason in `invalid_reasons`: unparseable month, future month, missing town, missing flat type, price ≤ 0, floor area ≤ 0, floor area outside 20 to 400 sqm, unparseable storey band, impossible lease (outside 0 to 99 years, or commencement after the sale or before 1960).

Warnings that keep the row valid:

* `is_duplicate`: identical to an earlier row across all source columns (318 rows). HDB publishes no transaction ID, so two identical rows can be two sales in the same block, storey band and month at the same price. They are kept in all statistics.
* `is_price_outlier`: log price per sqm more than 5 robust SDs (median/MAD) from its town × flat type × year, in groups of 30+ (1,075 rows). The top end is premium DBSS projects; the bottom end is short-lease flats. Both are explained by features the model sees, so they are kept for training as well.
* `lease_mismatch`: reported remaining lease differs from the commencement-year derivation by more than 2 years (1 row).

`exclude_from_model` covers invalid rows and 1-room / multi-generation flats (178 sales, too few to model or validate).

**Partial month.** Records are by registration date, so the month of the pull is incomplete (212 rows for Oct 2026). Analytics and models stop at the last complete month, Sep 2026.

## 2. Market statistics

* **Medians** for prices; means are kept in `gold_market_monthly` for reference.
* **3-month pooled median**: the median of all sales in the trailing three months, not an average of three monthly medians. It is steadier for thin series.
* **YoY** for headline tiles: the latest three months against the same three months a year earlier, requiring 5+ sales on each side.
* **Momentum**: the latest three months against the three before.
* **Five-year change**: latest 12 months against the 12 months ending five years earlier.
* **Rankings** use 4-room flats (the most traded type) so towns are compared like for like. Movers require 100+ sales a year.
* Months with fewer than five sales are blanked in charts rather than plotted as noise.

## 3. Forecast

**Target.** Monthly median price per series, where a series is a town × flat type (plus ALL rollups). Eligibility: 36+ months with 5+ sales, 60+ sales in the last 12 months, at most 2 thin months in the last year. 104 series qualify.

**Features for the boosted model** (relative to the series' 3-month level, so one model fits every price scale): deviation of the last month from that level; log changes over 1, 2, 3, 6 and 12 months; 3-month vs 6- and 12-month averages; 24-month trend slope; log 3-month volume and its YoY change; national 3- and 12-month change; horizon; target calendar month; town and flat type as categorical features. Thin months are carried forward from the previous month, never interpolated, so no feature borrows from the future.

**Backtest.** Origins: Dec 2024, Mar 2025, Jun 2025, Sep 2025, Dec 2025 and Mar 2026. At each origin the boosted model is retrained on targets observed up to that origin, then every method forecasts 1 to 6 months ahead. Actuals are only months with 5+ sales. 3,702 forecasts in total.

| Method | MAE | RMSE | MAPE |
|---|---|---|---|
| Last month carried forward | $35,132 | $58,354 | 5.12% |
| **3-month average (baseline)** | **$31,198** | $53,151 | **4.52%** |
| Linear trend (24 months) | $37,955 | $58,312 | 5.69% |
| Gradient boosting | $31,627 | **$50,246** | 4.66% |

**Selection** is by MAPE because it is comparable across cheap and expensive series. MAPE weighs a given dollar miss on a 3-room flat more heavily than on an executive flat, and it is asymmetric (over-forecasts can exceed 100%, under-forecasts cannot), so MAE and RMSE are reported alongside it. The boosted model wins on RMSE (fewer big misses) but carries a +1.6% mean bias over the validation window. It learned the 2020 to 2024 run-up while the 2025 to 2026 market flattened. The baseline is published.

**Interval.** The 10th and 90th percentiles of the selected method's log errors, per horizon and per volume tier (under 10, 10 to 30, 30+ sales a month), so thin series get wider bands.

**Reading.** The sentence is generated from the 6-month change: within ±1.5% is "stay about the same", ±1.5 to 4% is "rise a little" or "dip a little", beyond that "rise" or "fall". If the 80% band spans today's level, the text says the direction is uncertain.

**MLflow.** Parent run `forecast_backtest` with parameters (horizon, folds, step, training period, validation period, origins, interval level, selection metric). One child run per method with MAE/RMSE/MAPE and per-horizon metrics. The boosted model is logged with its feature set. Metric, by-horizon and interval tables are logged as artifacts.

## 4. Fair value

**Why an index.** Tree models cannot extrapolate a time trend. Dividing price by a market index (national median $/sqm over the three months *before* the sale month) leaves the model to learn how attributes move price relative to the market. Estimating today means multiplying by the latest index. Because the index for month *m* uses only months before *m*, holdout sales never inform their own prediction.

**Inputs.** The flat's own details (town, flat type, flat model, floor area, storey midpoint, remaining lease, month) and eight measures of its block's location from section 8: metres to the nearest MRT exit, a mall, a hawker centre, a park and a park connector; kilometres to the city centre; primary schools within 1 km; bus stops within 400 m.

**Split.** Train Jan 2017 to Mar 2026 (227,942 sales). Holdout Apr to Sep 2026 (13,588 sales).

| Model | MAE | MAPE | Median error | Within 5% | Within 10% |
|---|---|---|---|---|---|
| Rule of thumb: recent town × type median $/sqm × floor area | $89,484 | 12.88% | 9.54% | 28.8% | 51.8% |
| Ridge: one-hot town / type / model + quadratic numerics, with location | $40,085 | 5.96% | 4.84% | 51.5% | 82.4% |
| Gradient boosting on the flat's own details only | $33,890 | 4.99% | 3.89% | 60.4% | 88.1% |
| **Gradient boosting with location** (HistGradientBoosting, native categoricals) | **$26,284** | **3.91%** | **2.99%** | **71.8%** | **93.8%** |

Selection is by MAE among fitted models; the rule of thumb is the yardstick. The selected model is refitted on all data before serving.

**What location adds.** The flat-only row is the same model with the eight location inputs removed, trained and scored on the same split in every run. Location cuts the mean error by 22% ($33,890 to $26,284) and the typical miss from 3.89% to 2.99%. Part of that gain is the named amenities and part is that the measures tell blocks in different parts of a town apart, so the model picks up neighbourhood differences it could not see before. The app reports the gain as "location", not as the value of any one amenity.

**Serving.** If the buyer names a block, the model gets that block's measures. If not, it gets the median of each measure over the last 24 months of sales of that town and flat type, and the result says it assumes a typical spot in the town. A block that could not be placed would be passed as missing, which the boosted trees handle natively.

**Usual range.** The 10th to 90th percentile of holdout log errors per flat type (about −6% to +5% for 4-room). It is labelled as "80% of recent sales in testing sold within this range of their estimate".

**Asking price.** "Below the usual range", "Within the usual range" or "Above the usual range", with the difference in dollars and percent. The wording avoids "good deal" or "overpriced".

**Explanations.**
* *Global:* permutation importance on 8,000 holdout sales (increase in mean absolute log error when a feature is shuffled). Floor area 27.5%, town 20.4%, remaining lease 19.8%, flat type 12.5%, flat model 5.6%, walk to the MRT 5.2%, storey 4.4%, distance to the city centre 2.5%, mall 0.9%, hawker centre 0.4%, park 0.3%, park connector 0.2%, bus stops 0.1%, primary schools 0.1%; transaction date ≈0 because the index already absorbs time. Town's share fell from 28% once location was added: some of what "town" used to stand for is now measured directly.
* *Local:* "what moves this estimate". Each of floor area, storey, remaining lease and flat model is swapped back to the typical flat's value for that town and type (medians of the last 24 months) and the change in estimate is shown. When a block is named, a "Location" line swaps all eight location measures to the town's typical values at once. Effects interact, so they do not sum exactly; the UI says so.

**Comparables.** Hard filter on the same town and flat type within the last 24 months. Rank by weighted Euclidean distance over floor area (10 sqm), storey midpoint (6 floors), remaining lease (8 years) and recency (12 months), plus a small penalty for a different flat model. When a block is named, distance from that block joins the ranking (600 m counts as one step), so nearby sales come first, and each result says how far away it is. Similarity = 100 × e^(−d/2).

## 5. Affordability

```
min downpayment   = (1 − LTV) × price
stamp duty (BSD)  = 1% × first 180k + 2% × next 180k + 3% × next 640k + 4% × next 500k + 5% × next 1.5M + 6% × rest
upfront needed    = min downpayment + BSD
loan              = LTV × price − max(0, savings − upfront needed)
repayment         = loan × r / (1 − (1 + r)^−n),   r = annual rate / 12, n = years × 12
repayment ratio   = repayment / monthly household income
price-to-income   = price / (12 × monthly household income)
```

Defaults model an HDB housing loan: 2.6% a year, 25 years, 75% LTV. They are editable in the app and set in `config.yaml`. Status: **Comfortable** at 25% or less (our own rule of thumb, labelled as such); **Within the 30% limit** at 25 to 30%; **Over the 30% limit** above that (the Mortgage Servicing Ratio cap for HDB flats).

**Budget.** The highest price at which savings cover the upfront amount and the loan is serviceable within the MSR cap (or the user's own cap), found by bisection. The UI says which constraint binds.

**Where can I afford?** Towns with 20+ sales of the chosen type in the last 12 months, priced at their median, ordered by repayment ratio. "Within reach" means the repayment fits the cap and savings cover the upfront amount.

**Benchmark.** SingStat M810361 series 5: median monthly household employment income of resident employed households, including employer CPF ($12,027 in 2025). Because it includes employer CPF, it is not identical to the gross income MSR uses. The comparison is indicative and the UI says so.

## 6. Policy marker

October 2024 marks the first BTO exercise under the Standard / Plus / Prime framework. Resale records have no classification field, and the framework governs new flats. FlatFair therefore shows only a marker and a before/after comparison of medians, described as an association, never an effect.

## 7. Town map

HDB does not publish town boundaries as shapes, so each town is drawn from the URA planning area it matches (Master Plan 2019, `d_4765db0e87b9c86336792efe8a1f7a66` on data.gov.sg). Two towns need a rule: **Central Area** is the 11 planning areas URA flags as Central Area, and **Kallang/Whampoa** is drawn as the Kallang planning area. The other 19 planning areas (catchment, industrial land, islands) are drawn in grey for context.

The pipeline projects the coordinates (equirectangular, scaled by the cosine of the latitude), simplifies each outline with Douglas-Peucker at about 45 m, drops islets under a minimum size, and writes SVG paths. That takes 40,505 source points down to 2,257 and 34 KB, with no GIS dependency. The shapes show where a town is. They are not legal boundaries.

Towns are shaded in five steps of one colour by median price, with breaks at the quintiles so each shade holds about the same number of towns. A town with fewer than 10 sales of the chosen flat type in 12 months is greyed out as "too few sales". The chosen town is filled solid.

## 8. Block locations and what is nearby

**Why.** Size, storey and lease describe the flat. What a buyer also pays for is where it is. Published hedonic studies of HDB resale prices put the walk to the MRT first among location factors (roughly 1% of price per 100 m, more in towns with few stations), followed by distance to the city centre, shopping malls and primary schools. FlatFair measures these for every block and lets the model decide how much each is worth.

**Placing each block.** Resale records name a block and a street (`706`, `PASIR RIS DR 10`) and carry no coordinates. HDB's Existing Building dataset has an outline for every block but names the street with a code (`PAD10K`-style). The codes are built from the street name, so the pipeline matches them:

1. For each street, find the codes whose blocks include that street's blocks, keeping only codes that start with the first two letters of the street's first real word (`JLN`, `LOR` and `KG` are skipped; `BT`, `UPP`, `C'WEALTH`, `TG` are spelled out).
2. Take the code that covers the most blocks. A tie goes to the code whose third letter matches the street's type or next word (`BEDOK NTH ST 2` is `BES`, not `BER`), then to the code whose blocks sit nearest the rest of the town.
3. A match more than 6 km from the rest of its town is rejected.
4. The block's position is the middle of its outline. A block missing from the outlines would sit at the middle of its street, and a street with no match at the middle of its town, both marked as approximate.

In this run all 580 streets matched one code each and all 9,755 blocks were placed on their own outline. As an independent check, 40 addresses (30 at random, 10 from the streets that needed the special rules) were looked up on OneMap: the median gap was 6 m and the largest 36 m.

**Places.** MRT and LRT station exits and bus stops (LTA), hawker centres in operation (NEA), parks, leaving out playgrounds and small open spaces (NParks), park connector lines (NParks, simplified from 32,694 to 5,347 points), schools (MOE; the table has addresses only, so each is placed from its postal code with OneMap) and shopping malls (OpenStreetMap `shop=mall`; a mall mapped as both a building and a point is kept once). Seven exits carry a line code where the station name should be (`CC9`, `CC30` to `CC32`, `DT4`, `DT18`, `NE18`); these are mapped to their station names.

**Measures per block.** Straight-line distance to the nearest MRT exit, the nearest exit of any station (MRT or LRT), bus stop, primary school, mall, hawker centre, park and park connector (nearest point on the line), and to Raffles Place as the city centre; the count of bus stops within 400 m and of primary schools within 1 km. The 1 km school radius is the distance MOE uses to give priority at Primary 1 registration.

**Walking time.** `minutes = ceil(straight-line metres × 1.3 ÷ 80)`. Real routes are longer than a straight line; 1.3 is a common allowance for a street network, and 80 m a minute is 4.8 km/h. So the 5 and 10 minute rings on the map are 308 m and 615 m across the ground. These are estimates and the app says so beside every map: a canal or expressway between the block and the station is not accounted for.

**Town comparisons.** "Typical walk to a station" is the median over sales of that flat type in the last 24 months, and "flats within a 10 min walk" is the share of those sales. Both use the nearest station of either kind, so LRT towns are not penalised.

**Limits.** Today's stations, schools and malls are applied to every year of sales, so the measures describe each block as it is now. OpenStreetMap's mall list is community-maintained. A school's position is its postal code's, which can be the gate or the middle of the campus.

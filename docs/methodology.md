# Methodology

All numbers below come from the run on data pulled 2 October 2026 (241,822 transactions, Jan 2017 to Oct 2026; analysis through Sep 2026).

## 1. Cleaning (bronze → silver)

| Field | Raw form | Silver |
|---|---|---|
| `month` | `"2017-01"` | first-of-month date; `year`, `quarter`, `months_since_start` (0 = Jan 2017) |
| `remaining_lease` | `"61 years 04 months"`, `"70 years"`, `"61 years 1 month"` | `remaining_lease_years` (decimal); derived as 99 − (sale year − commencement year) if unreadable, with `remaining_lease_source` |
| `storey_range` | `"10 TO 12"` | `storey_low`, `storey_high`, `storey_mid` |
| `floor_area_sqm`, `resale_price` | text, mixed formats (`44`, `163.00`, `232000.0`) | float |
| `town`, `flat_type`, `flat_model` | text | trimmed, upper-case; `MULTI GENERATION` unified with `MULTI-GENERATION` |

Validity checks, each with a named reason in `invalid_reasons`: unparseable month, future month, missing town, missing flat type, price ≤ 0, floor area ≤ 0, floor area outside 20–400 sqm, unparseable storey band, impossible lease (outside 0–99 years, or commencement after the sale or before 1960).

Warnings that keep the row valid:

* `is_duplicate`: identical to an earlier row across all source columns (318 rows). HDB publishes no transaction ID, so two identical rows can be two sales in the same block, storey band and month at the same price. They are kept in all statistics.
* `is_price_outlier`: log price per sqm more than 5 robust SDs (median/MAD) from its town × flat type × year, in groups of 30+ (1,078 rows). The top end is premium DBSS projects; the bottom end is short-lease flats. Both are explained by features the model sees, so they are kept for training as well.
* `lease_mismatch`: reported remaining lease differs from the commencement-year derivation by more than 2 years (1 row).

`exclude_from_model` covers invalid rows and 1-room / multi-generation flats (178 sales, too few to model or validate).

**Partial month.** Records are by registration date, so the month of the pull is incomplete (113 rows for Oct 2026). Analytics and models stop at the last complete month, Sep 2026.

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

**Backtest.** Origins: Dec 2024, Mar 2025, Jun 2025, Sep 2025, Dec 2025 and Mar 2026. At each origin the boosted model is retrained on targets observed up to that origin, then every method forecasts 1–6 months ahead. Actuals are only months with 5+ sales. 3,702 forecasts in total.

| Method | MAE | RMSE | MAPE |
|---|---|---|---|
| Last month carried forward | $35,132 | $58,354 | 5.12% |
| **3-month average (baseline)** | **$31,198** | $53,151 | **4.52%** |
| Linear trend (24 months) | $37,955 | $58,312 | 5.69% |
| Gradient boosting | $31,627 | **$50,246** | 4.66% |

**Selection** is by MAPE because it is comparable across cheap and expensive series. MAPE weighs a given dollar miss on a 3-room flat more heavily than on an executive flat, and it is asymmetric (over-forecasts can exceed 100%, under-forecasts cannot), so MAE and RMSE are reported alongside it. The boosted model wins on RMSE (fewer big misses) but carries a +1.6% mean bias over the validation window. It learned the 2020–24 run-up while the 2025–26 market flattened. The baseline is published.

**Interval.** The 10th and 90th percentiles of the selected method's log errors, per horizon and per volume tier (under 10, 10–30, 30+ sales a month), so thin series get wider bands.

**Reading.** The sentence is generated from the 6-month change: within ±1.5% is "remain broadly stable", ±1.5–4% is "rise/ease modestly", beyond that "rise/decline". If the 80% band spans today's level, the text says the direction is uncertain.

**MLflow.** Parent run `forecast_backtest` with parameters (horizon, folds, step, training period, validation period, origins, interval level, selection metric). One child run per method with MAE/RMSE/MAPE and per-horizon metrics. The boosted model is logged with its feature set. Metric, by-horizon and interval tables are logged as artifacts.

## 4. Fair value

**Why an index.** Tree models cannot extrapolate a time trend. Dividing price by a market index (national median $/sqm over the three months *before* the sale month) leaves the model to learn how attributes move price relative to the market. Estimating today means multiplying by the latest index. Because the index for month *m* uses only months before *m*, holdout sales never inform their own prediction.

**Split.** Train Jan 2017 to Mar 2026 (227,942 sales). Holdout Apr–Sep 2026 (13,589 sales).

| Model | MAE | MAPE | Median error | Within 5% | Within 10% |
|---|---|---|---|---|---|
| Rule of thumb: recent town × type median $/sqm × floor area | $89,481 | 12.88% | 9.54% | 28.8% | 51.8% |
| Ridge: one-hot town / type / model + quadratic numerics | $50,327 | 7.58% | 6.22% | 41.5% | 71.8% |
| **Gradient boosting** (HistGradientBoosting, native categoricals) | **$33,892** | **4.99%** | **3.89%** | **60.4%** | **88.1%** |

Selection is by MAE among fitted models; the rule of thumb is the yardstick. The selected model is refitted on all data before serving.

**Expected range.** The 10th–90th percentile of holdout log errors per flat type (about −8% to +7% for 4-room). It is labelled as "80% of recent sales in testing sold within this range of their estimate".

**Asking price.** Below the range, within it, or above it, with the difference in dollars and percent. The wording avoids "good deal" or "overpriced".

**Explanations.**
* *Global:* permutation importance on 8,000 holdout sales (increase in mean absolute log error when a feature is shuffled). Floor area 31%, town 28%, remaining lease 20%, flat type 11%, flat model 7%, storey 4%; transaction date ≈0 because the index already absorbs time.
* *Local:* "what moves this estimate". Each of floor area, storey, remaining lease and flat model is swapped back to the typical flat's value for that town and type (medians of the last 24 months) and the change in estimate is shown. Effects interact, so they do not sum exactly; the UI says so.

**Comparables.** Hard filter on the same town and flat type within the last 24 months. Rank by weighted Euclidean distance over floor area (10 sqm), storey midpoint (6 floors), remaining lease (8 years) and recency (12 months), plus a small penalty for a different flat model. Similarity = 100 × e^(−d/2).

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

Defaults model an HDB housing loan: 2.6% a year, 25 years, 75% LTV. They are editable in the app and set in `config.yaml`. Status: **Comfortable** at 25% or less (an illustrative product threshold, labelled as such); **Within the MSR limit** at 25–30%; **Above the MSR limit** over 30% (the Mortgage Servicing Ratio cap for HDB flats).

**Budget.** The highest price at which savings cover the upfront amount and the loan is serviceable within the MSR cap (or the user's own cap), found by bisection. The UI says which constraint binds.

**Where can I afford?** Towns with 20+ sales of the chosen type in the last 12 months, priced at their median, ordered by repayment ratio. "Within reach" means the repayment fits the cap and savings cover the upfront amount.

**Benchmark.** SingStat M810361 series 5: median monthly household employment income of resident employed households, including employer CPF ($12,027 in 2025). Because it includes employer CPF, it is not identical to the gross income MSR uses. The comparison is indicative and the UI says so.

## 6. Policy marker

October 2024 marks the first BTO exercise under the Standard / Plus / Prime framework. Resale records have no classification field, and the framework governs new flats. FlatFair therefore shows only a marker and a before/after comparison of medians, described as an association, never an effect.

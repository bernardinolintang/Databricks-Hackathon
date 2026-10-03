# Data dictionary

All tables live in `workspace.flatfair` on Databricks (or `data/<layer>/<table>.parquet` locally). `ALL` in `town` or `flat_type` marks a rollup across every value.

## Bronze

### bronze_hdb_resale
Raw snapshot from data.gov.sg; every source column is text, exactly as published.

| Column | Example | Notes |
|---|---|---|
| month | `2017-01` | registration month |
| town | `ANG MO KIO` | 26 towns |
| flat_type | `4 ROOM` | 1 ROOM … EXECUTIVE, MULTI-GENERATION |
| block | `406` | |
| street_name | `ANG MO KIO AVE 10` | |
| storey_range | `10 TO 12` | 3-storey bands |
| floor_area_sqm | `44`, `163.00` | mixed formats |
| flat_model | `Improved` | 21 models |
| lease_commence_date | `1979` | year |
| remaining_lease | `61 years 04 months` | three text formats |
| resale_price | `232000` | |
| _ingested_at | ISO timestamp | added at ingestion |
| _source | `data.gov.sg:<id>:bulk` | added at ingestion |

### bronze_ingestion_log
One row per run: `dataset_id, method, rows, api_total_rows, columns, missing_columns, unexpected_columns, source_last_updated, ingested_at, snapshot_sha256, pages, notes, income_benchmark`.

### bronze_income
SingStat M810361 series 5: `year, median_monthly_household_income, series_name, unit, table_id, table_title, source_last_updated, _ingested_at`.

## Silver

### silver_hdb_resale
Every bronze row, typed and flagged.

| Column | Type | Meaning |
|---|---|---|
| source_row | int | position in bronze |
| month | date | first of month |
| year, quarter | int | |
| months_since_start | int | 0 = Jan 2017 |
| town, flat_type, flat_model, block, street_name, storey_range | string | trimmed, upper-case |
| storey_low, storey_high, storey_mid | float | from `storey_range` |
| floor_area_sqm, resale_price | float | |
| lease_commence_year | int | |
| remaining_lease_years | float | decimal years |
| remaining_lease_source | string | `reported` or `derived` |
| lease_age_years | float | sale date − commencement |
| price_per_sqm | float | |
| invalid_reasons | string | `;`-separated check names, empty if valid |
| is_valid | bool | passed every check |
| lease_mismatch | bool | reported vs derived lease differ by > 2 years |
| is_duplicate | bool | identical to an earlier row (kept) |
| is_price_outlier | bool | unusual $/sqm for town × type × year (kept) |
| model_exclusion_reason | string | `invalid_record`, `sparse_flat_type` or empty |
| exclude_from_model | bool | |
| pulled_at | timestamp | when bronze was ingested |

## Gold

### gold_market_monthly
Grain: month × town × flat_type (with ALL rollups), on a complete month grid.
`transactions, median_price, mean_price, p25_price, p75_price, median_psm, median_floor_area, median_price_3m, transactions_3m, mom_pct, yoy_pct, yoy_pct_3m, rolling_avg_3m, rolling_avg_6m`

### gold_town_summary / gold_flat_type_summary
Grain: town × flat_type (flat-type summary = town ALL).
`as_of_month, median_price_12m, median_psm_12m, transactions_12m, median_price_3m, median_psm_3m, transactions_3m, median_price_prev12m, median_price_5y_ago, yoy_pct, yoy_pct_3m, momentum_pct, change_5y_pct`

### gold_market_index
`month, market_index_psm` (median $/sqm of the three preceding months), `index_transactions`. Includes the month after the data ends ("today").

### gold_affordability
Grain: town × flat_type at the latest official median income.
`median_price_12m, benchmark_year, benchmark_monthly_income, price_to_income, loan, monthly_repayment, repayment_ratio, status`

### gold_comparable_transactions
Valid transactions with `month, year, town, flat_type, flat_model, block, street_name, storey_range, storey_mid, floor_area_sqm, remaining_lease_years, resale_price, price_per_sqm, is_duplicate, is_price_outlier`.

### gold_forecast
`town, flat_type, origin_month, month, horizon (1–6), forecast_price, lower_price, upper_price (80%), recent_level_price, volume_tier, method`

### gold_forecast_features / gold_forecast_backtest / gold_forecast_metrics
Features per series × origin × horizon; every backtest prediction with actuals; MAE / RMSE / MAPE per method with `selected`.

### gold_fair_value_metrics / gold_fair_value_importance
Holdout `mae, rmse, mape, median_ape, within_5pct, within_10pct, n, mae_vs_baseline_pct, selected` per model; permutation `importance` and `share_pct` per feature.

### gold_data_quality
`checked_at, total_rows, valid_rows, invalid_rows, duplicate_rows, missing_values_total, price_outlier_rows, latest_month, checks_passed, checks_total, summary_json`.

## Serving bundle (`/Volumes/workspace/flatfair/serving`, `data/serving`)
`transactions.parquet, market_monthly.parquet, town_summary.parquet, forecast.parquet, income.parquet, fair_value_model.joblib, meta.json` (quality summary, model metrics, intervals, importance, assumptions, sources).

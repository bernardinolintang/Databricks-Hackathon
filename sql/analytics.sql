-- FlatFair analytics queries for Databricks SQL (dashboards and a Genie space).
-- Tables live in workspace.flatfair; run notebooks 01-07 first.

-- 1. National trend: monthly median and 3-month pooled median, all flats
SELECT month, median_price, median_price_3m, transactions
FROM workspace.flatfair.gold_market_monthly
WHERE town = 'ALL' AND flat_type = 'ALL'
ORDER BY month;

-- 2. Most and least expensive towns for 4-room flats (last 12 months, 50+ sales)
SELECT town, median_price_12m, median_psm_12m, transactions_12m, yoy_pct, change_5y_pct
FROM workspace.flatfair.gold_town_summary
WHERE flat_type = '4 ROOM' AND transactions_12m >= 50
ORDER BY median_price_12m DESC;

-- 3. Momentum: last 3 months vs the 3 before, 4-room, towns with 100+ sales a year
SELECT town, median_price_3m, momentum_pct, yoy_pct
FROM workspace.flatfair.gold_town_summary
WHERE flat_type = '4 ROOM' AND transactions_12m >= 100
ORDER BY momentum_pct DESC;

-- 4. Affordability at the official median household income
SELECT town, flat_type, median_price_12m, monthly_repayment,
       ROUND(repayment_ratio * 100, 1) AS repayment_pct_of_income,
       price_to_income, status
FROM workspace.flatfair.gold_affordability
WHERE flat_type IN ('3 ROOM', '4 ROOM', '5 ROOM')
ORDER BY flat_type, repayment_ratio;

-- 5. Before and after the October 2024 classification change (association only)
SELECT CASE WHEN month < DATE'2024-10-01' THEN '12 months before' ELSE '12 months after' END AS period,
       flat_type,
       PERCENTILE(resale_price, 0.5) AS median_price,
       COUNT(*)                      AS transactions
FROM workspace.flatfair.silver_hdb_resale
WHERE is_valid
  AND month >= DATE'2023-10-01' AND month < DATE'2025-10-01'
  AND flat_type IN ('3 ROOM', '4 ROOM', '5 ROOM')
GROUP BY 1, 2
ORDER BY flat_type, period DESC;

-- 6. Forecast scorecard: which method won the backtest
SELECT method, ROUND(mape, 2) AS mape_pct, ROUND(mae) AS mae_sgd, ROUND(rmse) AS rmse_sgd, selected
FROM workspace.flatfair.gold_forecast_metrics
ORDER BY mape;

-- 7. Six-month outlook for every series
SELECT * FROM workspace.flatfair.v_forecast_vs_now ORDER BY town, flat_type;

-- 8. Data quality: what was flagged in the latest run
SELECT checked_at, total_rows, valid_rows, invalid_rows, duplicate_rows,
       price_outlier_rows, missing_values_total, latest_month, checks_passed, checks_total
FROM workspace.flatfair.gold_data_quality;

-- 9. Ingestion audit trail
SELECT ingested_at, method, rows, api_total_rows, source_last_updated, snapshot_sha256
FROM workspace.flatfair.bronze_ingestion_log
ORDER BY ingested_at DESC;

# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · SQL views, lineage and governance
# MAGIC Spark SQL views over the gold tables for Databricks SQL dashboards and a Genie space. Because they are defined in SQL
# MAGIC on Unity Catalog tables, **Catalog Explorer shows their lineage** back to silver and bronze.
# MAGIC Table comments and tags were applied by the pipeline on every write (`src/flatfair/governance.py`).

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW workspace.flatfair.v_town_4room_latest
# MAGIC COMMENT 'Current 4-room market by town: price, momentum, five-year change and repayment share for the median household.'
# MAGIC AS
# MAGIC SELECT s.town,
# MAGIC        s.median_price_12m,
# MAGIC        s.median_psm_12m,
# MAGIC        s.transactions_12m,
# MAGIC        s.yoy_pct,
# MAGIC        s.momentum_pct,
# MAGIC        s.change_5y_pct,
# MAGIC        a.monthly_repayment,
# MAGIC        a.repayment_ratio
# MAGIC FROM workspace.flatfair.gold_town_summary s
# MAGIC LEFT JOIN workspace.flatfair.gold_affordability a USING (town, flat_type)
# MAGIC WHERE s.flat_type = '4 ROOM'

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW workspace.flatfair.v_monthly_from_silver
# MAGIC COMMENT 'Monthly median price and volume computed directly from silver in SQL; cross-checks gold_market_monthly.'
# MAGIC AS
# MAGIC SELECT month,
# MAGIC        town,
# MAGIC        flat_type,
# MAGIC        COUNT(*)                         AS transactions,
# MAGIC        PERCENTILE(resale_price, 0.5)    AS median_price,
# MAGIC        PERCENTILE(price_per_sqm, 0.5)   AS median_psm
# MAGIC FROM workspace.flatfair.silver_hdb_resale
# MAGIC WHERE is_valid
# MAGIC GROUP BY month, town, flat_type

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW workspace.flatfair.v_forecast_vs_now
# MAGIC COMMENT 'Six-month-ahead forecast against the recent level, with the 80% range, per series.'
# MAGIC AS
# MAGIC SELECT town,
# MAGIC        flat_type,
# MAGIC        month                                                  AS forecast_month,
# MAGIC        recent_level_price,
# MAGIC        forecast_price,
# MAGIC        lower_price,
# MAGIC        upper_price,
# MAGIC        ROUND((forecast_price / recent_level_price - 1) * 100, 2) AS change_pct,
# MAGIC        method
# MAGIC FROM workspace.flatfair.gold_forecast
# MAGIC WHERE horizon = 6

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Sanity check: SQL medians agree with the pandas-built gold table
# MAGIC SELECT g.town, g.flat_type, g.month, g.median_price AS gold_median, v.median_price AS sql_median
# MAGIC FROM workspace.flatfair.gold_market_monthly g
# MAGIC JOIN workspace.flatfair.v_monthly_from_silver v USING (town, flat_type, month)
# MAGIC WHERE g.town = 'TAMPINES' AND g.flat_type = '4 ROOM'
# MAGIC ORDER BY g.month DESC
# MAGIC LIMIT 6

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW TABLES IN workspace.flatfair

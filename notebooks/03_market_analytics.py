# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Silver → Gold: market analytics and affordability
# MAGIC Builds the analysis-ready tables the app and Databricks SQL read:
# MAGIC
# MAGIC * `gold_market_monthly`: median / mean / quartiles / volume / $ per sqm by month × town × flat type (with ALL rollups), MoM, YoY, rolling averages
# MAGIC * `gold_town_summary`, `gold_flat_type_summary`: the current market in one row per segment
# MAGIC * `gold_market_index`: national $ per sqm from *earlier* months only (keeps the fair value model leak-free)
# MAGIC * `gold_affordability`: repayment and price-to-income at the official median household income
# MAGIC * `gold_comparable_transactions`: the search space for comparable sales
# MAGIC * `bronze_planning_areas` and `gold_town_map`: URA planning area boundaries from data.gov.sg, simplified into the town map the app draws
# MAGIC
# MAGIC Medians, not means: a few million-dollar sales pull a town's mean a long way.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

pipeline.step_gold(store, cfg)

# COMMAND ----------

# Town map. Optional: if data.gov.sg is unreachable the app shows a town list instead.
# To use a file, download the GeoJSON from the dataset page, upload it to the volume and set the widget.
dbutils.widgets.text("boundaries_file", "", "Uploaded planning area GeoJSON (optional)")
pipeline.step_boundaries(store, cfg, source_file=dbutils.widgets.get("boundaries_file").strip() or None)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- 4-room towns: price, momentum and affordability for the median household
# MAGIC SELECT s.town,
# MAGIC        s.median_price_12m,
# MAGIC        s.yoy_pct,
# MAGIC        s.change_5y_pct,
# MAGIC        a.monthly_repayment,
# MAGIC        ROUND(a.repayment_ratio * 100, 1) AS repayment_pct_of_median_income
# MAGIC FROM workspace.flatfair.gold_town_summary s
# MAGIC JOIN workspace.flatfair.gold_affordability a USING (town, flat_type)
# MAGIC WHERE s.flat_type = '4 ROOM' AND s.transactions_12m >= 50
# MAGIC ORDER BY s.median_price_12m

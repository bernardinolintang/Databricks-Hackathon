# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Bronze → Silver, plus data quality
# MAGIC Types every field, standardises names, parses `"61 years 04 months"` into decimal years and `"10 TO 12"` into a storey
# MAGIC midpoint, and runs nine validity checks. **No row is deleted**: problems become flags with named reasons.
# MAGIC
# MAGIC | Flag | Meaning | Used for modelling? |
# MAGIC |---|---|---|
# MAGIC | `is_valid = false` | failed a check (price ≤ 0, bad month, impossible lease, …) | excluded |
# MAGIC | `is_duplicate` | identical to an earlier row; HDB publishes no transaction ID, so these may be genuine twin sales | kept |
# MAGIC | `is_price_outlier` | price per sqm > 5 robust SDs from its town × type × year | kept (mostly premium or short-lease flats) |
# MAGIC | `exclude_from_model` | invalid, or 1-room / multi-generation (too few sales) | excluded |
# MAGIC
# MAGIC The month containing the pull date is still being registered, so analysis stops at the last complete month.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

summary = pipeline.step_transform(store, cfg)
print(f"{summary['valid_rows']:,} valid of {summary['total_rows']:,} | duplicates {summary['duplicate_rows']:,} | "
      f"unusual prices {summary['price_outlier_rows']:,} | latest complete month {summary['last_complete_month']}")
display(spark.createDataFrame([(c["name"], c["description"], c["passed"], c["failed_rows"]) for c in summary["checks"]],
                              "check string, description string, passed boolean, failed_rows long"))

# COMMAND ----------

# MAGIC %sql
# MAGIC -- What was flagged, and why
# MAGIC SELECT
# MAGIC   COUNT(*)                                        AS total_rows,
# MAGIC   SUM(CASE WHEN is_valid THEN 0 ELSE 1 END)       AS invalid_rows,
# MAGIC   SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END)   AS exact_duplicates,
# MAGIC   SUM(CASE WHEN is_price_outlier THEN 1 ELSE 0 END) AS unusual_price_per_sqm,
# MAGIC   SUM(CASE WHEN lease_mismatch THEN 1 ELSE 0 END) AS lease_text_vs_year_mismatch,
# MAGIC   SUM(CASE WHEN exclude_from_model THEN 1 ELSE 0 END) AS excluded_from_model
# MAGIC FROM workspace.flatfair.silver_hdb_resale

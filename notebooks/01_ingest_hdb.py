# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Ingest → Bronze
# MAGIC Pulls the full **HDB resale flat prices** dataset (`d_8b84c4ee58e3cfc0ece0d773c8ca6abc`) from data.gov.sg and the
# MAGIC **SingStat M810361** household income table, and lands them unchanged in Delta.
# MAGIC
# MAGIC * Inspects the live schema before trusting any column; fails loudly if an expected column disappears.
# MAGIC * `bulk` = one snapshot download, verified against the datastore row count. `api` = pages through `datastore_search` with retries.
# MAGIC * Full-snapshot overwrite: rerunning never duplicates rows. Every run is appended to `bronze_ingestion_log`.
# MAGIC * If the workspace cannot reach data.gov.sg, download the CSV from the dataset page, upload it to the serving volume,
# MAGIC   and set the `source_csv` widget to its path.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

dbutils.widgets.dropdown("method", "bulk", ["bulk", "api"], "Ingestion method")
dbutils.widgets.text("source_csv", "", "Uploaded CSV path (optional)")
method = dbutils.widgets.get("method")
source_csv = dbutils.widgets.get("source_csv").strip() or None

record = pipeline.step_ingest(store, cfg, method=method, source_csv=source_csv)
{k: record[k] for k in ("method", "rows", "api_total_rows", "missing_columns", "unexpected_columns", "source_last_updated", "notes", "income_benchmark")}

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT month, town, flat_type, storey_range, floor_area_sqm, remaining_lease, resale_price
# MAGIC FROM workspace.flatfair.bronze_hdb_resale
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT ingested_at, method, rows, api_total_rows, source_last_updated, snapshot_sha256
# MAGIC FROM workspace.flatfair.bronze_ingestion_log
# MAGIC ORDER BY ingested_at DESC

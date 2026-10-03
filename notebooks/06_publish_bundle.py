# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Publish the serving bundle
# MAGIC Writes the small set of files the FlatFair app loads at start-up to `/Volumes/workspace/flatfair/serving`:
# MAGIC transactions, gold tables, forecast, model and a `meta.json` with data quality, metrics and assumptions.
# MAGIC
# MAGIC The app (Databricks Apps, see `app.yaml`) copies this folder once and answers every request from memory, so a
# MAGIC 2X-Small warehouse is never on the request path. After this notebook: **Compute → Apps → flatfair → Deploy**.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

result = pipeline.step_publish(store, cfg, SERVING_DIR)
result

# COMMAND ----------

display(dbutils.fs.ls(str(SERVING_DIR)))

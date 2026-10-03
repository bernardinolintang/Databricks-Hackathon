# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Six-month forecast (MLflow)
# MAGIC Forecasts the monthly median price for ~100 town × flat type series, 1–6 months ahead.
# MAGIC
# MAGIC **Validation is time-based, never random**: a rolling-origin backtest from six past starting points. At each origin
# MAGIC the models see only data up to that month, then forecast the next six. Four methods compete:
# MAGIC
# MAGIC | Method | Idea |
# MAGIC |---|---|
# MAGIC | `naive_last` | last month carried forward |
# MAGIC | `rolling_3m` | average of the last three months (**baseline**) |
# MAGIC | `linear_trend` | straight line through the last 24 months |
# MAGIC | `gbm` | one gradient-boosted model across all series, lag / momentum / volume features |
# MAGIC
# MAGIC The lowest backtest MAPE wins and its own past errors set the 80% range. Every method is a child run in MLflow.
# MAGIC In the 2025–26 data the baseline won narrowly: the boosted model learned 2020–24 momentum and leaned high as the
# MAGIC market flattened. FlatFair publishes what the evidence supports.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

meta = pipeline.step_forecast(store, cfg, SERVING_DIR, track=True)
print("Selected method:", meta["selected_method"], "| MLflow run:", meta["mlflow_run_id"])
display(spark.table(f"{CATALOG}.{SCHEMA}.gold_forecast_metrics"))

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT month, forecast_price, lower_price, upper_price
# MAGIC FROM workspace.flatfair.gold_forecast
# MAGIC WHERE town = 'TAMPINES' AND flat_type = '4 ROOM'
# MAGIC ORDER BY month

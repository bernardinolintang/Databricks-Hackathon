# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Fair value model (MLflow + Unity Catalog registry)
# MAGIC Estimates what a described flat would sell for today.
# MAGIC
# MAGIC * **Target**: `log(price / market index)`, where the index is the national $ per sqm of the *preceding* three months.
# MAGIC   The model learns how attributes move price; the latest index brings the estimate to today's level.
# MAGIC * **Inputs**: town, flat type, flat model, floor area, storey midpoint, remaining lease, transaction month.
# MAGIC * **Validation**: train up to six months ago, test on the last six months of sales the model never saw.
# MAGIC * **Candidates**: a hand rule (recent town × type $ per sqm × size), ridge regression, gradient boosting.
# MAGIC * **Range**: the central 80% of holdout errors, per flat type. **Explanation**: permutation importance.
# MAGIC
# MAGIC The selected model is refitted on all data, registered as `workspace.flatfair.flatfair_fair_value`, and saved to the
# MAGIC serving volume for the app.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.7.2 pyyaml requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

meta = pipeline.step_fair_value(store, cfg, SERVING_DIR, track=True)
print("Selected:", meta["selected_model"], "| MLflow run:", meta["mlflow_run_id"])
display(spark.table(f"{CATALOG}.{SCHEMA}.gold_fair_value_metrics"))
display(spark.table(f"{CATALOG}.{SCHEMA}.gold_fair_value_importance"))

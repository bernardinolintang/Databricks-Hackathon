# Databricks notebook source
# MAGIC %md
# MAGIC # FlatFair · shared setup
# MAGIC Every pipeline notebook starts with `%run ./00_setup`. It puts the repo's `src/` package on the path,
# MAGIC loads `config/config.yaml`, and points storage at Unity Catalog:
# MAGIC
# MAGIC | What | Where |
# MAGIC |---|---|
# MAGIC | Delta tables | `workspace.flatfair.*` (bronze / silver / gold) |
# MAGIC | Serving bundle for the app | `/Volumes/workspace/flatfair/serving` |
# MAGIC | MLflow experiment | `/Shared/flatfair` |
# MAGIC
# MAGIC Run this repo as a **Git folder** so the notebooks can import `src/flatfair`.

# COMMAND ----------

import logging
import os
import sys
from pathlib import Path

# In a Git folder the working directory is the notebook's folder: notebooks/ -> repo root.
REPO = Path(os.getcwd()).parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", force=True)

from flatfair import pipeline  # noqa: E402
from flatfair.config import load_config  # noqa: E402
from flatfair.storage import DeltaStore  # noqa: E402

cfg = load_config(str(REPO / "config" / "config.yaml"))
CATALOG = cfg["storage"]["catalog"]
SCHEMA = cfg["storage"]["schema"]
VOLUME = cfg["storage"]["serving_volume"]

store = DeltaStore(spark, CATALOG, SCHEMA)  # creates the schema if needed
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`.`{VOLUME}`")
SERVING_DIR = Path(f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}")

print(f"Repo:    {REPO}")
print(f"Tables:  {CATALOG}.{SCHEMA}")
print(f"Serving: {SERVING_DIR}")

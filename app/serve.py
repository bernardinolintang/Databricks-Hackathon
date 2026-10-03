"""Entrypoint for Databricks Apps, which assigns the port via DATABRICKS_APP_PORT."""

import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))

"""Table storage behind one small interface.

The transformation code is plain pandas (the dataset is ~250k rows), so the only
thing that differs between a laptop and Databricks is where tables live:
parquet files locally, Delta tables in Unity Catalog on Databricks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

log = logging.getLogger(__name__)


class TableStore(Protocol):
    def write(self, name: str, df: pd.DataFrame, mode: str = "overwrite") -> None: ...
    def read(self, name: str) -> pd.DataFrame: ...
    def exists(self, name: str) -> bool: ...
    def describe(self) -> str: ...


def _layer(name: str) -> str:
    layer = name.split("_", 1)[0]
    if layer not in {"bronze", "silver", "gold"}:
        raise ValueError(f"Table '{name}' must start with bronze_, silver_ or gold_")
    return layer


class LocalStore:
    """Parquet files under <base>/<layer>/<table>.parquet."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def _path(self, name: str) -> Path:
        return self.base_dir / _layer(name) / f"{name}.parquet"

    def write(self, name: str, df: pd.DataFrame, mode: str = "overwrite") -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and path.exists():
            df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
        elif mode not in {"overwrite", "append"}:
            raise ValueError(f"Unsupported write mode '{mode}'")
        df.to_parquet(path, index=False)
        log.info("Wrote %s rows to %s", f"{len(df):,}", path)

    def read(self, name: str) -> pd.DataFrame:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"Table '{name}' not found at {path}. Run the earlier pipeline step first.")
        return pd.read_parquet(path)

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def describe(self) -> str:
        return f"local parquet at {self.base_dir}"


class DeltaStore:
    """Delta tables in Unity Catalog: <catalog>.<schema>.<table>."""

    def __init__(self, spark: Any, catalog: str, schema: str):
        self.spark = spark
        self.catalog = catalog
        self.schema = schema
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")

    def _fqn(self, name: str) -> str:
        _layer(name)
        return f"`{self.catalog}`.`{self.schema}`.`{name}`"

    @staticmethod
    def _spark_safe(df: pd.DataFrame) -> pd.DataFrame:
        """pandas nullable dtypes (Int64, string, boolean) do not all convert
        cleanly to Spark; fall back to plain numpy/object columns."""
        out = df.copy()
        for column in out.columns:
            dtype = out[column].dtype
            if pd.api.types.is_extension_array_dtype(dtype) and not isinstance(dtype, pd.DatetimeTZDtype):
                has_na = out[column].isna().any()
                if pd.api.types.is_integer_dtype(dtype):
                    out[column] = out[column].astype("float64" if has_na else "int64")
                elif pd.api.types.is_bool_dtype(dtype) and not has_na:
                    out[column] = out[column].astype(bool)
                else:
                    out[column] = out[column].astype(object).where(out[column].notna(), None)
        return out

    def write(self, name: str, df: pd.DataFrame, mode: str = "overwrite") -> None:
        if mode not in {"overwrite", "append"}:
            raise ValueError(f"Unsupported write mode '{mode}'")
        writer = self.spark.createDataFrame(self._spark_safe(df)).write.format("delta").mode(mode)
        if mode == "overwrite":
            # Schemas evolve as the pipeline grows; a full-snapshot table may be replaced.
            writer = writer.option("overwriteSchema", "true")
        writer.saveAsTable(self._fqn(name))
        log.info("Wrote %s rows to %s", f"{len(df):,}", self._fqn(name))
        from flatfair import governance

        governance.apply(self.spark, self._fqn(name), name)

    def read(self, name: str) -> pd.DataFrame:
        return self.spark.table(self._fqn(name)).toPandas()

    def exists(self, name: str) -> bool:
        return bool(self.spark.catalog.tableExists(f"{self.catalog}.{self.schema}.{name}"))

    def describe(self) -> str:
        return f"Delta tables in {self.catalog}.{self.schema}"


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def read_json(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)

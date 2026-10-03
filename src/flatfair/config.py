"""Load the single YAML config used by the pipeline, the notebooks and the app."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# src/flatfair/config.py -> repo root is two levels above the package.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.environ.get("FLATFAIR_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        raise FileNotFoundError(f"FlatFair config not found at {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def local_data_dir(cfg: dict[str, Any]) -> Path:
    """Local data root; FLATFAIR_DATA_DIR overrides the config for tests."""
    override = os.environ.get("FLATFAIR_DATA_DIR")
    base = Path(override) if override else REPO_ROOT / cfg["storage"]["local_dir"]
    return base

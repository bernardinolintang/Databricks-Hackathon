"""Small helpers shared by the API services."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

ALL = "ALL"


class InputError(ValueError):
    """A request parameter is invalid; returned to the client as HTTP 400."""


def to_json(value: Any) -> Any:
    """Make pandas/numpy output JSON-safe: NaN -> None, numpy scalars -> Python."""
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return to_json(value.to_dict("records"))
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.strftime("%Y-%m") if isinstance(value, pd.Timestamp) else value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value is pd.NaT or value is pd.NA:
        return None
    return value


def month_label(month: pd.Timestamp) -> str:
    return pd.Timestamp(month).strftime("%b %Y")


def title_case(name: str) -> str:
    """'KALLANG/WHAMPOA' -> 'Kallang/Whampoa', '4 ROOM' -> '4-room'."""
    if name == ALL:
        return "All"
    if name.endswith(" ROOM"):
        return name.split(" ")[0] + "-room"
    special = {"MULTI-GENERATION": "Multi-generation", "EXECUTIVE": "Executive", "CENTRAL AREA": "Central Area"}
    if name in special:
        return special[name]
    return "/".join(part.title() for part in name.split("/"))


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or not old or pd.isna(new) or pd.isna(old):
        return None
    return round((new / old - 1) * 100, 2)


def validate_choice(value: str, allowed: list[str], name: str) -> str:
    value = (value or ALL).strip().upper()
    if value != ALL and value not in allowed:
        raise InputError(f"Unknown {name} '{value}'")
    return value

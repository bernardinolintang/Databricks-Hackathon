import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from flatfair.config import load_config  # noqa: E402

SERVING_DIR = ROOT / "data" / "serving"


@pytest.fixture(scope="session")
def cfg():
    return load_config()


def make_bronze(rows: list[dict]) -> pd.DataFrame:
    """A bronze-shaped frame: every source column as text, like the API returns."""
    defaults = {
        "month": "2024-01",
        "town": "TAMPINES",
        "flat_type": "4 ROOM",
        "block": "101",
        "street_name": "TAMPINES ST 11",
        "storey_range": "07 TO 09",
        "floor_area_sqm": "92",
        "flat_model": "Model A",
        "lease_commence_date": "1990",
        "remaining_lease": "65 years 03 months",
        "resale_price": "550000",
    }
    frame = pd.DataFrame([{**defaults, **row} for row in rows]).astype(str)
    frame["_ingested_at"] = "2024-06-15T00:00:00+00:00"
    return frame


@pytest.fixture
def synthetic_transactions():
    """Two towns, three flat types, 48 months, with a gentle price trend."""
    rng = np.random.default_rng(7)
    records = []
    sizes = {"3 ROOM": 67, "4 ROOM": 92, "5 ROOM": 112}
    for month in pd.date_range("2020-01-01", periods=48, freq="MS"):
        for town, premium in (("TAMPINES", 1.0), ("QUEENSTOWN", 1.5)):
            for flat_type, size in sizes.items():
                for _ in range(12):
                    lease = rng.uniform(55, 95)
                    storey = float(rng.choice([2, 5, 8, 11, 14]))
                    area = size + rng.normal(0, 4)
                    psm = 5000 * premium * (1 + 0.004 * len(records) / 1000) * (lease / 80) ** 0.5 * (1 + storey / 200)
                    records.append(
                        {
                            "month": month,
                            "town": town,
                            "flat_type": flat_type,
                            "flat_model": "MODEL A",
                            "floor_area_sqm": area,
                            "storey_mid": storey,
                            "remaining_lease_years": lease,
                            "resale_price": round(psm * area * rng.lognormal(0, 0.03), -3),
                        }
                    )
    frame = pd.DataFrame(records)
    frame["price_per_sqm"] = frame["resale_price"] / frame["floor_area_sqm"]
    frame["year"] = frame["month"].dt.year
    frame["months_since_start"] = (frame["month"].dt.year - 2017) * 12 + frame["month"].dt.month - 1
    frame["is_valid"] = True
    frame["is_price_outlier"] = False
    frame["exclude_from_model"] = False
    frame["pulled_at"] = pd.Timestamp("2024-01-15")
    return frame

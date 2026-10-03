"""End-to-end API checks against the real serving bundle (the demo journey)."""

import pytest
from fastapi.testclient import TestClient

from conftest import SERVING_DIR

pytestmark = pytest.mark.skipif(not (SERVING_DIR / "meta.json").exists(), reason="run the pipeline first")


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert "TAMPINES" in meta["towns"] and meta["quality"]["checks_total"] >= 9


def test_demo_journey(client):
    """Scene by scene: market -> forecast -> affordability -> fair value -> compare."""
    market = client.get("/api/market", params={"town": "TAMPINES", "flat_type": "4 ROOM"}).json()
    assert market["kpis"]["median_price"] > 0 and len(market["series"]) > 100

    forecast = client.get("/api/forecast", params={"town": "TAMPINES", "flat_type": "4 ROOM"}).json()
    assert forecast["available"] and len(forecast["forecast"]) == 6
    assert "projected to" in forecast["reading"]["headline"]

    afford = client.get("/api/affordability", params={"income": 9000, "cash": 200000, "flat_type": "4 ROOM", "town": "TAMPINES"}).json()
    assert 0 < afford["result"]["repayment_ratio"] < 1 and afford["ranking"]

    value = client.get(
        "/api/fair-value",
        params={"town": "TAMPINES", "flat_type": "4 ROOM", "floor_area": 95, "storey_range": "10 TO 12", "remaining_lease": 72, "asking_price": 690000},
    ).json()
    low, high = value["range"]
    assert low < value["estimate"] < high
    assert value["comparison"]["position"] in {"below", "within", "above"}
    assert len(value["comparables"]) == 5

    compare = client.get("/api/compare", params={"towns": "TAMPINES,BEDOK,PASIR RIS", "flat_type": "4 ROOM", "income": 9000}).json()
    assert len(compare["cards"]) == 3 and compare["verdicts"]


@pytest.mark.parametrize(
    "path, params",
    [
        ("/api/market", {"town": "ATLANTIS"}),
        ("/api/fair-value", {"town": "TAMPINES", "flat_type": "4 ROOM", "floor_area": 95, "storey_range": "HIGH", "remaining_lease": 72}),
        ("/api/compare", {"towns": "TAMPINES,BEDOK,PASIR RIS,YISHUN"}),
    ],
)
def test_bad_input_is_a_400_not_a_crash(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 400
    assert "error" in response.json()


def test_frontend_served(client):
    assert "FlatFair" in client.get("/").text
    assert client.get("/static/js/main.js").status_code == 200

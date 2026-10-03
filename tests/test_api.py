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
    assert "next six months" in forecast["reading"]["headline"]

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
    # The footer pages share one module.
    assert client.get("/static/js/pages/info.js").status_code == 200


# --------------------------------------------------------------------------- #
# Location: skipped for a build that has no block locations.
# --------------------------------------------------------------------------- #
has_location = pytest.mark.skipif(not (SERVING_DIR / "blocks.parquet").exists(), reason="this build has no block locations")
FLAT = {"town": "PASIR RIS", "flat_type": "5 ROOM", "floor_area": 126, "storey_range": "07 TO 09", "remaining_lease": 68}
BLOCK = {"block": "706", "street_name": "PASIR RIS DR 10"}


@has_location
def test_blocks_are_listed_by_street(client):
    assert client.get("/api/meta").json()["has_location"]
    town = client.get("/api/blocks", params={"town": "PASIR RIS"}).json()
    streets = {s["street_name"]: s for s in town["streets"]}
    assert "PASIR RIS DR 10" in streets
    blocks = streets["PASIR RIS DR 10"]["blocks"]
    assert any(b["block"] == "706" for b in blocks)
    # Singapore's bounding box: a block anywhere else means a bad match.
    assert all(1.2 < b["lat"] < 1.48 and 103.6 < b["lon"] < 104.05 for s in town["streets"] for b in s["blocks"])
    assert town["blocks"] == sum(len(s["blocks"]) for s in town["streets"])


@has_location
def test_nearby_describes_a_block(client):
    near = client.get("/api/nearby", params=BLOCK).json()
    assert near["block"]["label"] == "Blk 706 Pasir Ris Dr 10" and not near["block"]["approximate"]
    groups = {g["key"]: g for g in near["groups"]}
    assert {"train", "bus", "school", "shop", "park"} <= set(groups)
    train = groups["train"]["items"][0]
    assert train["name"].endswith(("MRT", "LRT")) and train["minutes"] >= 1 and train["metres"] > 0
    # Minutes follow from metres by the published rule.
    walk = near["walk"]
    for group in near["groups"]:
        for item in group["items"]:
            assert item["minutes"] == max(1, -(-item["metres"] * walk["detour_factor"] // walk["speed_m_per_min"]))
    assert [r["minutes"] for r in near["rings"]] == [5, 10]
    assert all(m["category"] in {"train", "bus", "school", "mall", "hawker", "park"} for m in near["markers"])


@has_location
def test_fair_value_uses_the_named_block(client):
    plain = client.get("/api/fair-value", params=FLAT).json()
    named = client.get("/api/fair-value", params={**FLAT, **BLOCK}).json()
    assert plain["location"] is None and named["location"]["block"]["block"] == "706"
    assert plain["location_in_model"] and named["location_in_model"]
    # Naming the block adds one "Location" line to what changes the price.
    assert "Location" not in [d["label"] for d in plain["drivers"]]
    assert "Location" in [d["label"] for d in named["drivers"]]
    low, high = named["range"]
    assert low < named["estimate"] < high
    # Every comparable is placed, and with a block named each says how far away it is.
    assert all(1.2 < c["latitude"] < 1.48 for c in plain["comparables"])
    assert all("distance_m" not in c for c in plain["comparables"])
    assert all(c["distance_m"] >= 0 and c["train_minutes"] >= 1 for c in named["comparables"])
    # The model's own inputs are not echoed back as part of the flat.
    assert "mrt_m" not in named["flat"]


@has_location
def test_block_prefills_the_form(client):
    typical = client.get("/api/fair-value/typical", params={"town": "PASIR RIS", "flat_type": "5 ROOM", **BLOCK}).json()
    assert typical["prefill"]["label"] == "Blk 706 Pasir Ris Dr 10"
    assert 40 < typical["prefill"]["remaining_lease_years"] < 99
    assert client.get("/api/fair-value/typical", params={"town": "PASIR RIS", "flat_type": "5 ROOM"}).json()["prefill"] is None


@has_location
def test_compare_and_town_stats_say_how_far_the_train_is(client):
    compare = client.get("/api/compare", params={"towns": "TAMPINES,PASIR RIS", "flat_type": "4 ROOM"}).json()
    for card in compare["cards"]:
        assert 1 <= card["location"]["train_minutes"] <= 60
        assert 0 <= card["location"]["near_train_pct"] <= 100
    stats = client.get("/api/town-stats", params={"flat_type": "4 ROOM"}).json()
    assert all(t["train_minutes"] >= 1 for t in stats["towns"])


@has_location
@pytest.mark.parametrize(
    "path, params",
    [
        ("/api/nearby", {"block": "9999", "street_name": "NOWHERE RD"}),
        ("/api/blocks", {"town": "ATLANTIS"}),
        ("/api/fair-value", {**FLAT, "block": "706"}),                                   # a block needs its street
        ("/api/fair-value", {**FLAT, "town": "TAMPINES", **BLOCK}),                        # the block is in another town
    ],
)
def test_bad_location_input_is_a_400(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 400
    assert "error" in response.json()

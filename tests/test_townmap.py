import json
import math

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import SERVING_DIR
from flatfair.features.townmap import (
    build_town_map,
    ring_area_and_centroid,
    simplify_ring,
    town_for_area,
    town_map_frame,
    town_map_from_frame,
)
from flatfair.ingestion.boundaries import planning_areas_frame

TOWNS = ["BEDOK", "CENTRAL AREA", "KALLANG/WHAMPOA", "TAMPINES"]


def square(lon, lat, size=0.02):
    return [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]


def feature(name, lon, lat, central="N", region="EAST REGION", kind="Polygon"):
    ring = square(lon, lat)
    coordinates = [ring] if kind == "Polygon" else [[ring], [square(lon + 0.05, lat)]]
    return {"type": "Feature", "properties": {"PLN_AREA_N": name, "CA_IND": central, "REGION_N": region}, "geometry": {"type": kind, "coordinates": coordinates}}


@pytest.fixture
def areas():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            feature("BEDOK", 103.92, 1.32),
            feature("TAMPINES", 103.95, 1.35, kind="MultiPolygon"),
            feature("KALLANG", 103.87, 1.31, region="CENTRAL REGION"),
            feature("OUTRAM", 103.83, 1.28, central="Y", region="CENTRAL REGION"),
            feature("ROCHOR", 103.85, 1.30, central="Y", region="CENTRAL REGION"),
            feature("TUAS", 103.63, 1.30, region="WEST REGION"),
        ],
    }
    return planning_areas_frame(geojson)


def test_town_for_area_rules():
    towns = set(TOWNS)
    assert town_for_area("BEDOK", False, towns) == "BEDOK"
    assert town_for_area("KALLANG", False, towns) == "KALLANG/WHAMPOA"
    assert town_for_area("OUTRAM", True, towns) == "CENTRAL AREA"
    assert town_for_area("TUAS", False, towns) is None


def test_simplify_keeps_corners_and_drops_collinear_points():
    # A square with extra points along each edge collapses back to its corners.
    ring = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10), (5, 10), (0, 10), (0, 5), (0, 0)]
    simple = simplify_ring(ring, tolerance=0.1)
    assert simple[0] == simple[-1]
    assert set(simple) == {(0, 0), (10, 0), (10, 10), (0, 10)}


def test_simplify_keeps_real_detail():
    ring = [(0, 0), (5, 3), (10, 0), (10, 10), (0, 10), (0, 0)]
    assert (5, 3) in simplify_ring(ring, tolerance=0.5)
    assert (5, 3) not in simplify_ring(ring, tolerance=5)


def test_area_and_centroid():
    area, cx, cy = ring_area_and_centroid([(0, 0), (4, 0), (4, 2), (0, 2), (0, 0)])
    assert (area, cx, cy) == pytest.approx((8, 2, 1))


def test_build_map_groups_towns_and_context(cfg, areas):
    town_map = build_town_map(areas, TOWNS, cfg)
    drawn = {t["town"]: t for t in town_map["towns"]}
    assert set(drawn) == set(TOWNS)
    assert town_map["missing_towns"] == []
    assert [c["name"] for c in town_map["context"]] == ["TUAS"]
    assert drawn["CENTRAL AREA"]["merged"] and drawn["CENTRAL AREA"]["planning_areas"] == ["OUTRAM", "ROCHOR"]
    assert drawn["TAMPINES"]["d"].count("M") == 2  # both parts of the multi-polygon
    width, height = town_map["view_box"][2:]
    assert width == 1000 and height > 0
    for town in drawn.values():
        assert 0 <= town["cx"] <= width and 0 <= town["cy"] <= height
    # North is up: Tampines (higher latitude) sits above Bedok.
    assert drawn["TAMPINES"]["cy"] < drawn["BEDOK"]["cy"]
    # East is right.
    assert drawn["TAMPINES"]["cx"] > drawn["KALLANG/WHAMPOA"]["cx"]


def test_missing_town_is_reported(cfg, areas):
    town_map = build_town_map(areas, TOWNS + ["YISHUN"], cfg)
    assert town_map["missing_towns"] == ["YISHUN"]


def test_frame_round_trip(cfg, areas):
    town_map = build_town_map(areas, TOWNS, cfg)
    again = town_map_from_frame(town_map_frame(town_map))
    assert [t["town"] for t in again["towns"]] == [t["town"] for t in town_map["towns"]]
    assert again["towns"][0]["d"] == town_map["towns"][0]["d"]
    assert again["view_box"] == pytest.approx(town_map["view_box"])


def test_features_without_names_are_skipped():
    geojson = {"type": "FeatureCollection", "features": [feature("BEDOK", 103.92, 1.32), {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [square(1, 1)]}}]}
    assert planning_areas_frame(geojson)["planning_area"].tolist() == ["BEDOK"]


def test_description_table_fallback():
    html = "<table><tr><th>PLN_AREA_N</th> <td>YISHUN</td></tr><tr><th>CA_IND</th> <td>N</td></tr><tr><th>REGION_N</th> <td>NORTH REGION</td></tr></table>"
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"Description": html}, "geometry": {"type": "Polygon", "coordinates": [square(103.8, 1.42)]}}]}
    row = planning_areas_frame(geojson).iloc[0]
    assert (row["planning_area"], row["region"], bool(row["central_area"])) == ("YISHUN", "NORTH REGION", False)


# --------------------------------------------------------------------------- real bundle
needs_bundle = pytest.mark.skipif(not (SERVING_DIR / "town_map.json").exists(), reason="run the boundaries and publish steps first")


@needs_bundle
def test_published_map_covers_every_town():
    town_map = json.loads((SERVING_DIR / "town_map.json").read_text(encoding="utf-8"))
    towns = set(pd.read_parquet(SERVING_DIR / "transactions.parquet")["town"].unique())
    assert {t["town"] for t in town_map["towns"]} == towns
    for town in town_map["towns"]:
        assert town["d"].startswith("M") and town["d"].endswith("Z")
        assert not math.isnan(town["cx"]) and not math.isnan(town["cy"])


@needs_bundle
def test_map_api():
    from app.main import app

    with TestClient(app) as client:
        town_map = client.get("/api/map").json()
        assert town_map["available"] and len(town_map["towns"]) == 26
        stats = client.get("/api/town-stats", params={"flat_type": "4 ROOM"}).json()
        tampines = next(t for t in stats["towns"] if t["town"] == "TAMPINES")
        assert tampines["enough_sales"] and tampines["median_price_12m"] > 0
        assert client.get("/api/town-stats", params={"flat_type": "PENTHOUSE"}).status_code == 400

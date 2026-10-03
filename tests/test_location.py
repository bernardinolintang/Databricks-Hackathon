"""Block locations, nearby places and the location inputs to the price model."""

import json

import numpy as np
import pandas as pd
import pytest

from flatfair.features.location import (
    LOCATION_FEATURES,
    M_PER_DEG_LAT,
    M_PER_DEG_LON,
    PlaceIndex,
    block_features,
    clean_places,
    match_blocks,
    ring_metres,
    simplify_connectors,
    street_key,
    walk_minutes,
)
from flatfair.features.market import build_market_index
from flatfair.ingestion import places as place_sources
from flatfair.models.comparables import find_comparables
from flatfair.models.fair_value import FLAT_ONLY_MODEL, attach_location, model_features, predict_price, train_fair_value

HOME = (1.3500, 103.9400)


def offset(north_m: float = 0.0, east_m: float = 0.0) -> tuple[float, float]:
    """A point a known distance from HOME."""
    return HOME[0] + north_m / M_PER_DEG_LAT, HOME[1] + east_m / M_PER_DEG_LON


def place(category: str, name: str, north_m: float = 0.0, east_m: float = 0.0, kind: str | None = None) -> dict:
    lat, lon = offset(north_m, east_m)
    return {"category": category, "kind": kind, "name": name, "detail": None, "latitude": lat, "longitude": lon}


# --------------------------------------------------------------------------- #
# Matching resale addresses to HDB's building outlines
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "street, prefix, hint",
    [
        ("PASIR RIS DR 10", "PA", "D"),
        ("JLN BT MERAH", "BU", "M"),      # 'Jalan' is skipped, 'Bt' is spelled out
        ("LOR 1 TOA PAYOH", "TO", "P"),   # 'Lorong 1' is skipped
        ("C'WEALTH DR", "CO", "D"),
        ("BEDOK NTH ST 2", "BE", "S"),
        ("DOVER RD", "DO", "V"),          # a one-word name lends its own third letter
        ("ST. GEORGE'S RD", "ST", "G"),
    ],
)
def test_street_key(street, prefix, hint):
    got_prefix, hints = street_key(street)
    assert got_prefix == prefix
    assert hint in hints


def buildings_frame(rows: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["block", "street_code", "latitude", "longitude"])


def test_match_blocks_picks_the_code_named_after_the_street():
    # Block 101 exists on two streets. Only one code starts like 'Tampines'.
    buildings = buildings_frame(
        [
            ("101", "TAS11A", *offset(0, 0)),
            ("102", "TAS11A", *offset(50, 0)),
            ("101", "BES01K", *offset(9000, 0)),
            ("102", "BES01K", *offset(9050, 0)),
        ]
    )
    addresses = pd.DataFrame({"town": ["TAMPINES"] * 2, "block": ["101", "102"], "street_name": ["TAMPINES ST 11"] * 2})
    out = match_blocks(addresses, buildings)
    assert set(out["street_code"]) == {"TAS11A"}
    assert (out["location_source"] == "building").all()
    assert out.loc[out["block"] == "101", "latitude"].iloc[0] == pytest.approx(HOME[0])


def test_match_blocks_breaks_a_tie_with_the_street_type():
    # Both codes hold every block and both start 'BE'; only one's third letter fits 'ST'.
    buildings = buildings_frame(
        [
            ("1", "BES01K", *offset(0, 0)),
            ("2", "BES01K", *offset(40, 0)),
            ("1", "BER00B", *offset(2000, 0)),
            ("2", "BER00B", *offset(2040, 0)),
        ]
    )
    addresses = pd.DataFrame({"town": ["BEDOK"] * 2, "block": ["1", "2"], "street_name": ["BEDOK NTH ST 2"] * 2})
    assert set(match_blocks(addresses, buildings)["street_code"]) == {"BES01K"}


def test_match_blocks_falls_back_to_the_street_then_the_town():
    buildings = buildings_frame([("10", "TAS11A", *offset(0, 0)), ("12", "TAS11A", *offset(100, 0))])
    addresses = pd.DataFrame(
        {
            "town": ["TAMPINES"] * 4,
            "block": ["10", "12", "14", "5"],
            "street_name": ["TAMPINES ST 11", "TAMPINES ST 11", "TAMPINES ST 11", "TAMPINES AVE 9"],
        }
    )
    out = match_blocks(addresses, buildings).set_index("block")
    assert out.loc["10", "location_source"] == "building"
    # Block 14 has no outline, so it sits in the middle of its street.
    assert out.loc["14", "location_source"] == "street"
    assert out.loc["14", "latitude"] == pytest.approx((out.loc["10", "latitude"] + out.loc["12", "latitude"]) / 2)
    # Tampines Ave 9 matches no code at all, so it sits in the middle of the town.
    assert out.loc["5", "location_source"] == "town"
    assert not out["latitude"].isna().any()


def test_match_blocks_rejects_a_match_far_from_its_town():
    # 'TAL' fits Tampines Link by name but lies 12 km from every other Tampines block.
    near = [(str(n), "TAS11A", *offset(n * 10, 0)) for n in range(100, 120)]
    buildings = buildings_frame(near + [("7", "TAL00X", *offset(12_000, 0))])
    addresses = pd.DataFrame(
        {
            "town": ["TAMPINES"] * 21,
            "block": [str(n) for n in range(100, 120)] + ["7"],
            "street_name": ["TAMPINES ST 11"] * 20 + ["TAMPINES LINK"],
        }
    )
    out = match_blocks(addresses, buildings).set_index("block")
    assert out.loc["7", "location_source"] == "town"


# --------------------------------------------------------------------------- #
# Walking time
# --------------------------------------------------------------------------- #
def test_walk_minutes_round_up_and_match_the_rings(cfg):
    assert walk_minutes(0, cfg) == 1
    assert walk_minutes(None, cfg) is None
    assert walk_minutes(float("nan"), cfg) is None
    # 400 m in a straight line is 520 m on foot at 80 m a minute: 6.5, so 7.
    assert walk_minutes(400, cfg) == 7
    for minutes in cfg["location"]["walk_rings_minutes"]:
        assert walk_minutes(ring_metres(minutes, cfg), cfg) == minutes
        assert walk_minutes(ring_metres(minutes, cfg) + 5, cfg) == minutes + 1


# --------------------------------------------------------------------------- #
# Places and block features
# --------------------------------------------------------------------------- #
@pytest.fixture
def index(cfg):
    places = pd.DataFrame(
        [
            place("train", "Alpha", east_m=300, kind="MRT"),
            place("train", "Loop", north_m=100, kind="LRT"),
            place("bus", "Bus stop 1", east_m=50),
            place("bus", "Bus stop 2", east_m=350),
            place("bus", "Bus stop 3", east_m=450),
            place("school", "Near Primary School", north_m=600, kind="Primary"),
            place("school", "Far Primary School", north_m=1500, kind="Primary"),
            place("school", "A Secondary School", north_m=200, kind="Secondary"),
            place("mall", "The Mall", east_m=-800),
            place("hawker", "Food Centre", north_m=-400),
        ]
    )
    connector = [list(offset(-200, -1000)), list(offset(-200, 1000))]
    connectors = pd.DataFrame([{"name": "Riverside PC", "loop": "East", "points": 2, "path_json": json.dumps(connector)}])
    return PlaceIndex(places, connectors, cfg)


def test_block_features_measure_distance_and_count(index, cfg):
    blocks = pd.DataFrame({"latitude": [HOME[0]], "longitude": [HOME[1]]})
    row = block_features(blocks, index, cfg).iloc[0]
    assert row["mrt_m"] == pytest.approx(300, abs=2) and row["mrt_name"] == "Alpha"
    # The LRT is nearer than the MRT, and "train" means either.
    assert row["train_m"] == pytest.approx(100, abs=2) and row["train_kind"] == "LRT"
    assert row["bus_m"] == pytest.approx(50, abs=2)
    assert row["bus_stops_400m"] == 2
    assert row["primary_schools_1km"] == 1 and row["primary_name"] == "Near Primary School"
    assert row["mall_m"] == pytest.approx(800, abs=2)
    assert row["hawker_m"] == pytest.approx(400, abs=2)
    # The connector passes 200 m to the south; the nearest point on the line counts.
    assert row["connector_m"] == pytest.approx(200, abs=15)
    # No park in this index: the column is there but empty.
    assert np.isnan(row["park_m"])
    assert set(LOCATION_FEATURES) <= set(block_features(blocks, index, cfg).columns)


def test_place_index_within_and_connectors(index):
    stops = index.within("bus", *HOME, radius=400)
    assert list(stops["name"]) == ["Bus stop 1", "Bus stop 2"]
    assert stops["metres"].is_monotonic_increasing
    assert index.within("park", *HOME, radius=400).empty
    assert [c["name"] for c in index.connectors_within(*HOME, radius=300)] == ["Riverside PC"]
    assert index.connectors_within(*HOME, radius=100) == []


def test_clean_places_keeps_one_of_each_mall():
    a = place("mall", "Century Square")
    b = place("mall", "Century Square", north_m=20)          # the same mall, mapped twice
    c = place("mall", "Century Square", north_m=5000)        # a namesake across the island
    cleaned = clean_places(pd.DataFrame([a, b, c, place("bus", "Bus stop 1"), {**place("park", "Nowhere"), "latitude": np.nan}]))
    assert (cleaned["category"] == "mall").sum() == 2
    assert not cleaned["latitude"].isna().any()


def test_simplify_connectors_drops_points_on_a_straight_line(cfg):
    start, end = offset(0, 0), offset(0, 1000)
    straight = [[start[1] + (end[1] - start[1]) * i / 50, start[0]] for i in range(51)]
    frame = pd.DataFrame([{"name": "PC", "loop": "East", "geometry_json": json.dumps(straight), "source": "test"}])
    path = json.loads(simplify_connectors(frame, cfg).iloc[0]["path_json"])
    assert len(path) == 2
    # Output is [latitude, longitude], the order the map wants.
    assert path[0] == pytest.approx([start[0], start[1]], abs=1e-5)
    assert path[-1] == pytest.approx([end[0], end[1]], abs=1e-5)


# --------------------------------------------------------------------------- #
# Reading the sources
# --------------------------------------------------------------------------- #
def point_feature(properties: dict, lat: float = 1.35, lon: float = 103.9) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def test_station_rows_name_kind_and_code_only_exits():
    rows = place_sources.station_rows(
        [
            point_feature({"STATION_NA": "PASIR RIS MRT STATION", "EXIT_CODE": "Exit A"}),
            point_feature({"STATION_NA": "CHENG LIM LRT STATION", "EXIT_CODE": "Exit 1"}),
            point_feature({"STATION_NA": "CC9", "EXIT_CODE": "Exit B"}),
            point_feature({"STATION_NA": "", "EXIT_CODE": "Exit C"}),
        ],
        "test",
    )
    assert [(r["name"], r["kind"]) for r in rows] == [("Pasir Ris", "MRT"), ("Cheng Lim", "LRT"), ("Paya Lebar", "MRT")]


def test_park_and_hawker_rows_keep_only_real_places():
    parks = place_sources.park_rows(
        [point_feature({"NAME": "TIONG BAHRU PK"}), point_feature({"NAME": "GROVE LANE PG"}), point_feature({"NAME": "BISHAN-ANG MO KIO PARK"})], "test"
    )
    assert [p["name"] for p in parks] == ["Tiong Bahru Park", "Bishan-Ang Mo Kio Park"]
    hawkers = place_sources.hawker_rows(
        [point_feature({"NAME": "Tiong Bahru Market", "STATUS": "Existing"}), point_feature({"NAME": "New Centre", "STATUS": "Under Construction"})], "test"
    )
    assert [h["name"] for h in hawkers] == ["Tiong Bahru Market"]


def test_tidy_names():
    assert place_sources._tidy("ST. ANDREW'S JUNIOR SCHOOL") == "St. Andrew's Junior School"
    assert place_sources._tidy("CHIJ (KATONG) PRIMARY") == "CHIJ (Katong) Primary"
    assert place_sources._tidy("White Sands") == "White Sands"


def test_building_rows_take_the_middle_of_the_outline():
    square = [[103.0, 1.0], [103.002, 1.0], [103.002, 1.002], [103.0, 1.002]]
    features = [
        {"properties": {"BLK_NO": "12a", "ST_COD": "tas11a", "POSTAL_COD": "520012"}, "geometry": {"type": "Polygon", "coordinates": [square]}},
        {"properties": {"BLK_NO": "", "ST_COD": "TAS11A"}, "geometry": {"type": "Polygon", "coordinates": [square]}},
    ]
    frame = place_sources.building_rows(features)
    assert len(frame) == 1
    row = frame.iloc[0]
    assert (row["block"], row["street_code"]) == ("12A", "TAS11A")
    assert row["latitude"] == pytest.approx(1.001) and row["longitude"] == pytest.approx(103.001)


def test_connector_rows_split_multi_lines():
    features = [
        {"properties": {"PARK": "Tampines PC", "PCN_LOOP": "Eastern"}, "geometry": {"type": "LineString", "coordinates": [[103.9, 1.35], [103.91, 1.35]]}},
        {"properties": {"PARK": "Ulu Pandan PC"}, "geometry": {"type": "MultiLineString", "coordinates": [[[103.7, 1.3], [103.71, 1.3]], [[103.72, 1.3], [103.73, 1.3]]]}},
        {"properties": {"PARK": "A point"}, "geometry": {"type": "Point", "coordinates": [103.7, 1.3]}},
    ]
    assert list(place_sources.connector_rows(features, "test")["name"]) == ["Tampines PC", "Ulu Pandan PC", "Ulu Pandan PC"]


# --------------------------------------------------------------------------- #
# Comparables and the price model
# --------------------------------------------------------------------------- #
def test_comparables_prefer_nearby_sales_when_a_block_is_named(cfg, synthetic_transactions):
    txn = synthetic_transactions[(synthetic_transactions["town"] == "TAMPINES") & (synthetic_transactions["flat_type"] == "4 ROOM")].copy()
    # Identical flats sold in the same month, so only distance tells them apart.
    txn = txn.assign(floor_area_sqm=92.0, storey_mid=8.0, remaining_lease_years=75.0, month=txn["month"].max(), block="1", street_name="X", storey_range="07 TO 09")
    txn = txn.head(6).reset_index(drop=True)
    metres = [2500, 50, 900, 300, 1500, 150]
    txn["latitude"], txn["longitude"] = zip(*(offset(m, 0) for m in metres))
    txn["train_m"] = 400.0

    near_first = find_comparables(txn, "TAMPINES", "4 ROOM", 92, 8, 75, cfg, origin=HOME)
    assert list(near_first["distance_m"].round(-1)) == sorted(metres)[: cfg["fair_value"]["comparables"]["top_k"]]
    assert near_first["similarity"].is_monotonic_decreasing
    # Without a block there is nothing to measure from.
    assert "distance_m" not in find_comparables(txn, "TAMPINES", "4 ROOM", 92, 8, 75, cfg).columns


@pytest.fixture
def located(cfg, synthetic_transactions):
    """Synthetic sales where being near the MRT is worth real money."""
    rng = np.random.default_rng(3)
    txn = synthetic_transactions.copy()
    txn["block"] = rng.integers(1, 60, len(txn)).astype(str)
    txn["street_name"] = txn["town"] + " ST 1"
    blocks = txn[["town", "block", "street_name"]].drop_duplicates().reset_index(drop=True)
    blocks["mrt_m"] = rng.uniform(100, 1500, len(blocks))
    for feature in LOCATION_FEATURES:
        if feature != "mrt_m":
            blocks[feature] = rng.uniform(0, 1, len(blocks))
    txn = txn.merge(blocks[["block", "street_name", "mrt_m"]], on=["block", "street_name"])
    # Up to 15% off for the furthest blocks.
    txn["resale_price"] = (txn["resale_price"] * (1 - 0.15 * (txn["mrt_m"] - 100) / 1400)).round(-3)
    txn["price_per_sqm"] = txn["resale_price"] / txn["floor_area_sqm"]
    small = {**cfg, "fair_value": {**cfg["fair_value"], "permutation_sample": 500, "gbm": {**cfg["fair_value"]["gbm"], "max_iter": 80}}}
    return txn.drop(columns="mrt_m"), blocks, small


def test_location_improves_the_price_model(located):
    txn, blocks, cfg = located
    index = build_market_index(txn, cfg)
    result = train_fair_value(txn, index, txn["month"].max(), cfg, block_locations=blocks)
    metrics = result.metrics.set_index("model")
    # The same kind of model, with and without location.
    assert metrics.loc["gradient_boosting", "mae"] < metrics.loc[FLAT_ONLY_MODEL, "mae"]
    assert result.selected_model != FLAT_ONLY_MODEL
    assert set(LOCATION_FEATURES) <= set(model_features(result.model))
    assert result.importance.set_index("feature").loc["mrt_m", "share_pct"] > 5

    # Nearer the MRT, the same flat is worth more.
    flat = {"town": "TAMPINES", "flat_type": "4 ROOM", "flat_model": "MODEL A", "floor_area_sqm": 92, "storey_mid": 8, "remaining_lease_years": 75}
    place_of = {f: 0.5 for f in LOCATION_FEATURES}
    near, far = predict_price(result.model, pd.DataFrame([{**flat, **place_of, "mrt_m": 150}, {**flat, **place_of, "mrt_m": 1400}]), float(index["market_index_psm"].iloc[-1]), 48)
    assert near > far * 1.05
    # The model says which inputs it needs.
    with pytest.raises(ValueError, match="mrt_m"):
        predict_price(result.model, pd.DataFrame([flat]), 6000.0, 48)


def test_attach_location_is_a_no_op_without_blocks(synthetic_transactions):
    frame, features = attach_location(synthetic_transactions, None)
    assert features == [] and frame is synthetic_transactions

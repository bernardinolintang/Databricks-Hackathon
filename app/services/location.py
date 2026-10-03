"""What is near a block: the places a buyer weighs up beyond the flat itself.

Everything here reads the block and place tables the pipeline publishes. If a
build has none (the sources were unreachable) the functions say so and the app
hides its street map.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.bundle import Bundle
from app.services.common import ALL, InputError, title_case, validate_choice
from flatfair.features.location import LOCATION_FEATURES, ring_metres, to_metres, walk_minutes
from flatfair.models.fair_value import model_features

RECENT_MONTHS = 24
# A walk this long or shorter counts as "near the train" in town comparisons.
NEAR_TRAIN_MINUTES = 10
MAX_MARKERS_PER_KIND = 12


def _cfg(bundle: Bundle) -> dict[str, Any]:
    return {"location": bundle.meta["location"]}


def minutes(bundle: Bundle, metres: Any) -> int | None:
    return None if metres is None or pd.isna(metres) else walk_minutes(float(metres), _cfg(bundle))


def require_location(bundle: Bundle) -> None:
    if not bundle.has_location:
        raise InputError("This build has no block locations")


def street_label(street: str) -> str:
    """'PASIR RIS DR 10' -> 'Pasir Ris Dr 10'."""
    return " ".join(word.capitalize() if word.isalpha() or "'" in word else word.title() for word in street.split())


def address_label(block: str, street: str) -> str:
    return f"Blk {block} {street_label(street)}"


def blocks_in_town(bundle: Bundle, town: str) -> dict[str, Any]:
    """Every block with a resale record in a town, grouped by street, for the address picker."""
    require_location(bundle)
    town = validate_choice(town, bundle.towns, "town")
    if town == ALL:
        raise InputError("Choose a town")
    rows = bundle.blocks[bundle.blocks["town"] == town]
    types = bundle.block_flat_types
    streets = []
    for street, group in rows.groupby("street_name"):
        ordered = group.assign(_n=group["block"].str.extract(r"(\d+)")[0].astype(float)).sort_values(["_n", "block"])
        streets.append(
            {
                "street_name": street,
                "label": street_label(street),
                "blocks": [
                    {
                        "block": r.block,
                        "lat": round(r.latitude, 6),
                        "lon": round(r.longitude, 6),
                        "flat_types": types.get((r.block, r.street_name), []),
                    }
                    for r in ordered.itertuples(index=False)
                ],
            }
        )
    return {"town": town, "streets": streets, "blocks": int(len(rows))}


def find_block(bundle: Bundle, block: str | None, street_name: str | None, town: str | None = None) -> pd.Series | None:
    """The block a buyer named, or None if they named none."""
    if not block and not street_name:
        return None
    require_location(bundle)
    if not block or not street_name:
        raise InputError("Give both a block and a street")
    block, street_name = block.strip().upper(), street_name.strip().upper()
    rows = bundle.blocks[(bundle.blocks["block"] == block) & (bundle.blocks["street_name"] == street_name)]
    if town and town != ALL:
        rows = rows[rows["town"] == town]
    if rows.empty:
        raise InputError(f"No resale records for Blk {block} {street_label(street_name)}" + (f" in {title_case(town)}" if town and town != ALL else ""))
    return rows.iloc[0]


def typical_location(bundle: Bundle, town: str, flat_type: str) -> dict[str, float]:
    """The middle of each location measure over recent sales of this town and
    flat type: the 'typical block' the price model compares a named block with."""
    if not bundle.has_location:
        return {}
    return bundle.typical_locations.get((town, flat_type)) or bundle.typical_locations.get((town, ALL)) or {}


def town_location(bundle: Bundle, town: str, flat_type: str) -> dict[str, Any] | None:
    """Two plain facts about getting around from a town's recently sold flats."""
    typical = typical_location(bundle, town, flat_type)
    if not typical or pd.isna(typical.get("train_m", np.nan)):
        return None
    return {
        "train_minutes": minutes(bundle, typical["train_m"]),
        "near_train_pct": typical.get("near_train_pct"),
        "near_train_minutes": NEAR_TRAIN_MINUTES,
        "primary_schools_1km": typical.get("primary_schools_1km"),
    }


def _item(bundle: Bundle, name: str, metres: Any, row: Any = None, kind: str | None = None, note: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "metres": None if pd.isna(metres) else int(round(float(metres))),
        "minutes": minutes(bundle, metres),
        "lat": None if row is None else round(float(row.latitude), 6),
        "lon": None if row is None else round(float(row.longitude), 6),
        "note": note,
    }


def nearby(bundle: Bundle, block: pd.Series) -> dict[str, Any]:
    """Everything the 'What's nearby' card and the street map need for one block."""
    require_location(bundle)
    loc = bundle.meta["location"]
    index = bundle.place_index
    lat, lon = float(block["latitude"]), float(block["longitude"])
    radius = float(loc["nearby_radius_m"])

    def closest(key: str) -> Any:
        """The nearest place of a kind, however far it is."""
        if not index.has(key):
            return None
        distance, row = index.nearest(key, to_metres([lat], [lon]))
        found = index.groups[key].iloc[int(row[0])]
        return found, float(distance[0])

    groups: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []

    def mark(frame: pd.DataFrame, category: str, limit: int = MAX_MARKERS_PER_KIND) -> None:
        for r in frame.head(limit).itertuples(index=False):
            markers.append(
                {
                    "category": category,
                    "kind": r.kind,
                    "name": r.name,
                    "lat": round(float(r.latitude), 6),
                    "lon": round(float(r.longitude), 6),
                    "metres": int(round(r.metres)),
                    "minutes": minutes(bundle, r.metres),
                }
            )

    # Trains: one marker per station, at its nearest exit.
    trains = index.within("train", lat, lon, max(radius, 1500.0))
    stations = trains.drop_duplicates(["name", "kind"])
    nearest_train = closest("train")
    if nearest_train:
        found, metres = nearest_train
        items = [_item(bundle, f"{found['name']} {found['kind']}", metres, found, kind=found["kind"])]
        nearest_mrt = closest("mrt")
        if found["kind"] != "MRT" and nearest_mrt:
            items.append(_item(bundle, f"{nearest_mrt[0]['name']} MRT", nearest_mrt[1], nearest_mrt[0], kind="MRT"))
        typical = typical_location(bundle, block["town"], ALL)
        note = None
        if typical.get("train_m") is not None and not pd.isna(typical.get("train_m")):
            note = f"A typical flat in {title_case(block['town'])} is {minutes(bundle, typical['train_m'])} min from a station"
        groups.append({"key": "train", "label": "Train", "items": items, "note": note})
        if stations.empty:
            stations = pd.DataFrame([{**found.to_dict(), "metres": metres}])
        mark(stations.assign(name=stations["name"] + " " + stations["kind"]), "train", 6)

    # Buses: a count says more than one stop's number.
    stops = index.within("bus", lat, lon, float(loc["bus_stop_radius_m"]))
    nearest_bus = closest("bus")
    if nearest_bus:
        found, metres = nearest_bus
        count = len(stops)
        note = f"{count} bus stop{'s' if count != 1 else ''} within {int(loc['bus_stop_radius_m'])} m"
        groups.append({"key": "bus", "label": "Bus", "items": [_item(bundle, "Nearest bus stop", metres, found)], "note": note})
        mark(stops, "bus")

    # Schools: MOE gives Primary 1 priority to homes within 1 km.
    primary = index.within("primary", lat, lon, float(loc["school_radius_m"]))
    nearest_primary = closest("primary")
    if nearest_primary:
        found, metres = nearest_primary
        count = len(primary)
        note = f"{count} primary school{'s' if count != 1 else ''} within 1 km" if count else "No primary school within 1 km"
        groups.append({"key": "school", "label": "Schools", "items": [_item(bundle, found["name"], metres, found, kind="Primary")], "note": note})
        schools = index.within("school", lat, lon, float(loc["school_radius_m"]))
        if schools.empty:
            schools = pd.DataFrame([{**found.to_dict(), "metres": metres}])
        mark(schools, "school")

    shops = []
    for key, kind in (("mall", "Mall"), ("hawker", "Hawker centre")):
        found = closest(key)
        if found:
            shops.append(_item(bundle, found[0]["name"], found[1], found[0], kind=kind))
            around = index.within(key, lat, lon, radius)
            if around.empty:
                around = pd.DataFrame([{**found[0].to_dict(), "metres": found[1]}])
            mark(around.assign(kind=kind), key, 6)
    if shops:
        groups.append({"key": "shop", "label": "Shops and food", "items": shops, "note": None})

    parks = []
    found = closest("park")
    if found:
        parks.append(_item(bundle, found[0]["name"], found[1], found[0], kind="Park"))
        around = index.within("park", lat, lon, radius)
        if around.empty:
            around = pd.DataFrame([{**found[0].to_dict(), "metres": found[1]}])
        mark(around.assign(kind="Park"), "park", 6)
    if not pd.isna(block.get("connector_m", np.nan)):
        parks.append(_item(bundle, "Park connector", block["connector_m"], kind="Park connector"))
    if parks:
        groups.append({"key": "park", "label": "Parks", "items": parks, "note": None})

    return {
        "block": {
            "block": block["block"],
            "street_name": block["street_name"],
            "town": block["town"],
            "label": address_label(block["block"], block["street_name"]),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            # 'building' is the block's own outline; anything else is an approximation.
            "approximate": block["location_source"] != "building",
        },
        "groups": groups,
        "markers": markers,
        "connectors": index.connectors_within(lat, lon, radius * 1.3),
        "rings": [{"minutes": m, "metres": int(round(ring_metres(m, _cfg(bundle))))} for m in loc["walk_rings_minutes"]],
        "walk": {"speed_m_per_min": loc["walk_speed_m_per_min"], "detour_factor": loc["detour_factor"]},
    }


def block_nearby(bundle: Bundle, block: str, street_name: str, town: str | None = None) -> dict[str, Any]:
    found = find_block(bundle, block, street_name, town)
    if found is None:
        raise InputError("Give a block and a street")
    return nearby(bundle, found)


def model_location(bundle: Bundle) -> list[str]:
    """The location inputs the served price model was trained with, if any."""
    return [f for f in model_features(bundle.model) if f in LOCATION_FEATURES]

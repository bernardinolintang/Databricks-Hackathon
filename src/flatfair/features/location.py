"""Where each block is, and what is near it.

Resale records name a block and a street but carry no coordinates. HDB's
building outlines have coordinates but name the street with a code. The two are
joined here by working out which code each street uses, then every block gets
its distance to the places a buyer cares about: trains, buses, schools, shops,
food and parks.

Distances are straight lines. Walking times are an estimate from them (see
`walk_minutes`), which is plainly said wherever the app shows one.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

# Singapore is small enough that a flat projection around its centre is exact
# to within a metre or two over the distances that matter here.
LAT0, LON0 = 1.3521, 103.8198
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))

# What the fair value model learns from. Each is a property of the block.
LOCATION_FEATURES = [
    "mrt_m", "city_km", "mall_m", "hawker_m", "park_m", "connector_m", "primary_schools_1km", "bus_stops_400m",
]
LOCATION_LABELS = {
    "mrt_m": "Walk to the MRT",
    "city_km": "Distance to the city centre",
    "mall_m": "Walk to a mall",
    "hawker_m": "Walk to a hawker centre",
    "park_m": "Walk to a park",
    "connector_m": "Walk to a park connector",
    "primary_schools_1km": "Primary schools within 1 km",
    "bus_stops_400m": "Bus stops nearby",
}
# A match further than this from the rest of its town is treated as wrong.
MAX_TOWN_SPREAD_M = 6_000.0
# Words HDB leaves out, or spells out, when it builds a street code.
SKIPPED_WORDS = {"JLN", "LOR", "KG"}
EXPANDED_WORDS = {"BT": "BUKIT", "UPP": "UPPER", "C'WEALTH": "COMMONWEALTH", "TG": "TANJONG", "NTH": "NORTH", "STH": "SOUTH"}


def to_metres(latitude: Any, longitude: Any) -> np.ndarray:
    """(n, 2) array of x, y in metres from the centre of Singapore."""
    lat = np.asarray(latitude, dtype="float64")
    lon = np.asarray(longitude, dtype="float64")
    return np.column_stack([(lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT])


def walk_minutes(metres: float | None, cfg: dict[str, Any]) -> int | None:
    """Minutes to walk a straight-line distance, rounded up, never less than one."""
    if metres is None or (isinstance(metres, float) and math.isnan(metres)):
        return None
    loc = cfg["location"]
    return max(1, math.ceil(float(metres) * loc["detour_factor"] / loc["walk_speed_m_per_min"]))


def ring_metres(minutes: float, cfg: dict[str, Any]) -> float:
    """How far, in a straight line, a walk of `minutes` reaches."""
    loc = cfg["location"]
    return minutes * loc["walk_speed_m_per_min"] / loc["detour_factor"]


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #
def street_key(street: str) -> tuple[str, set[str]]:
    """What a street's HDB code should start with, and letters its third character may be.

    'JLN BT MERAH' -> ('BU', {'M'}); 'BEDOK NTH ST 2' -> ('BE', {'N', 'S'}).
    The codes are built from the street's name, so the first two letters of the
    first real word are a firm check and the initials that follow are a hint.
    """
    words = [w for w in street.upper().split() if w]
    while words and (words[0] in SKIPPED_WORDS or re.fullmatch(r"\d+[A-Z]?", words[0])):
        words = words[1:]
    if not words:
        return "", set()
    first = re.sub(r"[^A-Z]", "", EXPANDED_WORDS.get(words[0], words[0]))
    hints = {re.sub(r"[^A-Z]", "", EXPANDED_WORDS.get(w, w))[:1] for w in words[1:]}
    hints.discard("")
    # A one-word name ('DOVER RD') takes its third letter from the name itself.
    if len(first) > 2:
        hints.add(first[2])
    return first[:2], hints


def match_blocks(addresses: pd.DataFrame, buildings: pd.DataFrame) -> pd.DataFrame:
    """Give every (town, block, street_name) a position.

    Returns the addresses with latitude, longitude, street_code and
    location_source: 'building' (the block's own outline), 'street' (the block
    is not in the outlines, so it sits at the middle of its street) or 'town'
    (the street could not be matched at all).
    """
    by_code: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    codes_of_block: dict[str, set[str]] = defaultdict(set)
    for row in buildings.itertuples(index=False):
        by_code[row.street_code][row.block] = (row.latitude, row.longitude)
        codes_of_block[row.block].add(row.street_code)

    streets = {street: group for street, group in addresses.groupby("street_name")}
    ranked: dict[str, list[tuple[float, bool, str]]] = {}
    for street, group in streets.items():
        prefix, hints = street_key(street)
        blocks = group["block"].tolist()
        hits = Counter(code for block in blocks for code in codes_of_block.get(block, ()) if code[:2] == prefix)
        ranked[street] = sorted(((n / len(blocks), code[2:3] in hints, code) for code, n in hits.items()), reverse=True)

    def centre(points: list[tuple[float, float]]) -> tuple[float, float]:
        return float(np.median([p[0] for p in points])), float(np.median([p[1] for p in points]))

    def placed(street: str, code: str) -> list[tuple[float, float]]:
        return [by_code[code][b] for b in streets[street]["block"] if b in by_code[code]]

    # First pass: streets where one code is clearly the best.
    chosen: dict[str, str] = {}
    for street, options in ranked.items():
        if options and (len(options) == 1 or options[0][:2] > options[1][:2]):
            chosen[street] = options[0][2]
    town_points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for street, code in chosen.items():
        town = streets[street]["town"].mode().iloc[0]
        town_points[town].extend(placed(street, code))
    town_centre = {town: centre(points) for town, points in town_points.items() if points}

    def spread(street: str, code: str) -> float:
        town = streets[street]["town"].mode().iloc[0]
        if town not in town_centre:
            return 0.0
        a = to_metres(*centre(placed(street, code)))[0]
        b = to_metres(*town_centre[town])[0]
        return float(np.hypot(*(a - b)))

    # Second pass: ties go to the code whose blocks sit nearest the rest of the town.
    for street, options in ranked.items():
        if street in chosen or not options:
            continue
        tied = [code for cover, hint, code in options if (cover, hint) == options[0][:2]]
        chosen[street] = min(tied, key=lambda code: spread(street, code))
    for street in [s for s, code in chosen.items() if spread(s, code) > MAX_TOWN_SPREAD_M]:
        del chosen[street]

    out = addresses.copy()
    lat, lon, codes, sources = [], [], [], []
    street_middle = {street: centre(placed(street, code)) for street, code in chosen.items()}
    for row in out.itertuples(index=False):
        code = chosen.get(row.street_name)
        if code and row.block in by_code[code]:
            point, source = by_code[code][row.block], "building"
        elif code:
            point, source = street_middle[row.street_name], "street"
        elif row.town in town_centre:
            point, source = town_centre[row.town], "town"
        else:
            point, source = (float("nan"), float("nan")), "none"
        lat.append(point[0])
        lon.append(point[1])
        codes.append(code)
        sources.append(source)
    out["latitude"], out["longitude"], out["street_code"], out["location_source"] = lat, lon, codes, sources
    return out


# --------------------------------------------------------------------------- #
# Places
# --------------------------------------------------------------------------- #
def clean_places(places: pd.DataFrame) -> pd.DataFrame:
    """Drop places without a position and malls mapped more than once.

    OpenStreetMap often holds a mall as both a building and a point, so malls
    with the same name within about 200 m of each other are kept once.
    """
    frame = places.dropna(subset=["latitude", "longitude"]).copy()
    malls = frame["category"] == "mall"
    key = (
        frame.loc[malls, "name"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
        + "|" + (frame.loc[malls, "latitude"] / 0.002).round().astype(int).astype(str)
        + "|" + (frame.loc[malls, "longitude"] / 0.002).round().astype(int).astype(str)
    )
    frame = frame.drop(index=key[key.duplicated()].index)
    columns = ["category", "kind", "name", "detail", "latitude", "longitude"]
    return frame[columns].sort_values(["category", "name"]).reset_index(drop=True)


def _simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker on an open line of (x, y) metres; returns the kept indices."""
    keep = np.zeros(len(points), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        a, b = points[start], points[end]
        segment = b - a
        length = float(np.hypot(*segment))
        inner = points[start + 1 : end]
        if length:
            distance = np.abs(segment[1] * (inner[:, 0] - a[0]) - segment[0] * (inner[:, 1] - a[1])) / length
        else:
            distance = np.hypot(inner[:, 0] - a[0], inner[:, 1] - a[1])
        worst = int(distance.argmax())
        if distance[worst] > tolerance:
            index = start + 1 + worst
            keep[index] = True
            stack.extend([(start, index), (index, end)])
    return np.flatnonzero(keep)


def simplify_connectors(connectors: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Park connector lines with far fewer points, as [[lat, lon], ...] JSON text."""
    tolerance = cfg["location"]["connector_tolerance_m"]
    rows = []
    for row in connectors.itertuples(index=False):
        line = np.asarray(json.loads(row.geometry_json), dtype="float64")
        if len(line) < 2:
            continue
        kept = line[_simplify(to_metres(line[:, 1], line[:, 0]), tolerance)]
        path = [[round(float(lat), 5), round(float(lon), 5)] for lon, lat in kept]
        rows.append({"name": row.name, "loop": row.loop, "points": len(path), "path_json": json.dumps(path, separators=(",", ":"))})
    return pd.DataFrame(rows, columns=["name", "loop", "points", "path_json"])


def _along(path: np.ndarray, step: float = 25.0) -> np.ndarray:
    """Points every `step` metres along a line of (x, y), so nearest-point search finds the line."""
    out = [path[:1]]
    for a, b in zip(path[:-1], path[1:]):
        n = max(1, int(np.hypot(*(b - a)) // step))
        out.append(a + (b - a) * (np.arange(1, n + 1) / n)[:, None])
    return np.vstack(out)


class PlaceIndex:
    """Nearest-place lookups over every kind of place, built once and reused."""

    def __init__(self, places: pd.DataFrame, connectors: pd.DataFrame | None, cfg: dict[str, Any]):
        self.cfg = cfg
        self.groups: dict[str, pd.DataFrame] = {}
        self.trees: dict[str, cKDTree] = {}
        frames = {
            "mrt": places[(places["category"] == "train") & (places["kind"] == "MRT")],
            "train": places[places["category"] == "train"],
            "bus": places[places["category"] == "bus"],
            "primary": places[(places["category"] == "school") & (places["kind"] == "Primary")],
            "school": places[places["category"] == "school"],
            "mall": places[places["category"] == "mall"],
            "hawker": places[places["category"] == "hawker"],
            "park": places[places["category"] == "park"],
        }
        for key, frame in frames.items():
            if len(frame):
                self.groups[key] = frame.reset_index(drop=True)
                self.trees[key] = cKDTree(to_metres(frame["latitude"], frame["longitude"]))

        self.connector_names: list[str] = []
        self.connector_paths: list[list[list[float]]] = []
        self.connector_tree: cKDTree | None = None
        self.connector_line: np.ndarray = np.empty(0, dtype=int)
        if connectors is not None and len(connectors):
            points, owners = [], []
            for i, row in enumerate(connectors.itertuples(index=False)):
                path = json.loads(row.path_json)
                self.connector_names.append(row.name)
                self.connector_paths.append(path)
                dense = _along(to_metres([p[0] for p in path], [p[1] for p in path]))
                points.append(dense)
                owners.append(np.full(len(dense), i))
            self.connector_tree = cKDTree(np.vstack(points))
            self.connector_line = np.concatenate(owners)

    def has(self, key: str) -> bool:
        return key in self.trees

    def nearest(self, key: str, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(distance in metres, row index into the group) for each point."""
        return self.trees[key].query(xy)

    def count_within(self, key: str, xy: np.ndarray, radius: float) -> np.ndarray:
        return np.asarray(self.trees[key].query_ball_point(xy, r=radius, return_length=True))

    def within(self, key: str, latitude: float, longitude: float, radius: float) -> pd.DataFrame:
        """Places of one kind within `radius` of a point, nearest first, with their distance."""
        if key not in self.trees:
            return pd.DataFrame(columns=["category", "kind", "name", "detail", "latitude", "longitude", "metres"])
        xy = to_metres([latitude], [longitude])[0]
        rows = self.trees[key].query_ball_point(xy, r=radius)
        frame = self.groups[key].iloc[rows].copy()
        frame["metres"] = np.hypot(*(to_metres(frame["latitude"], frame["longitude"]) - xy).T) if len(frame) else []
        return frame.sort_values("metres")

    def connectors_within(self, latitude: float, longitude: float, radius: float) -> list[dict[str, Any]]:
        if self.connector_tree is None:
            return []
        xy = to_metres([latitude], [longitude])[0]
        lines = sorted(set(self.connector_line[self.connector_tree.query_ball_point(xy, r=radius)].tolist()))
        return [{"name": self.connector_names[i], "path": self.connector_paths[i]} for i in lines]


def block_features(blocks: pd.DataFrame, index: PlaceIndex, cfg: dict[str, Any]) -> pd.DataFrame:
    """Distances and counts for every block. Columns for a kind of place the
    index does not hold are left empty, so a missing source never stops the build."""
    loc = cfg["location"]
    xy = to_metres(blocks["latitude"], blocks["longitude"])
    out = pd.DataFrame(index=blocks.index)

    def nearest(key: str, prefix: str, with_kind: bool = False) -> None:
        if not index.has(key):
            out[f"{prefix}_m"] = np.nan
            out[f"{prefix}_name"] = None
            return
        distance, row = index.nearest(key, xy)
        out[f"{prefix}_m"] = np.round(distance, 0)
        out[f"{prefix}_name"] = index.groups[key]["name"].to_numpy()[row]
        if with_kind:
            out[f"{prefix}_kind"] = index.groups[key]["kind"].to_numpy()[row]

    nearest("mrt", "mrt")
    nearest("train", "train", with_kind=True)
    nearest("bus", "bus")
    nearest("primary", "primary")
    nearest("mall", "mall")
    nearest("hawker", "hawker")
    nearest("park", "park")
    out["bus_stops_400m"] = index.count_within("bus", xy, loc["bus_stop_radius_m"]) if index.has("bus") else np.nan
    out["primary_schools_1km"] = index.count_within("primary", xy, loc["school_radius_m"]) if index.has("primary") else np.nan
    if index.connector_tree is not None:
        distance, point = index.connector_tree.query(xy)
        out["connector_m"] = np.round(distance, 0)
        out["connector_name"] = np.asarray(index.connector_names, dtype=object)[index.connector_line[point]]
    else:
        out["connector_m"] = np.nan
        out["connector_name"] = None
    city = to_metres([loc["city_centre"][0]], [loc["city_centre"][1]])[0]
    out["city_km"] = np.round(np.hypot(*(xy - city).T) / 1000, 2)
    for column in ("bus_stops_400m", "primary_schools_1km"):
        out[column] = out[column].astype("float64")
    return out

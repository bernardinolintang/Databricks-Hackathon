"""Turn planning area boundaries into a light SVG map of HDB towns.

HDB towns are not published as shapes, so each town is drawn from the URA
planning area it corresponds to. Two towns need a rule: "CENTRAL AREA" is the
set of planning areas URA flags as Central Area, and "KALLANG/WHAMPOA" is drawn
as the Kallang planning area. The shapes are a guide to where a town is, not a
legal boundary.

Pure Python on purpose (no GIS dependency): project, simplify, emit SVG paths.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

VIEW_WIDTH = 1000.0
TOWN_FOR_AREA = {"KALLANG": "KALLANG/WHAMPOA"}
CENTRAL_TOWN = "CENTRAL AREA"

Point = tuple[float, float]


def town_for_area(planning_area: str, central_area: bool, towns: set[str]) -> str | None:
    """The HDB town a planning area is drawn as, or None for non-town land."""
    if central_area and CENTRAL_TOWN in towns:
        return CENTRAL_TOWN
    town = TOWN_FOR_AREA.get(planning_area, planning_area)
    return town if town in towns else None


def simplify_ring(points: list[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker: drop vertices closer than `tolerance` to the simplified line."""
    if len(points) < 5:
        return points
    closed = points[0] == points[-1]
    ring = points[:-1] if closed else points

    # A closed ring has no natural end points; anchor on its two most distant vertices.
    first = 0
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[first][0]) ** 2 + (ring[i][1] - ring[first][1]) ** 2)
    halves = [ring[first : far + 1], ring[far:] + ring[: first + 1]]

    def reduce(line: list[Point]) -> list[Point]:
        keep = [False] * len(line)
        keep[0] = keep[-1] = True
        stack = [(0, len(line) - 1)]
        while stack:
            start, end = stack.pop()
            (x1, y1), (x2, y2) = line[start], line[end]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            worst, index = 0.0, -1
            for i in range(start + 1, end):
                px, py = line[i]
                distance = abs(dy * (px - x1) - dx * (py - y1)) / length if length else math.hypot(px - x1, py - y1)
                if distance > worst:
                    worst, index = distance, i
            if worst > tolerance and index != -1:
                keep[index] = True
                stack.extend([(start, index), (index, end)])
        return [p for p, k in zip(line, keep) if k]

    a, b = reduce(halves[0]), reduce(halves[1])
    out = a + b[1:]
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def ring_area_and_centroid(points: list[Point]) -> tuple[float, float, float]:
    """Shoelace area (absolute) and centroid of a closed ring."""
    twice_area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if twice_area == 0:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(twice_area) / 2, cx / (3 * twice_area), cy / (3 * twice_area)


def _outer_rings(geometry_type: str, coordinates: list) -> list[list[list[float]]]:
    """Outer ring of every polygon; holes are ignored at this scale."""
    polygons = coordinates if geometry_type == "MultiPolygon" else [coordinates]
    return [polygon[0] for polygon in polygons if polygon]


def _path(rings: list[list[Point]]) -> str:
    parts = []
    for ring in rings:
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in ring[:-1])
        parts.append(f"M{coords}Z")
    return "".join(parts)


def build_town_map(areas: pd.DataFrame, towns: list[str], cfg: dict[str, Any]) -> dict[str, Any]:
    """Project, simplify and group planning areas into town shapes.

    Returns {"view_box": [0, 0, W, H], "towns": [...], "context": [...]} where
    each town has an SVG path, a label point and its region; `context` holds
    the remaining land (catchment, industrial, islands) for the island's outline.
    """
    settings = cfg["town_map"]
    town_set = set(towns)

    parsed = []
    lons, lats = [], []
    for row in areas.itertuples(index=False):
        rings = _outer_rings(row.geometry_type, json.loads(row.geometry_json))
        parsed.append((row, rings))
        for ring in rings:
            lons.extend(p[0] for p in ring)
            lats.extend(p[1] for p in ring)
    if not parsed:
        raise ValueError("No planning areas to draw")

    lon_min, lon_max, lat_min, lat_max = min(lons), max(lons), min(lats), max(lats)
    # Equirectangular projection; one degree of longitude is cos(latitude) as wide.
    k = math.cos(math.radians((lat_min + lat_max) / 2))
    scale = VIEW_WIDTH / ((lon_max - lon_min) * k)
    height = (lat_max - lat_min) * scale

    def project(ring: list[list[float]]) -> list[Point]:
        return [((lon - lon_min) * k * scale, (lat_max - lat) * scale) for lon, lat, *_ in ring]

    grouped: dict[str, dict[str, Any]] = {}
    context = []
    for row, rings in parsed:
        shapes = []
        for ring in rings:
            simple = simplify_ring(project(ring), settings["simplify_tolerance"])
            area, cx, cy = ring_area_and_centroid(simple)
            if area >= settings["min_ring_area"] and len(simple) >= 4:
                shapes.append((simple, area, cx, cy))
        if not shapes:
            continue
        town = town_for_area(row.planning_area, bool(row.central_area), town_set)
        if town is None:
            context.append({"name": row.planning_area, "d": _path([s[0] for s in shapes])})
            continue
        entry = grouped.setdefault(town, {"town": town, "region": row.region, "shapes": [], "areas": []})
        entry["shapes"].extend(shapes)
        entry["areas"].append(row.planning_area)

    town_shapes = []
    for town in sorted(grouped):
        entry = grouped[town]
        total = sum(s[1] for s in entry["shapes"])
        town_shapes.append(
            {
                "town": town,
                "region": entry["region"],
                "d": _path([s[0] for s in entry["shapes"]]),
                # Area-weighted centroid: a stable anchor for the label and tooltip.
                "cx": round(sum(s[2] * s[1] for s in entry["shapes"]) / total, 1),
                "cy": round(sum(s[3] * s[1] for s in entry["shapes"]) / total, 1),
                "area": round(total, 1),
                "merged": len(entry["areas"]) > 1,
                "planning_areas": sorted(entry["areas"]),
            }
        )

    missing = sorted(town_set - set(grouped))
    return {
        "view_box": [0, 0, round(VIEW_WIDTH, 1), round(height, 1)],
        "towns": town_shapes,
        "context": context,
        "missing_towns": missing,
        "points": sum(s["d"].count(",") for s in town_shapes) + sum(c["d"].count(",") for c in context),
    }


def town_map_frame(town_map: dict[str, Any]) -> pd.DataFrame:
    """Flatten the map for a Delta table: one row per drawn shape."""
    height = town_map["view_box"][3]
    rows = [
        {
            "kind": "town",
            "name": t["town"],
            "region": t["region"],
            "svg_path": t["d"],
            "label_x": t["cx"],
            "label_y": t["cy"],
            "area": t["area"],
            "merged": t["merged"],
            "planning_areas": ", ".join(t["planning_areas"]),
            "view_width": VIEW_WIDTH,
            "view_height": height,
        }
        for t in town_map["towns"]
    ]
    rows += [
        {
            "kind": "context", "name": c["name"], "region": None, "svg_path": c["d"], "label_x": None, "label_y": None,
            "area": None, "merged": False, "planning_areas": c["name"], "view_width": VIEW_WIDTH, "view_height": height,
        }
        for c in town_map["context"]
    ]
    return pd.DataFrame(rows)


def town_map_from_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Inverse of town_map_frame, for publishing the serving bundle."""
    towns = frame[frame["kind"] == "town"]
    context = frame[frame["kind"] == "context"]
    return {
        "view_box": [0, 0, float(frame["view_width"].iloc[0]), float(frame["view_height"].iloc[0])],
        "towns": [
            {
                "town": r.name, "region": r.region, "d": r.svg_path, "cx": float(r.label_x), "cy": float(r.label_y),
                "merged": bool(r.merged), "planning_areas": r.planning_areas.split(", "),
            }
            for r in towns.itertuples(index=False)
        ],
        "context": [{"name": r.name, "d": r.svg_path} for r in context.itertuples(index=False)],
    }

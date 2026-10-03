"""Places near a flat: trains, buses, schools, shops, food and parks.

Every source is open data. Most are GeoJSON files on data.gov.sg and need only
a download. Schools come as a table of addresses and are placed with OneMap.
Malls come from OpenStreetMap because no agency publishes a mall list.

Nothing here interprets the data beyond naming it: one row per place, with
where it is and where it came from.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from flatfair.ingestion.datagov import poll_download_url
from flatfair.ingestion.http import USER_AGENT, SourceError, get_with_retries

log = logging.getLogger(__name__)

PLACE_COLUMNS = ["category", "kind", "name", "detail", "latitude", "longitude", "source"]

# A few exits carry the station's line code where its name should be.
STATION_CODES = {
    "CC9": "PAYA LEBAR MRT STATION",
    "CC30": "KEPPEL MRT STATION",
    "CC31": "CANTONMENT MRT STATION",
    "CC32": "PRINCE EDWARD ROAD MRT STATION",
    "DT4": "HUME MRT STATION",
    "DT18": "TELOK AYER MRT STATION",
    "NE18": "PUNGGOL COAST MRT STATION",
}
# The parks file mixes real parks with playgrounds and small open spaces.
PARK_ENDINGS = ("PK", "PARK", "GARDEN", "GARDENS", "GDN", "RESERVE", "GREEN", "PROMENADE")
SCHOOL_KINDS = {
    "PRIMARY": "Primary",
    "MIXED LEVEL (P1-S4)": "Primary",
    "JUNIOR COLLEGE": "Junior college",
    "CENTRALISED INSTITUTE": "Junior college",
}
ONEMAP_TOKEN_ENV = "ONEMAP_TOKEN"


def _http(cfg: dict[str, Any]) -> dict[str, Any]:
    ing = cfg["ingestion"]
    return {"max_retries": ing["max_retries"], "backoff_seconds": ing["backoff_seconds"], "timeout_seconds": ing["timeout_seconds"]}


def download_dataset(cfg: dict[str, Any], dataset_id: str) -> bytes:
    """The current export of a data.gov.sg dataset, whatever its format."""
    return get_with_retries(poll_download_url(cfg, dataset_id), **_http(cfg)).content


def fetch_geojson(cfg: dict[str, Any], dataset_id: str) -> list[dict[str, Any]]:
    try:
        geojson = json.loads(download_dataset(cfg, dataset_id))
    except ValueError as exc:
        raise SourceError(f"Dataset {dataset_id} is not valid JSON") from exc
    features = geojson.get("features") if isinstance(geojson, dict) else None
    if not features:
        raise SourceError(f"Dataset {dataset_id} is not a GeoJSON FeatureCollection")
    return features


def _point(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "Point":
        return None
    lon, lat, *_ = geometry["coordinates"]
    return float(lat), float(lon)


ACRONYMS = {"CHIJ", "SJI", "NUS", "ITE", "II", "III", "IV"}
PARK_WORDS = {"PK": "PARK", "GDN": "GARDEN", "RD": "ROAD", "AVE": "AVENUE", "DR": "DRIVE"}


def _tidy(name: str, expand: dict[str, str] | None = None) -> str:
    """'ST. ANDREW'S JUNIOR SCHOOL' -> 'St. Andrew's Junior School'.

    Names already in mixed case are left alone. `expand` spells out
    abbreviations, e.g. 'TIONG BAHRU PK' -> 'Tiong Bahru Park'.
    """
    words = re.sub(r"\s+", " ", str(name)).strip().split(" ")
    out = []
    for word in words:
        word = (expand or {}).get(word.upper(), word)
        if any(c.islower() for c in word) or word.upper() in ACRONYMS:
            out.append(word)
        else:
            # Capitalise each run of letters; an apostrophe does not start a new one.
            out.append(re.sub(r"(?<![A-Za-z'])([A-Za-z])([A-Za-z']*)", lambda m: m.group(1).upper() + m.group(2).lower(), word))
    return " ".join(out)


def station_rows(features: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """One row per station exit: people walk to the nearest exit, not the middle of the station."""
    rows = []
    for feature in features:
        point = _point(feature)
        properties = feature.get("properties") or {}
        raw = str(properties.get("STATION_NA") or "").strip().upper()
        station = STATION_CODES.get(raw, raw)
        if point is None or not station:
            continue
        kind = "LRT" if "LRT" in station else "MRT"
        name = _tidy(re.sub(r"\s+(MRT|LRT)\s+STATION$", "", station))
        rows.append({"category": "train", "kind": kind, "name": name, "detail": str(properties.get("EXIT_CODE") or "").strip(), "latitude": point[0], "longitude": point[1], "source": source})
    return rows


def bus_stop_rows(features: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    rows = []
    for feature in features:
        point = _point(feature)
        number = str((feature.get("properties") or {}).get("BUS_STOP_NUM") or "").strip()
        if point is None or not number:
            continue
        rows.append({"category": "bus", "kind": None, "name": f"Bus stop {number}", "detail": number, "latitude": point[0], "longitude": point[1], "source": source})
    return rows


def hawker_rows(features: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    rows = []
    for feature in features:
        point = _point(feature)
        properties = feature.get("properties") or {}
        status = str(properties.get("STATUS") or "")
        # Centres still being built are not somewhere to eat yet.
        if point is None or not properties.get("NAME") or not status.startswith("Existing"):
            continue
        rows.append({"category": "hawker", "kind": None, "name": _tidy(properties["NAME"]), "detail": status, "latitude": point[0], "longitude": point[1], "source": source})
    return rows


def park_rows(features: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    rows = []
    for feature in features:
        point = _point(feature)
        name = str((feature.get("properties") or {}).get("NAME") or "").strip().upper()
        if point is None or not name or not name.split(" ")[-1].endswith(PARK_ENDINGS):
            continue
        rows.append({"category": "park", "kind": None, "name": _tidy(name, PARK_WORDS), "detail": None, "latitude": point[0], "longitude": point[1], "source": source})
    return rows


def connector_rows(features: list[dict[str, Any]], source: str) -> pd.DataFrame:
    """Park connector lines, geometry kept as [[lon, lat], ...] JSON text."""
    rows = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if geometry.get("type") == "LineString":
            lines = [geometry["coordinates"]]
        elif geometry.get("type") == "MultiLineString":
            lines = geometry["coordinates"]
        else:
            continue
        for line in lines:
            if len(line) < 2:
                continue
            rows.append(
                {
                    "name": str(properties.get("PARK") or "Park connector").strip(),
                    "loop": str(properties.get("PCN_LOOP") or "").strip() or None,
                    "geometry_json": json.dumps([[p[0], p[1]] for p in line], separators=(",", ":")),
                    "source": source,
                }
            )
    return pd.DataFrame(rows, columns=["name", "loop", "geometry_json", "source"])


def building_rows(features: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per HDB building: block, HDB's street code, postal code and the centre of its outline."""
    rows = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        block = str(properties.get("BLK_NO") or "").strip().upper()
        code = str(properties.get("ST_COD") or "").strip().upper()
        if geometry.get("type") == "Polygon":
            rings = [geometry["coordinates"][0]]
        elif geometry.get("type") == "MultiPolygon":
            rings = [polygon[0] for polygon in geometry["coordinates"] if polygon]
        else:
            continue
        points = [p for ring in rings for p in ring]
        if not block or not code or not points:
            continue
        rows.append(
            {
                "block": block,
                "street_code": code,
                "postal_code": str(properties.get("POSTAL_COD") or "").strip() or None,
                "latitude": sum(p[1] for p in points) / len(points),
                "longitude": sum(p[0] for p in points) / len(points),
            }
        )
    frame = pd.DataFrame(rows, columns=["block", "street_code", "postal_code", "latitude", "longitude"])
    # A block drawn as several outlines (a podium and a tower) is one place.
    return frame.groupby(["block", "street_code"], as_index=False).agg(
        postal_code=("postal_code", "first"), latitude=("latitude", "mean"), longitude=("longitude", "mean")
    )


def geocode_postal(cfg: dict[str, Any], postal_code: str, session: requests.Session) -> tuple[float, float] | None:
    """Where a postal code is, from OneMap. None if OneMap does not know it."""
    onemap = cfg["sources"]["onemap"]
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get(ONEMAP_TOKEN_ENV)
    if token:
        headers["Authorization"] = token
    params = {"searchVal": postal_code, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1}
    for attempt in range(6):
        try:
            response = session.get(onemap["search_url"], params=params, headers=headers, timeout=30)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code == 429:
            time.sleep(4 + 2 * attempt)
            continue
        if response.status_code != 200:
            raise SourceError(f"OneMap search failed with HTTP {response.status_code}")
        results = response.json().get("results") or []
        match = next((r for r in results if str(r.get("POSTAL")) == postal_code), results[0] if results else None)
        return (float(match["LATITUDE"]), float(match["LONGITUDE"])) if match else None
    raise SourceError("OneMap kept refusing requests; try again later")


def school_rows(csv_bytes: bytes, cfg: dict[str, Any], source: str, known: dict[str, tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    """Schools with coordinates. `known` holds postal codes placed on an earlier
    run, so a rerun only asks OneMap about schools it has not seen."""
    table = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False)
    missing = [c for c in ("school_name", "postal_code", "mainlevel_code") if c not in table.columns]
    if missing:
        raise SourceError(f"School list is missing columns: {missing}")
    known = dict(known or {})
    pause = cfg["sources"]["onemap"]["pause_seconds"]
    rows, unplaced = [], 0
    with requests.Session() as session:
        for record in table.itertuples(index=False):
            postal = str(record.postal_code).strip().zfill(6)
            if postal not in known:
                known[postal] = geocode_postal(cfg, postal, session)
                time.sleep(pause)
            if known[postal] is None:
                unplaced += 1
                continue
            level = str(record.mainlevel_code).strip().upper()
            rows.append(
                {
                    "category": "school",
                    "kind": SCHOOL_KINDS.get(level, "Secondary"),
                    "name": _tidy(record.school_name),
                    "detail": postal,
                    "latitude": known[postal][0],
                    "longitude": known[postal][1],
                    "source": source,
                }
            )
    if unplaced:
        log.warning("%d schools could not be placed from their postal code", unplaced)
    return rows


def mall_rows(cfg: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Shopping malls from OpenStreetMap, tried against each Overpass server in turn."""
    query = '[out:json][timeout:90];area["ISO3166-1"="SG"][admin_level=2]->.sg;nwr["shop"="mall"](area.sg);out center tags;'
    last_error = "no server tried"
    for url in cfg["sources"]["places"]["malls"]["overpass_urls"]:
        try:
            response = requests.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=120)
            if response.status_code != 200:
                last_error = f"{url} answered HTTP {response.status_code}"
                continue
            elements = response.json().get("elements") or []
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{url}: {type(exc).__name__}"
            continue
        rows = []
        for element in elements:
            centre = element.get("center") or element
            name = (element.get("tags") or {}).get("name")
            if not name or "lat" not in centre:
                continue
            rows.append({"category": "mall", "kind": None, "name": name.strip(), "detail": None, "latitude": float(centre["lat"]), "longitude": float(centre["lon"]), "source": source})
        if rows:
            return rows
        last_error = f"{url} returned no malls"
    raise SourceError(f"Could not fetch malls from OpenStreetMap ({last_error})")


def fetch_places(cfg: dict[str, Any], known_schools: dict[str, tuple[float, float]] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Every kind of place the app shows, plus the park connector lines.

    A source that cannot be reached is skipped with a note, not a failure:
    the app simply leaves that kind of place out.
    """
    sources = cfg["sources"]["places"]
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    connectors = pd.DataFrame(columns=["name", "loop", "geometry_json", "source"])

    def tag(key: str) -> str:
        return f"data.gov.sg:{sources[key]['dataset_id']}"

    point_sources = [("mrt_exits", station_rows), ("bus_stops", bus_stop_rows), ("hawker_centres", hawker_rows), ("parks", park_rows)]
    for key, parse in point_sources:
        try:
            found = parse(fetch_geojson(cfg, sources[key]["dataset_id"]), tag(key))
        except SourceError as exc:
            notes.append(f"{sources[key]['name']} unavailable: {exc}")
            log.warning(notes[-1])
            continue
        log.info("%s: %d places", sources[key]["name"], len(found))
        rows.extend(found)

    try:
        connectors = connector_rows(fetch_geojson(cfg, sources["park_connectors"]["dataset_id"]), tag("park_connectors"))
        log.info("%s: %d lines", sources["park_connectors"]["name"], len(connectors))
    except SourceError as exc:
        notes.append(f"{sources['park_connectors']['name']} unavailable: {exc}")
        log.warning(notes[-1])

    try:
        found = school_rows(download_dataset(cfg, sources["schools"]["dataset_id"]), cfg, tag("schools"), known_schools)
        log.info("%s: %d schools placed", sources["schools"]["name"], len(found))
        rows.extend(found)
    except SourceError as exc:
        notes.append(f"{sources['schools']['name']} unavailable: {exc}")
        log.warning(notes[-1])

    try:
        found = mall_rows(cfg, "openstreetmap:shop=mall")
        log.info("%s: %d malls", sources["malls"]["name"], len(found))
        rows.extend(found)
    except SourceError as exc:
        notes.append(f"{sources['malls']['name']} unavailable: {exc}")
        log.warning(notes[-1])

    places = pd.DataFrame(rows, columns=PLACE_COLUMNS)
    places["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return places, connectors, notes


def fetch_buildings(cfg: dict[str, Any]) -> pd.DataFrame:
    frame = building_rows(fetch_geojson(cfg, cfg["sources"]["hdb_buildings"]["dataset_id"]))
    if frame.empty:
        raise SourceError("HDB building outlines had no usable features")
    frame["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return frame

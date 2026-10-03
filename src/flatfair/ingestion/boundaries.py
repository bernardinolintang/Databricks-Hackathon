"""URA planning area boundaries from data.gov.sg, used to draw the town map."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from flatfair.ingestion.datagov import poll_download_url
from flatfair.ingestion.http import SourceError, get_with_retries

log = logging.getLogger(__name__)

# Older exports carry attributes inside an HTML description instead of properties.
_DESCRIPTION_FIELD = r"<th>{field}</th>\s*<td>([^<]*)</td>"


def _property(properties: dict[str, Any], field: str) -> str | None:
    value = properties.get(field)
    if value:
        return str(value).strip()
    match = re.search(_DESCRIPTION_FIELD.format(field=field), str(properties.get("Description", "")))
    return match.group(1).strip() if match else None


def fetch_planning_areas(cfg: dict[str, Any]) -> dict[str, Any]:
    """Download the planning area GeoJSON via data.gov.sg's poll-download."""
    ing = cfg["ingestion"]
    url = poll_download_url(cfg, cfg["sources"]["planning_areas"]["dataset_id"])
    response = get_with_retries(
        url, max_retries=ing["max_retries"], backoff_seconds=ing["backoff_seconds"], timeout_seconds=ing["timeout_seconds"]
    )
    try:
        geojson = response.json()
    except ValueError as exc:
        raise SourceError("Planning area download is not valid JSON") from exc
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        raise SourceError("Planning area download is not a GeoJSON FeatureCollection")
    return geojson


def planning_areas_frame(geojson: dict[str, Any]) -> pd.DataFrame:
    """One bronze row per planning area; the geometry is kept verbatim as JSON text."""
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for feature in geojson["features"]:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        name = _property(properties, "PLN_AREA_N")
        if not name or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            log.warning("Skipping a planning area feature without a name or polygon geometry")
            continue
        rows.append(
            {
                "planning_area": name.upper(),
                "region": (_property(properties, "REGION_N") or "").upper() or None,
                "central_area": (_property(properties, "CA_IND") or "N").upper() == "Y",
                "geometry_type": geometry["type"],
                "geometry_json": json.dumps(geometry["coordinates"], separators=(",", ":")),
                "_ingested_at": ingested_at,
            }
        )
    if not rows:
        raise SourceError("No usable planning area features found")
    return pd.DataFrame(rows)

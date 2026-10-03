"""data.gov.sg client for the HDB resale dataset.

Only API concerns live here: paging, retries, schema inspection. Nothing in this
module interprets the data; bronze stores exactly what the source returned.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from flatfair.ingestion.http import SourceError, get_with_retries

log = logging.getLogger(__name__)

# Columns the datastore API adds that are not part of the published dataset.
API_INTERNAL_COLUMNS = {"_id", "_full_text", "rank"}


@dataclass
class IngestionInfo:
    dataset_id: str
    method: str
    rows: int
    api_total_rows: int | None
    columns: list[str]
    missing_columns: list[str]
    unexpected_columns: list[str]
    source_last_updated: str | None
    ingested_at: str
    snapshot_sha256: str
    pages: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _http_kwargs(cfg: dict[str, Any]) -> dict[str, Any]:
    ing = cfg["ingestion"]
    return {
        "max_retries": ing["max_retries"],
        "backoff_seconds": ing["backoff_seconds"],
        "timeout_seconds": ing["timeout_seconds"],
    }


def fetch_metadata(cfg: dict[str, Any]) -> dict[str, Any]:
    src = cfg["sources"]["hdb_resale"]
    url = src["metadata_url"].format(dataset_id=src["dataset_id"])
    payload = get_with_retries(url, **_http_kwargs(cfg)).json()
    if payload.get("code") != 0 or "data" not in payload:
        raise SourceError(f"Unexpected metadata response from {url}: {str(payload)[:200]}")
    return payload["data"]


def fetch_page(cfg: dict[str, Any], offset: int, limit: int, session: requests.Session | None = None) -> dict[str, Any]:
    """One datastore_search page. Sorted by _id so paging is stable across requests."""
    src = cfg["sources"]["hdb_resale"]
    params = {"resource_id": src["dataset_id"], "limit": limit, "offset": offset, "sort": "_id asc"}
    payload = get_with_retries(src["datastore_url"], params=params, session=session, **_http_kwargs(cfg)).json()
    if not payload.get("success") or "result" not in payload:
        raise SourceError(f"datastore_search returned an error at offset {offset}: {str(payload)[:200]}")
    return payload["result"]


def fetch_schema_and_total(cfg: dict[str, Any]) -> tuple[list[str], int]:
    result = fetch_page(cfg, offset=0, limit=1)
    columns = [f["id"] for f in result["fields"] if f["id"] not in API_INTERNAL_COLUMNS]
    return columns, int(result["total"])


def fetch_paginated(cfg: dict[str, Any], max_pages: int | None = None) -> tuple[pd.DataFrame, int, int]:
    """Page through datastore_search until every row is collected.

    Returns (frame, api_total, pages). `max_pages` exists for smoke tests only.
    """
    page_size = cfg["ingestion"]["page_size"]
    pause = cfg["ingestion"]["page_pause_seconds"]
    records: list[dict[str, Any]] = []
    total: int | None = None
    offset = 0
    pages = 0
    with requests.Session() as session:
        while total is None or offset < total:
            result = fetch_page(cfg, offset=offset, limit=page_size, session=session)
            total = int(result["total"])
            batch = result["records"]
            if not batch:
                # The API reports more rows than it returns; stop instead of looping forever.
                log.warning("Empty page at offset %d although total is %d", offset, total)
                break
            records.extend(batch)
            offset += len(batch)
            pages += 1
            log.info("Fetched page %d: %s / %s rows", pages, f"{offset:,}", f"{total:,}")
            if max_pages is not None and pages >= max_pages:
                break
            time.sleep(pause)
    frame = pd.DataFrame.from_records(records)
    if "_id" in frame.columns:
        # A dataset refresh mid-run can shift offsets and repeat rows.
        before = len(frame)
        frame = frame.drop_duplicates(subset="_id").sort_values("_id")
        if len(frame) != before:
            log.warning("Dropped %d rows repeated across pages", before - len(frame))
    frame = frame.drop(columns=[c for c in frame.columns if c in API_INTERNAL_COLUMNS])
    return frame.reset_index(drop=True), int(total or 0), pages


def fetch_bulk_csv(cfg: dict[str, Any]) -> pd.DataFrame:
    """Download the full snapshot CSV that data.gov.sg generates for the dataset."""
    src = cfg["sources"]["hdb_resale"]
    poll_url = src["download_url"].format(dataset_id=src["dataset_id"])
    # The export is generated on demand; poll until the signed URL is ready.
    for _ in range(10):
        payload = get_with_retries(poll_url, **_http_kwargs(cfg)).json()
        data = payload.get("data") or {}
        if payload.get("code") != 0:
            raise SourceError(f"poll-download failed: {str(payload)[:200]}")
        if data.get("status") == "DOWNLOAD_SUCCESS" and data.get("url"):
            csv_bytes = get_with_retries(data["url"], **_http_kwargs(cfg)).content
            # Everything is read as text: bronze must not reinterpret source values.
            return pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False)
        time.sleep(3)
    raise SourceError("poll-download did not produce a file after 10 polls")


def read_local_csv(path: str) -> pd.DataFrame:
    """Fallback when the workspace cannot reach data.gov.sg: the same CSV,
    downloaded from the dataset page and uploaded to a volume."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _snapshot_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(",".join(frame.columns).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return digest.hexdigest()


def ingest_hdb_resale(
    cfg: dict[str, Any],
    method: str | None = None,
    max_pages: int | None = None,
    source_csv: str | None = None,
) -> tuple[pd.DataFrame, IngestionInfo]:
    """Fetch the full dataset as a bronze frame plus an audit record.

    Bronze is a full snapshot replaced on every run, so reruns never duplicate
    rows. The audit record carries a content hash so a no-change rerun is visible.
    `source_csv` (method "file") reads an uploaded copy instead of the network.
    """
    src = cfg["sources"]["hdb_resale"]
    method = "file" if source_csv else (method or cfg["ingestion"]["method"])
    expected = list(src["expected_columns"])
    notes: list[str] = []

    if method == "file":
        frame = read_local_csv(source_csv)
        api_columns, api_total = list(frame.columns), len(frame)
        notes.append(f"Read from uploaded file {source_csv}")
    else:
        api_columns, api_total = fetch_schema_and_total(cfg)
    missing = [c for c in expected if c not in api_columns]
    unexpected = [c for c in api_columns if c not in expected]
    if missing:
        raise SourceError(f"Source schema changed: expected columns missing from the source: {missing}")
    if unexpected:
        notes.append(f"New source columns kept in bronze but unused downstream: {unexpected}")

    pages = 0
    if method == "file":
        pass
    elif method == "bulk":
        try:
            frame = fetch_bulk_csv(cfg)
        except SourceError as exc:
            log.warning("Bulk download failed (%s); falling back to the paginated API", exc)
            notes.append(f"Bulk download failed, used paginated API: {exc}")
            method = "api"
    if method == "api":
        frame, api_total, pages = fetch_paginated(cfg, max_pages=max_pages)
    elif method not in ("bulk", "file"):
        raise ValueError(f"Unknown ingestion method '{method}' (use 'bulk', 'api' or a source_csv)")

    frame_missing = [c for c in expected if c not in frame.columns]
    if frame_missing:
        raise SourceError(f"Downloaded data is missing expected columns: {frame_missing}")
    if max_pages is None and len(frame) != api_total:
        # The export file and the live datastore can be a refresh apart.
        notes.append(f"Row count {len(frame):,} differs from API total {api_total:,}")
        log.warning(notes[-1])

    frame = frame.astype(str)
    try:
        last_updated = fetch_metadata(cfg).get("lastUpdatedAt")
    except (SourceError, requests.RequestException) as exc:
        last_updated = None
        notes.append(f"Metadata unavailable: {exc}")

    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    info = IngestionInfo(
        dataset_id=src["dataset_id"],
        method=method,
        rows=len(frame),
        api_total_rows=api_total,
        columns=list(frame.columns),
        missing_columns=missing,
        unexpected_columns=unexpected,
        source_last_updated=last_updated,
        ingested_at=ingested_at,
        snapshot_sha256=_snapshot_hash(frame),
        pages=pages,
        notes=notes,
    )
    frame["_ingested_at"] = ingested_at
    frame["_source"] = f"data.gov.sg:{src['dataset_id']}:{method}"
    log.info("Ingested %s rows via %s (API total %s)", f"{len(frame):,}", method, f"{api_total:,}")
    return frame, info

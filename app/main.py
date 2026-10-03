"""FlatFair web app: a JSON API plus a static single-page front end.

Runs unchanged in three places:
  local          uvicorn app.main:app --reload
  Databricks     Databricks Apps (see app.yaml), bundle read from a UC volume
  Vercel         zero-config FastAPI entrypoint (see vercel.json)
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Vercel and Databricks load this file directly, so make both the repo root
# (for `app.services`) and `src` (for `flatfair`) importable.
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.services import market as market_service  # noqa: E402
from app.services import outlook, personal  # noqa: E402
from app.services.bundle import Bundle, BundleError, load_bundle  # noqa: E402
from app.services.common import ALL, InputError, to_json  # noqa: E402

log = logging.getLogger("flatfair.app")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@lru_cache(maxsize=1)
def bundle() -> Bundle:
    return load_bundle()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        bundle()
    except BundleError as exc:
        # Keep serving so /api/health can explain what is missing.
        log.error("Serving bundle unavailable: %s", exc)
    yield


app = FastAPI(title="FlatFair", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)


@app.exception_handler(InputError)
async def input_error(_: Request, exc: InputError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(BundleError)
async def bundle_error(_: Request, exc: BundleError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": str(exc)})


def ok(payload: dict) -> JSONResponse:
    return JSONResponse(to_json(payload))


@app.get("/api/health")
def health() -> JSONResponse:
    try:
        b = bundle()
    except BundleError as exc:
        return JSONResponse(status_code=503, content={"status": "unavailable", "error": str(exc)})
    return ok({"status": "ok", "last_complete_month": b.meta["last_complete_month"], "transactions": len(b.transactions)})


@app.get("/api/meta")
def meta() -> JSONResponse:
    return ok(market_service.meta_payload(bundle()))


@app.get("/api/overview")
def overview() -> JSONResponse:
    return ok(market_service.overview(bundle()))


@app.get("/api/market")
def market(
    town: str = ALL,
    flat_type: str = ALL,
    storey: str = ALL,
    flat_model: str = ALL,
    year_from: int | None = Query(None, ge=2017, le=2100),
    year_to: int | None = Query(None, ge=2017, le=2100),
) -> JSONResponse:
    return ok(market_service.market(bundle(), town, flat_type, storey, flat_model, year_from, year_to))


@app.get("/api/forecast")
def forecast(town: str = "TAMPINES", flat_type: str = "4 ROOM") -> JSONResponse:
    return ok(outlook.forecast(bundle(), town, flat_type))


@app.get("/api/affordability")
def affordability(
    income: float = Query(..., gt=0, le=1_000_000),
    cash: float = Query(0, ge=0, le=20_000_000),
    flat_type: str = "4 ROOM",
    town: str = ALL,
    price: float | None = Query(None, gt=0, le=10_000_000),
    max_repayment: float | None = Query(None, gt=0, le=1_000_000),
    rate: float | None = Query(None, ge=0, le=0.2),
    tenure: int | None = Query(None, ge=5, le=35),
    ltv: float | None = Query(None, gt=0, le=1),
) -> JSONResponse:
    return ok(personal.affordability(bundle(), income, cash, flat_type, town, price, max_repayment, rate, tenure, ltv))


@app.get("/api/fair-value/typical")
def typical(town: str, flat_type: str) -> JSONResponse:
    return ok(personal.typical_flat(bundle(), town, flat_type))


@app.get("/api/fair-value")
def fair_value(
    town: str,
    flat_type: str,
    floor_area: float = Query(..., gt=0, le=400),
    storey_range: str = Query(..., min_length=3, max_length=12),
    remaining_lease: float = Query(..., gt=0, le=99),
    flat_model: str | None = None,
    asking_price: float | None = Query(None, ge=0, le=10_000_000),
) -> JSONResponse:
    return ok(personal.fair_value(bundle(), town, flat_type, floor_area, storey_range, remaining_lease, flat_model, asking_price))


@app.get("/api/compare")
def compare(
    towns: str = Query(..., description="Comma-separated, up to three"),
    flat_type: str = "4 ROOM",
    income: float | None = Query(None, gt=0, le=1_000_000),
    cash: float | None = Query(None, ge=0, le=20_000_000),
) -> JSONResponse:
    names = [t.strip() for t in towns.split(",") if t.strip()]
    return ok(outlook.compare(bundle(), names, flat_type, income, cash))


@app.get("/api/{rest:path}", include_in_schema=False)
def api_not_found(rest: str) -> JSONResponse:
    raise HTTPException(status_code=404, detail=f"No API route /api/{rest}")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Architecture

## Flow

```
                ┌──────────────────────────┐        ┌───────────────────────────┐
                │ data.gov.sg              │        │ SingStat Table Builder    │
                │ HDB resale (d_8b84c4ee…) │        │ M810361 household income  │
                └────────────┬─────────────┘        └─────────────┬─────────────┘
          bulk snapshot / paged API, retries,                      │
          schema check, row-count check                            │
                             ▼                                     ▼
 BRONZE   bronze_hdb_resale (text, full snapshot)   bronze_income   bronze_ingestion_log (append)
          bronze_planning_areas (URA)   bronze_hdb_buildings (HDB outlines)
          bronze_places (LTA, MOE + OneMap, NEA, NParks, OpenStreetMap)   bronze_park_connectors (NParks)
                             │
                             │ parse lease / storey / month, type, standardise,
                             │ 9 validity checks, flag duplicates and unusual prices
                             ▼
 SILVER   silver_hdb_resale (+ is_valid, invalid_reasons, is_duplicate, is_price_outlier, exclude_from_model)
          gold_data_quality
                             │
                             ▼
 GOLD     gold_market_monthly   gold_town_summary   gold_flat_type_summary   gold_market_index
          gold_affordability    gold_comparable_transactions   gold_town_map
          gold_block_locations (each block's position and what is near it)   gold_places   gold_park_connectors
                             │
             ┌───────────────┴────────────────┐
             ▼                                ▼
 ML       forecast backtest (4 methods)    fair value (rule / ridge / boosting, with and without location)
          → gold_forecast, _metrics,        → gold_fair_value_metrics, _importance
            _backtest, _features              → UC model workspace.flatfair.flatfair_fair_value
          MLflow experiment /Shared/flatfair (parent + child runs, params, metrics, artifacts)
             └───────────────┬────────────────┘
                             ▼
 SERVE    /Volumes/workspace/flatfair/serving  (≈8 MB: parquet + model + meta.json)
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
     Databricks Apps (app.yaml)       Vercel (public demo, same code)
     FastAPI JSON API + static SPA

 SQL      v_town_4room_latest, v_monthly_from_silver, v_forecast_vs_now, v_price_by_train_walk  → dashboards, Genie, lineage
```

## Why this shape

| Decision | Reason |
|---|---|
| Pandas for transforms, Spark/Delta for storage | ~240k rows fit comfortably in memory. One tested Python package runs identically on a laptop and in a notebook. Spark gives Delta, Unity Catalog, SQL and lineage. |
| Full-snapshot bronze | The source republishes the whole dataset. Overwriting the snapshot makes reruns idempotent; an append-only log records each run with a content hash. |
| Flags instead of deletes | Judges and users can see exactly what was excluded and why. Every consumer states its own filter. |
| Serving bundle instead of per-request SQL | Free Edition has one 2X-Small warehouse. The app loads ~8 MB once and answers every request from memory in under 150 ms. |
| Medians computed on request in the app | A median of medians is not a median. Arbitrary filters (town × type × storey × model × years) are recomputed from transactions. |
| One FastAPI app for Databricks Apps and Vercel | The same artifact runs behind workspace login for judges and publicly for a shareable link. |
| Town map drawn from open boundary data | URA planning areas from data.gov.sg are simplified in the pipeline into SVG paths (34 KB). No map tiles, API key or third-party service, and it works offline. |
| Blocks placed from HDB's own outlines | One download of HDB Existing Building places all 9,755 blocks. Geocoding each address with OneMap would take about three hours at its anonymous rate limit and would tie the pipeline to a service that asks for a token. OneMap is used only for 337 schools, and those lookups are cached in bronze. |
| Distances worked out in the pipeline | Each block's distance to every kind of place is computed once with a k-d tree and stored in `gold_block_locations`. The app only looks up a row; it rebuilds the small place index lazily for the "what's nearby" list. |
| Street map only where a street matters | The Fair value page draws a block and its surroundings on OneMap's base map with Leaflet, loaded on first use. Every other page keeps the offline town map. If the map tiles fail, the distances and the list still work. |
| Optional steps degrade, never block | The town map and the places step each warn and move on if their source is unreachable. Without places the price model trains on the flat's own details and the app hides the address picker and street map. |

## Storage abstraction

`src/flatfair/storage.py` defines `LocalStore` (parquet under `data/`) and `DeltaStore` (Delta in `catalog.schema`). Pipeline steps take a store, so `run_pipeline.py` and the notebooks call the same functions. `DeltaStore.write` converts pandas nullable dtypes for Spark, overwrites with schema evolution, and applies the Unity Catalog comment and tags from `governance.py`.

## Free Edition fit

* Serverless notebooks only; no clusters to manage.
* One schema, one volume, about 28 small tables.
* No model serving endpoint needed: the model runs inside the app process.
* One of three allowed apps.
* The heaviest step, the forecast backtest, trains six small boosted models in about 20 seconds on a laptop.

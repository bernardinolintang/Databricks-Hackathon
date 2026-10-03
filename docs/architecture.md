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
                             │
                             │ parse lease / storey / month, type, standardise,
                             │ 9 validity checks, flag duplicates and unusual prices
                             ▼
 SILVER   silver_hdb_resale (+ is_valid, invalid_reasons, is_duplicate, is_price_outlier, exclude_from_model)
          gold_data_quality
                             │
                             ▼
 GOLD     gold_market_monthly   gold_town_summary   gold_flat_type_summary   gold_market_index
          gold_affordability    gold_comparable_transactions
                             │
             ┌───────────────┴────────────────┐
             ▼                                ▼
 ML       forecast backtest (4 methods)    fair value (rule / ridge / gradient boosting)
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

 SQL      v_town_4room_latest, v_monthly_from_silver, v_forecast_vs_now  → dashboards, Genie, lineage
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

## Storage abstraction

`src/flatfair/storage.py` defines `LocalStore` (parquet under `data/`) and `DeltaStore` (Delta in `catalog.schema`). Pipeline steps take a store, so `run_pipeline.py` and the notebooks call the same functions. `DeltaStore.write` converts pandas nullable dtypes for Spark, overwrites with schema evolution, and applies the Unity Catalog comment and tags from `governance.py`.

## Free Edition fit

* Serverless notebooks only; no clusters to manage.
* One schema, one volume, about 20 small tables.
* No model serving endpoint needed: the model runs inside the app process.
* One of three allowed apps.
* The heaviest step, the forecast backtest, trains six small boosted models in about 20 seconds on a laptop.

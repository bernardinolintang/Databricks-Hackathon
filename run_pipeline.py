"""Run the FlatFair pipeline locally.

    python run_pipeline.py                 # every step
    python run_pipeline.py gold forecast   # selected steps
    python run_pipeline.py ingest --method api
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from flatfair.config import load_config, local_data_dir  # noqa: E402
from flatfair.pipeline import STEPS, run  # noqa: E402
from flatfair.storage import LocalStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FlatFair data and model pipeline locally.")
    parser.add_argument("steps", nargs="*", help=f"steps to run, from: {', '.join(STEPS)} (default: all)")
    parser.add_argument("--method", choices=["bulk", "api"], help="ingestion method (default: config)")
    parser.add_argument("--no-mlflow", action="store_true", help="skip MLflow logging")
    parser.add_argument("--boundaries-file", help="planning area GeoJSON downloaded from data.gov.sg (skips the download)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg = load_config()
    data_dir = local_data_dir(cfg)
    store = LocalStore(data_dir)
    results = run(store, cfg, data_dir / "serving", steps=args.steps or None, method=args.method, track=not args.no_mlflow, boundaries_file=args.boundaries_file)

    print("\nPipeline finished:", ", ".join(results))
    if "transform" in results:
        q = results["transform"]
        print(f"  rows {q['total_rows']:,} | valid {q['valid_rows']:,} | invalid {q['invalid_rows']:,} | "
              f"duplicates {q['duplicate_rows']:,} | latest month {q['latest_month']}")
    if "forecast" in results:
        print("  forecast method:", results["forecast"]["selected_method"])
    if "boundaries" in results:
        b = results["boundaries"]
        print("  town map:", f"{b['towns_drawn']} towns, {b['points']:,} points" if b.get("available") else f"skipped ({b.get('reason')})")
    if "fairvalue" in results:
        print("  fair value model:", results["fairvalue"]["selected_model"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fetch NESO national carbon intensity for a calendar year.

Loops /intensity/{from}/{to} in 14-day windows and also grabs the live
/intensity/factors snapshot.

    python pull_neso_2023.py --out-dir Data --year 2023
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://api.carbonintensity.org.uk"
WINDOW_DAYS = 14
TIMEOUT = 30
SLEEP_S = 1.0


def iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def fetch_window(start: datetime, end: datetime) -> list[dict]:
    r = requests.get(f"{BASE_URL}/intensity/{iso_z(start)}/{iso_z(end)}",
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("data", [])


def fetch_factors() -> dict:
    r = requests.get(f"{BASE_URL}/intensity/factors", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--year", type=int, default=2023)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    start = datetime(args.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(args.year + 1, 1, 1, tzinfo=timezone.utc)
    rows: list[dict] = []
    cur = start
    n_windows = 0
    while cur < end:
        window_end = min(cur + timedelta(days=WINDOW_DAYS), end)
        n_windows += 1
        print(f"  {iso_z(cur)} .. {iso_z(window_end)}")
        try:
            rows.extend(fetch_window(cur, window_end))
        except requests.RequestException as e:
            print(f"    retry after error: {e}")
            time.sleep(5)
            rows.extend(fetch_window(cur, window_end))
        cur = window_end
        time.sleep(SLEEP_S)

    print(f"fetched {len(rows)} half-hour rows over {n_windows} windows")

    df = pd.DataFrame([{
        "from": r.get("from"),
        "to":   r.get("to"),
        "forecast": (r.get("intensity") or {}).get("forecast"),
        "actual":   (r.get("intensity") or {}).get("actual"),
        "index":    (r.get("intensity") or {}).get("index"),
    } for r in rows])
    df["from"] = pd.to_datetime(df["from"], utc=True, errors="coerce")
    df["to"]   = pd.to_datetime(df["to"],   utc=True, errors="coerce")
    df = df.sort_values("from").drop_duplicates(subset=["from"])

    out_csv = args.out_dir / "national_intensity.csv"
    df.to_csv(out_csv, index=False)
    print(f"-> {out_csv} ({len(df)} rows)")

    (args.out_dir / "factors.json").write_text(
        json.dumps(fetch_factors(), indent=2), encoding="utf-8")
    print(f"-> {args.out_dir / 'factors.json'}")


if __name__ == "__main__":
    main()

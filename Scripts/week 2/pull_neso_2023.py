"""
Fetch NESO national carbon intensity truth data for calendar year 2023.

Loops `https://api.carbonintensity.org.uk/intensity/{from}/{to}` in
14-day windows from 2023-01-01T00:00Z to 2024-01-01T00:00Z and
concatenates into one CSV per snapshot. Also fetches the live
`/intensity/factors` table for the record.

Usage
-----
    python scripts/pull_neso_2023.py --out-dir results/neso_2023
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import requests


BASE_URL = "https://api.carbonintensity.org.uk"
WINDOW_DAYS = 14
TIMEOUT = 30  # seconds
SLEEP_S = 1.0


def iso_z(dt: datetime) -> str:
    """ISO 8601 'YYYY-MM-DDTHH:MMZ' (NESO accepts this form)."""
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def fetch_window(start: datetime, end: datetime) -> list[dict]:
    """Pull `/intensity/{from}/{to}` for one [start, end) window."""
    url = f"{BASE_URL}/intensity/{iso_z(start)}/{iso_z(end)}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("data", [])


def fetch_factors() -> dict:
    """Pull `/intensity/factors` snapshot."""
    r = requests.get(f"{BASE_URL}/intensity/factors", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Directory for outputs.")
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
        print(f"  window {n_windows}: {iso_z(cur)} .. {iso_z(window_end)}")
        try:
            window_rows = fetch_window(cur, window_end)
        except requests.RequestException as e:
            print(f"    failed: {e}; sleeping 5s and retrying once")
            time.sleep(5)
            window_rows = fetch_window(cur, window_end)
        rows.extend(window_rows)
        cur = window_end
        time.sleep(SLEEP_S)

    print(f"fetched {len(rows)} half-hour rows over {n_windows} windows")

    df = pd.DataFrame([
        {
            "from": r.get("from"),
            "to":   r.get("to"),
            "forecast": (r.get("intensity") or {}).get("forecast"),
            "actual":   (r.get("intensity") or {}).get("actual"),
            "index":    (r.get("intensity") or {}).get("index"),
        }
        for r in rows
    ])
    df["from"] = pd.to_datetime(df["from"], utc=True, errors="coerce")
    df["to"]   = pd.to_datetime(df["to"],   utc=True, errors="coerce")
    df = df.sort_values("from").drop_duplicates(subset=["from"])

    out_csv = args.out_dir / "national_intensity.csv"
    df.to_csv(out_csv, index=False)
    print(f"wrote {out_csv}  ({len(df)} rows)")

    factors = fetch_factors()
    out_factors = args.out_dir / "factors.json"
    out_factors.write_text(json.dumps(factors, indent=2), encoding="utf-8")
    print(f"wrote {out_factors}")


if __name__ == "__main__":
    main()

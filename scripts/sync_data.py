#!/usr/bin/env python3
"""Sync the three-city public snapshot from the Keli API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


API_BASE = os.getenv("KELI_API_BASE", "http://139.224.105.7").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DETAIL_DIR = DATA_DIR / "details"
CITY_CODES = ("310000", "520100", "532800")
CITY_FALLBACK = {
    "310000": {"id": "310000", "city_code": "310000", "name": "上海", "country": "中国", "latitude": 31.2304, "longitude": 121.4737},
    "520100": {"id": "520100", "city_code": "520100", "name": "贵阳", "country": "中国", "latitude": 26.6477, "longitude": 106.6302},
    "532800": {"id": "532800", "city_code": "532800", "name": "西双版纳", "country": "中国", "latitude": 22.0088, "longitude": 100.7978},
}


def fetch_json(path: str) -> object:
    request = urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "keli-pages-sync/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def sync_detail(hotel_id: int) -> int:
    detail = fetch_json(f"/api/hotels/{hotel_id}")
    write_json(DETAIL_DIR / f"{hotel_id}.json", detail)
    return hotel_id


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)

    remote_cities = fetch_json("/api/cities")
    by_code = {str(item.get("city_code")): item for item in remote_cities if isinstance(item, dict)}
    cities = [by_code.get(code, CITY_FALLBACK[code]) for code in CITY_CODES]
    write_json(DATA_DIR / "cities.json", cities)

    rated_ids: set[int] = set()
    counts: dict[str, dict[str, int]] = {}
    for city_code in CITY_CODES:
        hotels = fetch_json(f"/api/hotels?city_code={city_code}&limit=3000")
        write_json(DATA_DIR / f"hotels-{city_code}.json", hotels)
        city_rated_ids = {int(hotel["id"]) for hotel in hotels if hotel.get("safety_score") is not None}
        rated_ids.update(city_rated_ids)
        status_counts = {
            "environment_scored": 0,
            "deep_audited": 0,
            "evidence_insufficient": 0,
            "pending": 0,
        }
        for hotel in hotels:
            status = str(hotel.get("audit_status") or "pending")
            status_counts[status if status in status_counts else "pending"] += 1
        counts[city_code] = {
            "total": len(hotels),
            "rated": len(city_rated_ids),
            **status_counts,
        }

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(sync_detail, hotel_id) for hotel_id in sorted(rated_ids)]
        for future in as_completed(futures):
            future.result()

    for existing in DETAIL_DIR.glob("*.json"):
        if int(existing.stem) not in rated_ids:
            existing.unlink()

    write_json(
        DATA_DIR / "snapshot.json",
        {"cities": counts, "generated_at": datetime.now(timezone.utc).isoformat()},
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise SystemExit(f"snapshot sync failed: {error}") from error

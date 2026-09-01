#!/usr/bin/env python3
"""Validate a generated public snapshot before it is published."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


CITY_CODES = ("310000", "520100", "532800")
MINIMUM_COUNTS = {"310000": 2000, "520100": 800, "532800": 200}
STATUS_NAMES = ("environment_scored", "deep_audited", "evidence_insufficient", "pending")


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def fail(message: str) -> None:
    raise SystemExit(f"snapshot validation failed: {message}")


def hotel_rows(root: Path, city_code: str) -> list[dict[str, object]]:
    value = read_json(root / "data" / f"hotels-{city_code}.json")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        fail(f"hotels-{city_code}.json is not a list of objects")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--previous-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    data_dir = root / "data"

    if data_dir.is_symlink():
        fail("data directory must not be a symlink")
    allowed = {"cities.json", "snapshot.json", "details", *(f"hotels-{code}.json" for code in CITY_CODES)}
    extras = sorted(path.name for path in data_dir.iterdir() if path.name not in allowed)
    if extras:
        fail(f"unexpected data files: {', '.join(extras)}")

    cities = read_json(data_dir / "cities.json")
    if not isinstance(cities, list):
        fail("cities.json is not a list")
    city_codes = [str(item.get("city_code")) for item in cities if isinstance(item, dict)]
    if city_codes != list(CITY_CODES):
        fail(f"unexpected city codes/order: {city_codes}")

    snapshot = read_json(data_dir / "snapshot.json")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("cities"), dict):
        fail("snapshot.json has an invalid structure")
    generated_at = datetime.fromisoformat(str(snapshot.get("generated_at")))
    if generated_at.tzinfo is None:
        fail("generated_at must include a timezone")
    age_seconds = (datetime.now(timezone.utc) - generated_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -300 or age_seconds > 3600:
        fail(f"generated_at is not recent (age={age_seconds:.0f}s)")

    all_ids: set[int] = set()
    rated_ids: set[int] = set()
    summary: dict[str, dict[str, int]] = {}
    for city_code in CITY_CODES:
        rows = hotel_rows(root, city_code)
        if len(rows) < MINIMUM_COUNTS[city_code]:
            fail(f"{city_code} count is unexpectedly low: {len(rows)}")
        if args.previous_root:
            previous_count = len(hotel_rows(args.previous_root.resolve(), city_code))
            if len(rows) < previous_count * 0.9:
                fail(f"{city_code} shrank by more than 10%: {previous_count} -> {len(rows)}")

        ids = [int(item["id"]) for item in rows]
        if len(ids) != len(set(ids)):
            fail(f"{city_code} contains duplicate hotel IDs")
        overlap = all_ids.intersection(ids)
        if overlap:
            fail(f"hotel IDs occur in multiple cities: {sorted(overlap)[:5]}")
        all_ids.update(ids)
        city_rated_ids = {int(item["id"]) for item in rows if item.get("safety_score") is not None}
        rated_ids.update(city_rated_ids)
        statuses = {name: 0 for name in STATUS_NAMES}
        for item in rows:
            item_city = str(item.get("city_code"))
            if item_city != city_code:
                fail(f"hotel {item.get('id')} belongs to {item_city}, expected {city_code}")
            status = str(item.get("audit_status") or "pending")
            statuses[status if status in statuses else "pending"] += 1
        summary[city_code] = {"total": len(rows), "rated": len(city_rated_ids), **statuses}

    if snapshot["cities"] != summary:
        fail("snapshot summary does not match hotel files")

    detail_dir = data_dir / "details"
    if detail_dir.is_symlink():
        fail("details directory must not be a symlink")
    detail_paths = list(detail_dir.glob("*.json"))
    detail_ids = {int(path.stem) for path in detail_paths}
    if detail_ids != rated_ids:
        missing = sorted(rated_ids - detail_ids)[:5]
        extra = sorted(detail_ids - rated_ids)[:5]
        fail(f"detail IDs do not match rated hotels (missing={missing}, extra={extra})")
    for path in detail_paths:
        detail = read_json(path)
        if not isinstance(detail, dict) or not isinstance(detail.get("hotel"), dict):
            fail(f"invalid detail structure: {path.name}")
        if int(detail["hotel"].get("id", -1)) != int(path.stem):
            fail(f"detail ID mismatch: {path.name}")

    print(json.dumps({"cities": summary, "details": len(detail_paths), "generated_at": snapshot["generated_at"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

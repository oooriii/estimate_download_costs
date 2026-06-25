from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from watch.aggregator import WatchSnapshot
from watch.blocking import BlockRecommendation
from watch.country_blocks import CountryBlocksResolver
from watch.country_blocks_export import export_flagged_country_cidrs


def write_blocks_csv(path: Path, blocks: tuple[BlockRecommendation, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "block_type",
                "target",
                "country_code",
                "country_name",
                "requests",
                "rps",
                "reason",
                "detail",
            ]
        )
        for item in blocks:
            writer.writerow(
                [
                    item.block_type,
                    item.target,
                    item.country_code or "",
                    item.country_name or "",
                    item.requests,
                    f"{item.rps:.4f}",
                    item.reason,
                    item.detail,
                ]
            )


def write_snapshot_json(
    path: Path,
    snapshot: WatchSnapshot,
    blocks: tuple[BlockRecommendation, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "window_seconds": snapshot.window_seconds,
        "total_requests": snapshot.total_requests,
        "current_rps": snapshot.current_rps,
        "window_start": (
            snapshot.window_start.isoformat() if snapshot.window_start else None
        ),
        "window_end": snapshot.window_end.isoformat() if snapshot.window_end else None,
        "countries": [
            {
                "country_code": item.country_code,
                "country_name": item.country_name,
                "requests": item.requests,
                "rps": item.rps,
                "unique_ips": len(item.unique_ips),
            }
            for item in snapshot.countries
        ],
        "ips": [
            {
                "ip": item.key,
                "requests": item.requests,
                "rps": item.rps,
                "bursts": item.burst_count,
                "max_burst_rps": item.max_burst_rps,
            }
            for item in snapshot.ips
        ],
        "blocks": [
            {
                "block_type": item.block_type,
                "target": item.target,
                "country_code": item.country_code,
                "country_name": item.country_name,
                "requests": item.requests,
                "rps": item.rps,
                "reason": item.reason,
                "detail": item.detail,
            }
            for item in blocks
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _timestamp_slug(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return current.strftime("%Y%m%dT%H%M%S")


@dataclass
class SnapshotScheduler:
    directory: Path
    every_seconds: float
    country_blocks: CountryBlocksResolver | None = None
    export_country_cidrs: bool = True
    _last_saved_monotonic: float | None = None

    @property
    def enabled(self) -> bool:
        return self.every_seconds > 0

    def maybe_write(
        self,
        snapshot: WatchSnapshot,
        blocks: tuple[BlockRecommendation, ...],
        *,
        now: datetime | None = None,
    ) -> tuple[Path, Path] | None:
        if not self.enabled:
            return None

        monotonic_now = time.monotonic()
        if (
            self._last_saved_monotonic is not None
            and monotonic_now - self._last_saved_monotonic < self.every_seconds
        ):
            return None

        slug = _timestamp_slug(now)
        json_path = self.directory / f"{slug}.json"
        csv_path = self.directory / f"{slug}-blocks.csv"
        write_snapshot_json(json_path, snapshot, blocks)
        write_blocks_csv(csv_path, blocks)
        if (
            self.export_country_cidrs
            and self.country_blocks is not None
            and any(item.block_type == "country" for item in blocks)
        ):
            export_flagged_country_cidrs(self.directory, blocks, self.country_blocks)
        self._last_saved_monotonic = monotonic_now
        return json_path, csv_path

from __future__ import annotations

import csv
from pathlib import Path

from static_demand import StaticDemandResult, sort_paths_by_records
from static_paths import category_label, DSPACE_STATIC_PATH_VERSION


def write_static_demand_csv(
    path: Path,
    result: StaticDemandResult,
    *,
    limit: int | None = None,
) -> int:
    rows = result.paths if limit is None else result.paths[:limit]
    path.parent.mkdir(parents=True, exist_ok=True)

    stats = result.stats
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "path",
                "category",
                "extension",
                "records",
                "records_pct",
                "bytes",
                "bytes_pct",
                "bot_records",
                "human_records",
            ]
        )
        for rank, item in enumerate(rows, start=1):
            records_pct = (
                100.0 * item.records / stats.total_records
                if stats.total_records > 0
                else 0.0
            )
            bytes_pct = (
                100.0 * item.bytes / stats.total_bytes if stats.total_bytes > 0 else 0.0
            )
            writer.writerow(
                [
                    rank,
                    item.path,
                    category_label(item.category),
                    item.extension,
                    item.records,
                    f"{records_pct:.2f}",
                    item.bytes,
                    f"{bytes_pct:.2f}",
                    item.bot_records,
                    item.human_records,
                ]
            )

    return len(rows)


def write_static_daily_csv(path: Path, result: StaticDemandResult) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = result.stats

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["day", "records", "records_pct", "bytes", "bytes_pct"])
        for item in result.daily:
            writer.writerow(
                [
                    item.day.isoformat(),
                    item.records,
                    f"{100.0 * item.records / stats.total_records:.2f}"
                    if stats.total_records
                    else "0.00",
                    item.bytes,
                    f"{100.0 * item.bytes / stats.total_bytes:.2f}"
                    if stats.total_bytes
                    else "0.00",
                ]
            )

    return len(result.daily)


def write_static_summary_csv(path: Path, result: StaticDemandResult) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = result.stats
    projection = result.projection

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerow(["dspace_theme_path_rules", DSPACE_STATIC_PATH_VERSION])
        writer.writerow(["observed_days", f"{stats.observed_days:.2f}"])
        writer.writerow(["total_records", stats.total_records])
        writer.writerow(["total_bytes", stats.total_bytes])
        writer.writerow(["unique_paths", len(result.paths)])
        writer.writerow(["repeat_records", result.repeat_records])
        writer.writerow(["repeat_bytes", result.repeat_bytes])
        writer.writerow(
            ["avg_records_per_day", f"{stats.total_records / stats.observed_days:.2f}"]
        )
        writer.writerow(
            ["avg_bytes_per_day", f"{stats.total_bytes / stats.observed_days:.2f}"]
        )
        writer.writerow(
            ["projected_monthly_requests", f"{projection.monthly_requests:.2f}"]
        )
        writer.writerow(["projected_monthly_bytes", f"{projection.monthly_bytes:.2f}"])

        writer.writerow([])
        writer.writerow(["category", "unique_paths", "records", "bytes"])
        for item in result.categories:
            writer.writerow(
                [item.label, item.unique_paths, item.records, item.bytes]
            )

    return 2 + len(result.categories)

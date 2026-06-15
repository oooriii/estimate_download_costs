from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bots import BotCategory, classify_user_agent
from parser import TrafficStats, iter_log_lines
from projection import ProjectedTraffic, project_traffic
from static_paths import category_label, classify_static_path, file_extension


@dataclass(slots=True)
class _PathBucket:
    records: int = 0
    bytes: int = 0
    bot_records: int = 0
    human_records: int = 0
    category: str = "other"
    extension: str = ""


@dataclass(frozen=True)
class StaticPathDemand:
    path: str
    category: str
    extension: str
    records: int
    bytes: int
    bot_records: int
    human_records: int


@dataclass(frozen=True)
class CategoryTraffic:
    category: str
    label: str
    records: int
    bytes: int
    unique_paths: int


@dataclass(frozen=True)
class ExtensionTraffic:
    extension: str
    records: int
    bytes: int
    unique_paths: int


@dataclass(frozen=True)
class DailyTraffic:
    day: date
    records: int
    bytes: int


@dataclass(frozen=True)
class StaticDemandResult:
    stats: TrafficStats
    projection: ProjectedTraffic
    paths: tuple[StaticPathDemand, ...]
    categories: tuple[CategoryTraffic, ...]
    extensions: tuple[ExtensionTraffic, ...]
    daily: tuple[DailyTraffic, ...]
    repeat_records: int
    repeat_bytes: int


def _repeat_bytes(bucket: _PathBucket) -> int:
    if bucket.records <= 1:
        return 0
    return bucket.bytes - bucket.bytes // bucket.records


def parse_static_demand(
    file_path: Path,
    *,
    projection_mode: str = "simple",
    progress: object | None = None,
) -> StaticDemandResult:
    min_date = None
    max_date = None
    total_records = 0
    total_bytes = 0

    by_path: dict[str, _PathBucket] = {}
    by_day: dict[date, list[int]] = {}
    category_paths: dict[str, set[str]] = {key: set() for key in ("theme", "bitstream_image", "other")}
    extension_paths: dict[str, set[str]] = {}

    task_id = None
    if progress is not None:
        task_id = progress.add_task("Parsing static log...", total=None)

    for log_line in iter_log_lines(file_path):
        path, path_category = classify_static_path(log_line.path)
        ext = file_extension(path)

        total_records += 1
        total_bytes += log_line.bytes_sent

        if min_date is None or log_line.timestamp < min_date:
            min_date = log_line.timestamp
        if max_date is None or log_line.timestamp > max_date:
            max_date = log_line.timestamp

        day = log_line.timestamp.date()
        day_bucket = by_day.setdefault(day, [0, 0])
        day_bucket[0] += 1
        day_bucket[1] += log_line.bytes_sent

        bucket = by_path.get(path)
        if bucket is None:
            bucket = _PathBucket(category=path_category, extension=ext)
            by_path[path] = bucket
        bucket.records += 1
        bucket.bytes += log_line.bytes_sent
        bucket.category = path_category
        bucket.extension = ext

        bot_category: BotCategory = classify_user_agent(log_line.user_agent)
        if bot_category == "bot":
            bucket.bot_records += 1
        elif bot_category == "human":
            bucket.human_records += 1

        category_paths[bucket.category].add(path)
        extension_paths.setdefault(ext or "(none)", set()).add(path)

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=total_records)

    stats = TrafficStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )
    projection = project_traffic(stats, mode=projection_mode)

    paths = tuple(
        sorted(
            (
                StaticPathDemand(
                    path=path,
                    category=bucket.category,
                    extension=bucket.extension,
                    records=bucket.records,
                    bytes=bucket.bytes,
                    bot_records=bucket.bot_records,
                    human_records=bucket.human_records,
                )
                for path, bucket in by_path.items()
            ),
            key=lambda item: (-item.bytes, -item.records, item.path),
        )
    )

    category_totals: dict[str, list[int]] = {
        key: [0, 0] for key in ("theme", "bitstream_image", "other")
    }
    for item in paths:
        totals = category_totals[item.category]
        totals[0] += item.records
        totals[1] += item.bytes

    categories = tuple(
        CategoryTraffic(
            category=category,
            label=category_label(category),
            records=category_totals[category][0],
            bytes=category_totals[category][1],
            unique_paths=len(category_paths[category]),
        )
        for category in ("theme", "bitstream_image", "other")
        if category_totals[category][0] > 0
    )

    extension_totals: dict[str, list[int]] = {}
    for item in paths:
        key = item.extension or "(none)"
        totals = extension_totals.setdefault(key, [0, 0])
        totals[0] += item.records
        totals[1] += item.bytes

    extensions = tuple(
        ExtensionTraffic(
            extension=ext,
            records=totals[0],
            bytes=totals[1],
            unique_paths=len(extension_paths[ext]),
        )
        for ext, totals in sorted(
            extension_totals.items(),
            key=lambda pair: (-pair[1][1], -pair[1][0], pair[0]),
        )
    )

    daily = tuple(
        DailyTraffic(day=day, records=values[0], bytes=values[1])
        for day, values in sorted(by_day.items())
    )

    repeat_records = sum(max(bucket.records - 1, 0) for bucket in by_path.values())
    repeat_bytes = sum(_repeat_bytes(bucket) for bucket in by_path.values())

    return StaticDemandResult(
        stats=stats,
        projection=projection,
        paths=paths,
        categories=categories,
        extensions=extensions,
        daily=daily,
        repeat_records=repeat_records,
        repeat_bytes=repeat_bytes,
    )


def sort_paths_by_records(
    paths: tuple[StaticPathDemand, ...],
) -> tuple[StaticPathDemand, ...]:
    return tuple(sorted(paths, key=lambda item: (-item.records, -item.bytes, item.path)))

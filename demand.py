from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bitstream_paths import BitstreamRef, normalize_request_path, parse_bitstream_ref
from bots import BotCategory, classify_user_agent
from parser import TrafficStats, iter_log_lines


@dataclass(frozen=True)
class FileDemand:
    path: str
    item_id: str | None
    filename: str | None
    records: int
    bytes: int
    unique_ips: int
    bot_records: int
    human_records: int


@dataclass(frozen=True)
class FileDemandResult:
    stats: TrafficStats
    files: tuple[FileDemand, ...]
    bitstream_records: int
    other_records: int


def display_filename(item: FileDemand) -> str:
    if item.filename:
        return item.filename
    path = item.path.rstrip("/")
    if "/" in path:
        return path.rsplit("/", 1)[-1]
    return path or "—"


def _resolve_path(raw_path: str, *, bitstreams_only: bool) -> tuple[str, BitstreamRef | None]:
    bitstream = parse_bitstream_ref(raw_path)
    if bitstream is not None:
        return bitstream.canonical_path, bitstream
    if bitstreams_only:
        return "", None
    return normalize_request_path(raw_path), None


def parse_file_demand(
    file_path: Path,
    *,
    bitstreams_only: bool = True,
    progress: object | None = None,
) -> FileDemandResult:
    min_date = None
    max_date = None
    total_records = 0
    total_bytes = 0
    bitstream_records = 0
    other_records = 0

    by_path: dict[str, dict[str, object]] = {}

    task_id = None
    if progress is not None:
        task_id = progress.add_task("Parsing log...", total=None)

    for log_line in iter_log_lines(file_path):
        resolved_path, bitstream = _resolve_path(
            log_line.path,
            bitstreams_only=bitstreams_only,
        )
        if not resolved_path:
            continue

        total_records += 1
        total_bytes += log_line.bytes_sent
        if bitstream is not None:
            bitstream_records += 1
        else:
            other_records += 1

        if min_date is None or log_line.timestamp < min_date:
            min_date = log_line.timestamp
        if max_date is None or log_line.timestamp > max_date:
            max_date = log_line.timestamp

        bucket = by_path.setdefault(
            resolved_path,
            {
                "item_id": bitstream.item_id if bitstream else None,
                "filename": bitstream.filename if bitstream else None,
                "records": 0,
                "bytes": 0,
                "ips": set(),
                "bot_records": 0,
                "human_records": 0,
            },
        )
        if bitstream is not None:
            bucket["item_id"] = bitstream.item_id
            bucket["filename"] = bitstream.filename

        bucket["records"] = int(bucket["records"]) + 1
        bucket["bytes"] = int(bucket["bytes"]) + log_line.bytes_sent
        ips: set[str] = bucket["ips"]  # type: ignore[assignment]
        ips.add(log_line.remote_host)

        category: BotCategory = classify_user_agent(log_line.user_agent)
        if category == "bot":
            bucket["bot_records"] = int(bucket["bot_records"]) + 1
        elif category == "human":
            bucket["human_records"] = int(bucket["human_records"]) + 1

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=total_records)

    stats = TrafficStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )

    files = sort_file_demand(
        tuple(
            FileDemand(
                path=path,
                item_id=bucket["item_id"],  # type: ignore[arg-type]
                filename=bucket["filename"],  # type: ignore[arg-type]
                records=int(bucket["records"]),  # type: ignore[arg-type]
                bytes=int(bucket["bytes"]),  # type: ignore[arg-type]
                unique_ips=len(bucket["ips"]),  # type: ignore[arg-type]
                bot_records=int(bucket["bot_records"]),  # type: ignore[arg-type]
                human_records=int(bucket["human_records"]),  # type: ignore[arg-type]
            )
            for path, bucket in by_path.items()
        )
    )

    return FileDemandResult(
        stats=stats,
        files=files,
        bitstream_records=bitstream_records,
        other_records=other_records,
    )


def sort_file_demand(items: tuple[FileDemand, ...]) -> tuple[FileDemand, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (-item.bytes, -item.records, item.path),
        )
    )

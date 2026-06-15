from __future__ import annotations

import csv
from pathlib import Path

from abuse import IpTraffic, is_abusive, top_items


def filter_problematic_ips(
    ips: tuple[IpTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
    min_bytes_pct: float,
    limit: int | None = None,
) -> tuple[IpTraffic, ...]:
    abusive = tuple(
        ip
        for ip in ips
        if is_abusive(
            records=ip.records,
            bytes=ip.bytes,
            total_records=total_records,
            total_bytes=total_bytes,
            min_bytes_pct=min_bytes_pct,
        )
    )
    if abusive:
        rows = abusive
    else:
        rows = ips
    if limit is not None and limit > 0:
        rows = top_items(rows, limit=limit)
    return rows


def write_problematic_ips_csv(
    path: Path,
    ips: tuple[IpTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
    min_bytes_pct: float,
    limit: int | None = None,
) -> int:
    rows = filter_problematic_ips(
        ips,
        total_records=total_records,
        total_bytes=total_bytes,
        min_bytes_pct=min_bytes_pct,
        limit=limit,
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ip",
                "country_code",
                "country_name",
                "records",
                "records_pct",
                "bytes",
                "bytes_pct",
                "user_agent_count",
                "top_user_agent",
                "abusive",
            ]
        )
        for item in rows:
            records_pct = _pct(item.records, total_records)
            bytes_pct = _pct(item.bytes, total_bytes)
            writer.writerow(
                [
                    item.remote_host,
                    item.country_code or "",
                    item.country_name or "",
                    item.records,
                    f"{records_pct:.1f}",
                    item.bytes,
                    f"{bytes_pct:.1f}",
                    item.user_agent_count,
                    item.top_user_agent,
                    "yes"
                    if is_abusive(
                        records=item.records,
                        bytes=item.bytes,
                        total_records=total_records,
                        total_bytes=total_bytes,
                        min_bytes_pct=min_bytes_pct,
                    )
                    else "no",
                ]
            )

    return len(rows)


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * part / total

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from bots import BotCategory, classify_user_agent
from geo import CountryTraffic, GeoIpResolver, country_for_line, sort_countries
from parser import TrafficStats, iter_log_lines


@dataclass(frozen=True)
class BotTraffic:
    category: BotCategory
    records: int
    bytes: int


@dataclass(frozen=True)
class IpTraffic:
    remote_host: str
    country_code: str | None
    country_name: str | None
    records: int
    bytes: int
    user_agent_count: int
    top_user_agent: str


@dataclass(frozen=True)
class UserAgentTraffic:
    user_agent: str
    records: int
    bytes: int
    ip_count: int


@dataclass(frozen=True)
class AnalysisResult:
    stats: TrafficStats
    countries: tuple[CountryTraffic, ...] | None
    bot_traffic: tuple[BotTraffic, ...]
    ips: tuple[IpTraffic, ...]
    user_agents: tuple[UserAgentTraffic, ...]


def parse_log(
    file_path: Path,
    *,
    geo_resolver: GeoIpResolver | None = None,
    progress: object | None = None,
) -> AnalysisResult:
    min_date = None
    max_date = None
    total_records = 0
    total_bytes = 0

    by_country: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    by_bot: dict[BotCategory, list[int]] = defaultdict(lambda: [0, 0])
    by_ip: dict[str, dict[str, object]] = {}
    by_user_agent: dict[str, dict[str, object]] = {}

    task_id = None
    if progress is not None:
        task_id = progress.add_task("Parsing log...", total=None)

    for log_line in iter_log_lines(file_path):
        total_records += 1
        total_bytes += log_line.bytes_sent

        if min_date is None or log_line.timestamp < min_date:
            min_date = log_line.timestamp
        if max_date is None or log_line.timestamp > max_date:
            max_date = log_line.timestamp

        if geo_resolver is not None:
            country_code, country_name = country_for_line(log_line, geo_resolver)
            bucket = by_country[(country_code, country_name)]
            bucket[0] += 1
            bucket[1] += log_line.bytes_sent
        else:
            country_code = None
            country_name = None

        bot_category = classify_user_agent(log_line.user_agent)
        bot_bucket = by_bot[bot_category]
        bot_bucket[0] += 1
        bot_bucket[1] += log_line.bytes_sent

        ip_bucket = by_ip.setdefault(
            log_line.remote_host,
            {
                "records": 0,
                "bytes": 0,
                "country_code": country_code,
                "country_name": country_name,
                "user_agents": Counter(),
            },
        )
        ip_bucket["records"] = int(ip_bucket["records"]) + 1
        ip_bucket["bytes"] = int(ip_bucket["bytes"]) + log_line.bytes_sent
        user_agents: Counter[str] = ip_bucket["user_agents"]  # type: ignore[assignment]
        user_agents[log_line.user_agent] += 1
        if country_code is not None:
            ip_bucket["country_code"] = country_code
            ip_bucket["country_name"] = country_name

        ua_bucket = by_user_agent.setdefault(
            log_line.user_agent,
            {
                "records": 0,
                "bytes": 0,
                "ips": set(),
            },
        )
        ua_bucket["records"] = int(ua_bucket["records"]) + 1
        ua_bucket["bytes"] = int(ua_bucket["bytes"]) + log_line.bytes_sent
        ips: set[str] = ua_bucket["ips"]  # type: ignore[assignment]
        ips.add(log_line.remote_host)

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=total_records)

    stats = TrafficStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )

    countries = None
    if geo_resolver is not None:
        countries = sort_countries(
            tuple(
                CountryTraffic(
                    country_code=code,
                    country_name=name,
                    records=values[0],
                    bytes=values[1],
                )
                for (code, name), values in by_country.items()
            )
        )

    bot_traffic = sort_bot_traffic(
        tuple(
            BotTraffic(
                category=category,
                records=by_bot.get(category, [0, 0])[0],
                bytes=by_bot.get(category, [0, 0])[1],
            )
            for category in ("bot", "human", "unknown")
        )
    )

    ips = sort_ip_traffic(
        tuple(
            IpTraffic(
                remote_host=remote_host,
                country_code=bucket["country_code"],  # type: ignore[arg-type]
                country_name=bucket["country_name"],  # type: ignore[arg-type]
                records=int(bucket["records"]),  # type: ignore[arg-type]
                bytes=int(bucket["bytes"]),  # type: ignore[arg-type]
                user_agent_count=len(bucket["user_agents"]),  # type: ignore[arg-type]
                top_user_agent=bucket["user_agents"].most_common(1)[0][0],  # type: ignore[index]
            )
            for remote_host, bucket in by_ip.items()
        )
    )

    user_agents = sort_user_agent_traffic(
        tuple(
            UserAgentTraffic(
                user_agent=user_agent,
                records=int(bucket["records"]),  # type: ignore[arg-type]
                bytes=int(bucket["bytes"]),  # type: ignore[arg-type]
                ip_count=len(bucket["ips"]),  # type: ignore[arg-type]
            )
            for user_agent, bucket in by_user_agent.items()
        )
    )

    return AnalysisResult(
        stats=stats,
        countries=countries,
        bot_traffic=bot_traffic,
        ips=ips,
        user_agents=user_agents,
    )


def sort_bot_traffic(items: tuple[BotTraffic, ...]) -> tuple[BotTraffic, ...]:
    order = {"bot": 0, "human": 1, "unknown": 2}
    return tuple(sorted(items, key=lambda item: (order[item.category], -item.bytes)))


def sort_ip_traffic(items: tuple[IpTraffic, ...]) -> tuple[IpTraffic, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (-item.bytes, -item.records, item.remote_host),
        )
    )


def sort_user_agent_traffic(
    items: tuple[UserAgentTraffic, ...],
) -> tuple[UserAgentTraffic, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (-item.bytes, -item.records, item.user_agent),
        )
    )


def top_items[T](items: tuple[T, ...], *, limit: int) -> tuple[T, ...]:
    if limit <= 0:
        return items
    return items[:limit]


def is_abusive(
    *,
    records: int,
    bytes: int,
    total_records: int,
    total_bytes: int,
    min_bytes_pct: float,
) -> bool:
    if total_records <= 0 and total_bytes <= 0:
        return False
    records_pct = 100.0 * records / total_records if total_records > 0 else 0.0
    bytes_pct = 100.0 * bytes / total_bytes if total_bytes > 0 else 0.0
    return bytes_pct >= min_bytes_pct or records_pct >= min_bytes_pct

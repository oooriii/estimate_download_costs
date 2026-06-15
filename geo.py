from __future__ import annotations

import ipaddress
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from parser import LogLine, TrafficStats, iter_log_lines

UNKNOWN_COUNTRY_CODE = "??"
UNKNOWN_COUNTRY_NAME = "Unknown"
LOCAL_COUNTRY_CODE = "LOCAL"
LOCAL_COUNTRY_NAME = "Local / private"


@dataclass(frozen=True)
class CountryTraffic:
    country_code: str
    country_name: str
    records: int
    bytes: int


class GeoIpResolver(Protocol):
    def lookup(self, remote_host: str) -> tuple[str, str]:
        """Return ISO country code and display name for a log remote host."""


@dataclass(frozen=True)
class StaticGeoIpResolver:
    """In-memory resolver for tests and small fixtures."""

    mapping: dict[str, tuple[str, str]]

    def lookup(self, remote_host: str) -> tuple[str, str]:
        return self.mapping.get(
            remote_host,
            (UNKNOWN_COUNTRY_CODE, UNKNOWN_COUNTRY_NAME),
        )


@dataclass
class MaxMindGeoIpResolver:
    database_path: Path
    _reader: object | None = None

    def __post_init__(self) -> None:
        if not self.database_path.is_file():
            raise FileNotFoundError(
                f"GeoIP database '{self.database_path}' does not exist."
            )

    def _get_reader(self):
        if self._reader is None:
            try:
                import geoip2.database
            except ImportError as exc:
                raise RuntimeError(
                    "geoip2 is required for country lookup. Install with: uv add geoip2"
                ) from exc
            self._reader = geoip2.database.Reader(str(self.database_path))
        return self._reader

    def lookup(self, remote_host: str) -> tuple[str, str]:
        normalized = classify_remote_host(remote_host)
        if normalized is not None:
            return normalized

        reader = self._get_reader()
        try:
            response = reader.country(remote_host)
        except Exception:
            return UNKNOWN_COUNTRY_CODE, UNKNOWN_COUNTRY_NAME

        code = response.country.iso_code or UNKNOWN_COUNTRY_CODE
        name = response.country.name or UNKNOWN_COUNTRY_NAME
        return code, name

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None


def classify_remote_host(remote_host: str) -> tuple[str, str] | None:
    if remote_host == "-":
        return UNKNOWN_COUNTRY_CODE, UNKNOWN_COUNTRY_NAME
    try:
        address = ipaddress.ip_address(remote_host)
    except ValueError:
        return UNKNOWN_COUNTRY_CODE, UNKNOWN_COUNTRY_NAME
    if address.is_private or address.is_loopback or address.is_link_local:
        return LOCAL_COUNTRY_CODE, LOCAL_COUNTRY_NAME
    return None


def open_geoip_resolver(database_path: Path) -> MaxMindGeoIpResolver:
    return MaxMindGeoIpResolver(database_path=database_path)


def parse_with_countries(
    file_path: Path,
    geo_resolver: GeoIpResolver,
    *,
    progress: object | None = None,
) -> tuple[TrafficStats, tuple[CountryTraffic, ...]]:
    min_date = None
    max_date = None
    total_records = 0
    total_bytes = 0
    by_country: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])

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

        country_code, country_name = country_for_line(log_line, geo_resolver)
        bucket = by_country[(country_code, country_name)]
        bucket[0] += 1
        bucket[1] += log_line.bytes_sent

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=total_records)

    countries = tuple(
        CountryTraffic(
            country_code=code,
            country_name=name,
            records=values[0],
            bytes=values[1],
        )
        for (code, name), values in by_country.items()
    )
    countries = sort_countries(countries)

    stats = TrafficStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )
    return stats, countries


def country_for_line(
    log_line: LogLine,
    geo_resolver: GeoIpResolver,
) -> tuple[str, str]:
    normalized = classify_remote_host(log_line.remote_host)
    if normalized is not None:
        return normalized
    return geo_resolver.lookup(log_line.remote_host)


def sort_countries(countries: tuple[CountryTraffic, ...]) -> tuple[CountryTraffic, ...]:
    return tuple(
        sorted(
            countries,
            key=lambda item: (-item.bytes, -item.records, item.country_code),
        )
    )


def top_countries(
    countries: tuple[CountryTraffic, ...],
    *,
    limit: int = 15,
) -> tuple[CountryTraffic, ...]:
    if limit <= 0 or len(countries) <= limit:
        return countries

    top = countries[:limit]
    remainder = countries[limit:]
    return top + (
        CountryTraffic(
            country_code="OTHER",
            country_name=f"Other ({len(remainder)} countries)",
            records=sum(item.records for item in remainder),
            bytes=sum(item.bytes for item in remainder),
        ),
    )

from __future__ import annotations

import csv
import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CountryBlocksPaths:
    locations: Path
    blocks_ipv4: Path | None = None
    blocks_ipv6: Path | None = None


@dataclass(frozen=True)
class CountryBlocksSummary:
    country_code: str
    country_name: str
    total_cidrs: int
    sample_cidrs: tuple[str, ...]


def resolve_country_blocks_paths(
    *,
    geoip_db: Path | None,
    locations: str | None = None,
    blocks_ipv4: str | None = None,
    blocks_ipv6: str | None = None,
) -> CountryBlocksPaths | None:
    if locations:
        return CountryBlocksPaths(
            locations=Path(locations),
            blocks_ipv4=Path(blocks_ipv4) if blocks_ipv4 else None,
            blocks_ipv6=Path(blocks_ipv6) if blocks_ipv6 else None,
        )
    if geoip_db is not None:
        return discover_country_blocks_paths(geoip_db)
    return None


def discover_country_blocks_paths(geoip_db: Path) -> CountryBlocksPaths | None:
    """Infer GeoLite2 Country CSV paths from a .mmdb file location."""
    directory = geoip_db.parent
    locations = directory / "GeoLite2-Country-Locations-en.csv"
    blocks_ipv4 = directory / "GeoLite2-Country-Blocks-IPv4.csv"
    blocks_ipv6 = directory / "GeoLite2-Country-Blocks-IPv6.csv"

    if not locations.is_file():
        return None

    return CountryBlocksPaths(
        locations=locations,
        blocks_ipv4=blocks_ipv4 if blocks_ipv4.is_file() else None,
        blocks_ipv6=blocks_ipv6 if blocks_ipv6.is_file() else None,
    )


def open_country_blocks_resolver(
    *,
    geoip_db: Path | None,
    locations: str | None = None,
    blocks_ipv4: str | None = None,
    blocks_ipv6: str | None = None,
) -> CountryBlocksResolver | None:
    paths = resolve_country_blocks_paths(
        geoip_db=geoip_db,
        locations=locations,
        blocks_ipv4=blocks_ipv4,
        blocks_ipv6=blocks_ipv6,
    )
    if paths is None:
        return None
    if paths.blocks_ipv4 is None and paths.blocks_ipv6 is None:
        return None
    return CountryBlocksResolver.from_paths(paths)


def _network_sort_key(cidr: str) -> tuple[int, int, int]:
    network = ipaddress.ip_network(cidr, strict=False)
    return (network.prefixlen, network.version, int(network.network_address))


class CountryBlocksResolver:
    """Lookup official MaxMind CIDR ranges per country ISO code."""

    def __init__(
        self,
        *,
        locations_path: Path,
        blocks_ipv4_path: Path | None = None,
        blocks_ipv6_path: Path | None = None,
    ) -> None:
        if not locations_path.is_file():
            raise FileNotFoundError(
                f"Country locations file '{locations_path}' does not exist."
            )
        self._locations_path = locations_path
        self._blocks_ipv4_path = blocks_ipv4_path
        self._blocks_ipv6_path = blocks_ipv6_path
        self._country_names: dict[str, str] = {}
        self._geoname_to_code: dict[str, str] = {}
        self._blocks_by_country: dict[str, list[str]] | None = None

    @classmethod
    def from_paths(cls, paths: CountryBlocksPaths) -> CountryBlocksResolver:
        return cls(
            locations_path=paths.locations,
            blocks_ipv4_path=paths.blocks_ipv4,
            blocks_ipv6_path=paths.blocks_ipv6,
        )

    def _ensure_loaded(self) -> None:
        if self._blocks_by_country is not None:
            return

        self._load_locations()
        blocks_by_country: dict[str, list[str]] = {}
        if self._blocks_ipv4_path is not None:
            self._load_blocks_file(self._blocks_ipv4_path, blocks_by_country)
        if self._blocks_ipv6_path is not None:
            self._load_blocks_file(self._blocks_ipv6_path, blocks_by_country)

        for country_code, cidrs in blocks_by_country.items():
            cidrs.sort(key=_network_sort_key)

        self._blocks_by_country = blocks_by_country

    def _load_locations(self) -> None:
        with self._locations_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                geoname_id = (row.get("geoname_id") or "").strip()
                country_code = (row.get("country_iso_code") or "").strip().upper()
                country_name = (row.get("country_name") or "").strip()
                if not geoname_id or not country_code:
                    continue
                self._geoname_to_code[geoname_id] = country_code
                self._country_names[country_code] = country_name

    def _country_code_for_row(self, row: dict[str, str]) -> str | None:
        for key in (
            "geoname_id",
            "represented_country_geoname_id",
            "registered_country_geoname_id",
        ):
            geoname_id = (row.get(key) or "").strip()
            if not geoname_id:
                continue
            country_code = self._geoname_to_code.get(geoname_id)
            if country_code:
                return country_code
        return None

    def _load_blocks_file(
        self,
        path: Path,
        blocks_by_country: dict[str, list[str]],
    ) -> None:
        if not path.is_file():
            return

        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                network = (row.get("network") or "").strip()
                country_code = self._country_code_for_row(row)
                if not network or not country_code:
                    continue
                blocks_by_country.setdefault(country_code, []).append(network)

    def country_name(self, country_code: str) -> str:
        self._ensure_loaded()
        return self._country_names.get(country_code, country_code)

    def blocks_for_country(self, country_code: str) -> tuple[str, ...]:
        self._ensure_loaded()
        assert self._blocks_by_country is not None
        return tuple(self._blocks_by_country.get(country_code.upper(), ()))

    def summary(
        self,
        country_code: str,
        *,
        limit: int = 5,
    ) -> CountryBlocksSummary | None:
        cidrs = self.blocks_for_country(country_code)
        if not cidrs:
            return None
        return CountryBlocksSummary(
            country_code=country_code.upper(),
            country_name=self.country_name(country_code),
            total_cidrs=len(cidrs),
            sample_cidrs=cidrs[: max(limit, 0)],
        )

    def format_summary_detail(self, country_code: str, *, limit: int = 5) -> str:
        summary = self.summary(country_code, limit=limit)
        if summary is None:
            return "no official CIDR data"
        sample = ", ".join(summary.sample_cidrs) if summary.sample_cidrs else "—"
        return (
            f"official CIDRs: {summary.total_cidrs:,} "
            f"(largest: {sample})"
        )

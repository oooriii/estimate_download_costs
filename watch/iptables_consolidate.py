from __future__ import annotations

import csv
import ipaddress
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from geo import GeoIpResolver, classify_remote_host
from watch.subnet import collapse_host_ips, collapse_subnets


@dataclass(frozen=True)
class ConsolidatedRange:
    country_code: str
    country_name: str
    cidr: str
    ips_covered: int


@dataclass(frozen=True)
class ConsolidationResult:
    input_ips: int
    unique_ips: int
    output_ranges: int
    ranges: tuple[ConsolidatedRange, ...]


def _parse_ip_list(path: Path) -> list[str]:
    ips: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            token = raw.split()[0].rstrip(",;")
            if token in seen:
                continue
            try:
                ipaddress.ip_address(token)
            except ValueError:
                continue
            seen.add(token)
            ips.append(token)
    return ips


def _country_for_ip(ip: str, geo_resolver: GeoIpResolver | None) -> tuple[str, str]:
    if geo_resolver is not None:
        return geo_resolver.lookup(ip)
    normalized = classify_remote_host(ip)
    if normalized is not None:
        return normalized
    return "??", "Unknown"


def _count_ips_in_network(
    sorted_ip_ints: list[int],
    network: ipaddress._BaseNetwork,
) -> int:
    lo = bisect_left(sorted_ip_ints, int(network.network_address))
    hi = bisect_right(sorted_ip_ints, int(network.broadcast_address))
    return hi - lo


def consolidate_ips(
    ips: list[str],
    *,
    geo_resolver: GeoIpResolver | None = None,
    group_by_country: bool = True,
) -> ConsolidationResult:
    unique_ips = sorted(set(ips), key=lambda ip: ipaddress.ip_address(ip))
    if not unique_ips:
        return ConsolidationResult(
            input_ips=len(ips),
            unique_ips=0,
            output_ranges=0,
            ranges=(),
        )

    if group_by_country:
        by_country: dict[tuple[str, str], list[str]] = {}
        for ip in unique_ips:
            code, name = _country_for_ip(ip, geo_resolver)
            by_country.setdefault((code, name), []).append(ip)

        ranges: list[ConsolidatedRange] = []
        for (code, name), country_ips in sorted(by_country.items()):
            cidrs = collapse_host_ips(country_ips)
            country_ip_ints = sorted(
                int(ipaddress.ip_address(ip)) for ip in country_ips
            )
            for cidr in cidrs:
                network = ipaddress.ip_network(cidr, strict=False)
                covered = _count_ips_in_network(country_ip_ints, network)
                ranges.append(
                    ConsolidatedRange(
                        country_code=code,
                        country_name=name,
                        cidr=cidr,
                        ips_covered=covered,
                    )
                )
    else:
        cidrs = collapse_host_ips(unique_ips)
        unique_ip_ints = sorted(int(ipaddress.ip_address(ip)) for ip in unique_ips)
        ranges = []
        for cidr in cidrs:
            network = ipaddress.ip_network(cidr, strict=False)
            covered = _count_ips_in_network(unique_ip_ints, network)
            ranges.append(
                ConsolidatedRange(
                    country_code="*",
                    country_name="All",
                    cidr=cidr,
                    ips_covered=covered,
                )
            )

    return ConsolidationResult(
        input_ips=len(ips),
        unique_ips=len(unique_ips),
        output_ranges=len(ranges),
        ranges=tuple(ranges),
    )


def consolidate_ip_file(
    path: Path,
    *,
    geo_resolver: GeoIpResolver | None = None,
    group_by_country: bool = True,
) -> ConsolidationResult:
    return consolidate_ips(
        _parse_ip_list(path),
        geo_resolver=geo_resolver,
        group_by_country=group_by_country,
    )


def write_consolidation_csv(path: Path, result: ConsolidationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["country_code", "country_name", "cidr", "ips_covered"])
        for item in result.ranges:
            writer.writerow(
                [item.country_code, item.country_name, item.cidr, item.ips_covered]
            )


def write_ipset_script(path: Path, result: ConsolidationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/bin/bash",
        "# Consolidated iptables/ipset ranges",
        f"# {result.unique_ips} unique IPs -> {result.output_ranges} CIDR ranges",
        "set -euo pipefail",
        "IPSET_NAME=${IPSET_NAME:-blocked_abuse}",
        (
            "ipset create \"$IPSET_NAME\" hash:net family inet "
            "hashsize 4096 maxelem 65536 -exist"
        ),
    ]
    for item in result.ranges:
        if item.country_code in ("*", "??"):
            continue
        lines.append(f"ipset add \"$IPSET_NAME\" {item.cidr} -exist")
    lines.append('iptables -I INPUT -m set --match-set "$IPSET_NAME" src -j DROP')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

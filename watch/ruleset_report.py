from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from geo import GeoIpResolver
from watch.iptables_consolidate import (
    ConsolidationResult,
    _country_for_ip,
    consolidate_ips,
)
from watch.nftables_ruleset import NftRuleset, all_ips_from_ruleset, parse_nftables_ruleset


@dataclass(frozen=True)
class CountrySummary:
    country_code: str
    country_name: str
    ip_count: int
    pct_of_total: float


@dataclass(frozen=True)
class SetSummary:
    name: str
    entry_count: int
    unique_ips: int
    unique_cidrs: int
    referenced: bool
    consolidated_ranges: int
    consolidation_reduction_pct: float


@dataclass(frozen=True)
class RulesetReport:
    source_path: Path
    generated_at: str
    file_size_bytes: int
    total_entries: int
    total_unique_ips: int
    empty_sets: tuple[str, ...]
    active_sets: tuple[str, ...]
    referenced_sets: tuple[str, ...]
    set_summaries: tuple[SetSummary, ...]
    countries: tuple[CountrySummary, ...]
    consolidation: ConsolidationResult
    performance_assessment: str
    input_chain_rules: tuple[str, ...]


def _performance_assessment(
    *,
    unique_ips: int,
    output_ranges: int,
    active_set_count: int,
    referenced_drop_rules: int,
) -> str:
    lines = []
    if unique_ips >= 10_000:
        lines.append(
            f"High load: {unique_ips:,} individual IPv4 entries across nftables sets. "
            "Each packet matching the input chain may perform multiple set lookups."
        )
    elif unique_ips >= 1_000:
        lines.append(
            f"Moderate load: {unique_ips:,} IPv4 entries. "
            "Consolidation into CIDR ranges is recommended."
        )
    else:
        lines.append(f"Low load: {unique_ips:,} unique IPv4 entries.")

    if output_ranges > 0 and unique_ips > 0:
        reduction = 100.0 * (1 - output_ranges / unique_ips)
        lines.append(
            f"Consolidation could replace {unique_ips:,} host entries with "
            f"{output_ranges:,} CIDR ranges ({reduction:.1f}% fewer elements)."
        )

    if active_set_count > 3:
        lines.append(
            f"{active_set_count} non-empty sets with {referenced_drop_rules} "
            "separate drop rules in the input chain; consider merging into one set."
        )

    empty = active_set_count == 0 and unique_ips > 0
    if not empty and active_set_count < referenced_drop_rules:
        lines.append(
            "Some drop rules reference empty sets; they add lookup cost without effect."
        )

    return " ".join(lines)


def analyze_ruleset(
    path: Path,
    *,
    geo_resolver: GeoIpResolver | None = None,
    group_by_country: bool = True,
) -> RulesetReport:
    ruleset = parse_nftables_ruleset(path)
    all_ips = all_ips_from_ruleset(ruleset)
    unique_ips = sorted(set(all_ips))

    country_counts: Counter[tuple[str, str]] = Counter()
    for ip in unique_ips:
        code, name = _country_for_ip(ip, geo_resolver)
        country_counts[(code, name)] += 1

    total_unique = len(unique_ips)
    countries = tuple(
        CountrySummary(
            country_code=code,
            country_name=name,
            ip_count=count,
            pct_of_total=100.0 * count / total_unique if total_unique else 0.0,
        )
        for (code, name), count in country_counts.most_common()
    )

    consolidation = consolidate_ips(
        all_ips,
        geo_resolver=geo_resolver,
        group_by_country=group_by_country,
    )

    set_summaries: list[SetSummary] = []
    active_sets: list[str] = []
    empty_sets: list[str] = []

    for nft_set in ruleset.sets:
        unique_set_ips = len(set(nft_set.ips))
        if unique_set_ips == 0 and not nft_set.cidrs:
            empty_sets.append(nft_set.name)
            per_set_ranges = 0
            reduction = 0.0
        else:
            active_sets.append(nft_set.name)
            per_set = consolidate_ips(
                list(nft_set.ips),
                geo_resolver=geo_resolver,
                group_by_country=False,
            )
            per_set_ranges = per_set.output_ranges
            reduction = (
                100.0 * (1 - per_set_ranges / per_set.unique_ips)
                if per_set.unique_ips
                else 0.0
            )

        set_summaries.append(
            SetSummary(
                name=nft_set.name,
                entry_count=len(nft_set.ips),
                unique_ips=unique_set_ips,
                unique_cidrs=len(nft_set.cidrs),
                referenced=nft_set.name in ruleset.referenced_sets,
                consolidated_ranges=per_set_ranges,
                consolidation_reduction_pct=reduction,
            )
        )

    input_rules: tuple[str, ...] = ()
    for chain in ruleset.chains:
        if chain.name == "input":
            input_rules = chain.rules
            break

    referenced_drop_rules = sum(
        1 for rule in input_rules if " drop" in rule and "@" in rule
    )

    return RulesetReport(
        source_path=path,
        generated_at=datetime.now().isoformat(),
        file_size_bytes=path.stat().st_size,
        total_entries=len(all_ips),
        total_unique_ips=total_unique,
        empty_sets=tuple(empty_sets),
        active_sets=tuple(active_sets),
        referenced_sets=ruleset.referenced_sets,
        set_summaries=tuple(set_summaries),
        countries=countries,
        consolidation=consolidation,
        performance_assessment=_performance_assessment(
            unique_ips=total_unique,
            output_ranges=consolidation.output_ranges,
            active_set_count=len(active_sets),
            referenced_drop_rules=referenced_drop_rules,
        ),
        input_chain_rules=input_rules,
    )


def write_ruleset_report_json(path: Path, report: RulesetReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": report.generated_at,
        "source_path": str(report.source_path),
        "file_size_bytes": report.file_size_bytes,
        "total_entries": report.total_entries,
        "total_unique_ips": report.total_unique_ips,
        "empty_sets": list(report.empty_sets),
        "active_sets": list(report.active_sets),
        "referenced_sets": list(report.referenced_sets),
        "performance_assessment": report.performance_assessment,
        "input_chain_rules": list(report.input_chain_rules),
        "sets": [
            {
                "name": item.name,
                "entry_count": item.entry_count,
                "unique_ips": item.unique_ips,
                "referenced": item.referenced,
                "consolidated_ranges": item.consolidated_ranges,
                "consolidation_reduction_pct": item.consolidation_reduction_pct,
            }
            for item in report.set_summaries
        ],
        "countries": [
            {
                "country_code": item.country_code,
                "country_name": item.country_name,
                "ip_count": item.ip_count,
                "pct_of_total": item.pct_of_total,
            }
            for item in report.countries
        ],
        "consolidation": {
            "unique_ips": report.consolidation.unique_ips,
            "output_ranges": report.consolidation.output_ranges,
            "ranges": [
                {
                    "country_code": item.country_code,
                    "country_name": item.country_name,
                    "cidr": item.cidr,
                    "ips_covered": item.ips_covered,
                }
                for item in report.consolidation.ranges
            ],
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_ruleset_countries_csv(path: Path, report: RulesetReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["country_code", "country_name", "ip_count", "pct_of_total"])
        for item in report.countries:
            writer.writerow(
                [
                    item.country_code,
                    item.country_name,
                    item.ip_count,
                    f"{item.pct_of_total:.2f}",
                ]
            )


def write_simplified_nftables(
    path: Path,
    report: RulesetReport,
    *,
    set_name: str = "blocked_consolidated",
) -> None:
    """Write a simplified nftables snippet using consolidated CIDR ranges."""
    ranges = report.consolidation.ranges
    if len(ranges) <= 80:
        cidr_blob = ", ".join(item.cidr for item in ranges)
        elements_line = f"\t\telements = {{ {cidr_blob} }}"
    else:
        chunks = [ranges[i : i + 40] for i in range(0, len(ranges), 40)]
        parts = []
        for index, chunk in enumerate(chunks):
            blob = ", ".join(item.cidr for item in chunk)
            if index == 0:
                parts.append(f"\t\telements = {{ {blob},")
            elif index == len(chunks) - 1:
                parts.append(f"\t\t  {blob} }}")
            else:
                parts.append(f"\t\t  {blob},")
        elements_line = "\n".join(parts)

    lines = [
        "# Simplified nftables snippet generated from ruleset analysis",
        f"# {report.consolidation.unique_ips:,} IPs -> "
        f"{report.consolidation.output_ranges:,} CIDR ranges",
        "# Review before applying. Requires 'flags interval' for CIDR ranges.",
        "table inet filter {",
        f"\tset {set_name} {{",
        "\t\ttype ipv4_addr",
        "\t\tflags interval",
        elements_line,
        "\t}",
        "\tchain input {",
        "\t\ttype filter hook input priority 0; policy accept;",
        "\t\tiif lo accept",
        "\t\tct state established,related accept",
        f"\t\tip saddr @{set_name} drop",
        "\t}",
        "}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

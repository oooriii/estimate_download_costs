from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from watch.aggregator import WatchSnapshot
from watch.config import WatchThresholds
from watch.country_blocks import CountryBlocksResolver
from watch.subnet import collapse_subnets

BlockType = Literal["country", "subnet", "ip", "country_cidr"]


@dataclass(frozen=True)
class BlockRecommendation:
    block_type: BlockType
    target: str
    country_code: str | None
    country_name: str | None
    requests: int
    rps: float
    reason: str
    detail: str


def _is_abusive_ip(
    stats_rps: float,
    stats_requests: int,
    thresholds: WatchThresholds,
    *,
    max_burst_rps: float = 0.0,
    max_burst_requests: int = 0,
) -> bool:
    burst_abuse = (
        max_burst_rps >= thresholds.min_burst_rps
        and max_burst_requests >= thresholds.min_burst_requests
    )
    sustained_abuse = (
        stats_rps >= thresholds.min_rps_per_ip
        and stats_requests >= thresholds.min_requests_per_ip
    )
    return burst_abuse or sustained_abuse


def _is_abusive_subnet(
    stats_rps: float,
    stats_requests: int,
    thresholds: WatchThresholds,
    *,
    max_burst_rps: float = 0.0,
    max_burst_requests: int = 0,
) -> bool:
    burst_abuse = (
        max_burst_rps >= thresholds.min_burst_rps
        and max_burst_requests >= thresholds.min_burst_requests
    )
    sustained_abuse = (
        stats_rps >= thresholds.min_rps_per_subnet
        and stats_requests >= thresholds.min_requests_per_subnet
    )
    return burst_abuse or sustained_abuse


def _is_abusive_country(
    stats_rps: float,
    stats_requests: int,
    thresholds: WatchThresholds,
) -> bool:
    return (
        stats_rps >= thresholds.min_rps_per_country
        and stats_requests >= thresholds.min_requests_per_country
    )


def recommend_blocks(
    snapshot: WatchSnapshot,
    *,
    thresholds: WatchThresholds,
    country_blocks: CountryBlocksResolver | None = None,
    official_cidr_limit: int = 5,
) -> tuple[BlockRecommendation, ...]:
    recommendations: list[BlockRecommendation] = []

    for country in snapshot.countries:
        if country.country_code in ("LOCAL", "??", "OTHER"):
            continue
        if not _is_abusive_country(country.rps, country.requests, thresholds):
            continue

        top_subnets = [
            cidr
            for cidr, count in country.subnets.most_common()
            if count >= max(thresholds.min_requests_per_subnet // 5, 10)
        ]
        collapsed = collapse_subnets(top_subnets[:20])
        cidr_detail = ", ".join(collapsed[:10]) if collapsed else "—"
        official_detail = ""
        if country_blocks is not None:
            official_detail = country_blocks.format_summary_detail(
                country.country_code,
                limit=official_cidr_limit,
            )

        recommendations.append(
            BlockRecommendation(
                block_type="country",
                target=country.country_code,
                country_code=country.country_code,
                country_name=country.country_name,
                requests=country.requests,
                rps=country.rps,
                reason="high_country_rps",
                detail=(
                    f"{len(country.unique_ips)} unique IPs; "
                    f"observed subnets: {cidr_detail}"
                    + (f"; {official_detail}" if official_detail else "")
                ),
            )
        )

        if country_blocks is not None:
            summary = country_blocks.summary(
                country.country_code,
                limit=official_cidr_limit,
            )
            if summary is not None:
                for cidr in summary.sample_cidrs:
                    recommendations.append(
                        BlockRecommendation(
                            block_type="country_cidr",
                            target=cidr,
                            country_code=country.country_code,
                            country_name=country.country_name,
                            requests=country.requests,
                            rps=country.rps,
                            reason="official_country_cidr",
                            detail=(
                                f"Official GeoLite2 range for {summary.country_name} "
                                f"({summary.total_cidrs:,} total)"
                            ),
                        )
                    )

        for cidr in collapsed[:5]:
            count = country.subnets.get(cidr, 0)
            if count == 0:
                # collapsed block may cover multiple observed subnets
                count = sum(
                    requests
                    for subnet, requests in country.subnets.items()
                    if subnet in collapsed
                )
            recommendations.append(
                BlockRecommendation(
                    block_type="subnet",
                    target=cidr,
                    country_code=country.country_code,
                    country_name=country.country_name,
                    requests=count,
                    rps=country.rps,
                    reason="country_subnet_cluster",
                    detail=f"Part of abusive traffic from {country.country_name}",
                )
            )

    seen_ips: set[str] = set()
    for ip_stats in snapshot.ips:
        if ip_stats.key in ("-", "") or ip_stats.key in seen_ips:
            continue
        if not _is_abusive_ip(
            ip_stats.rps,
            ip_stats.requests,
            thresholds,
            max_burst_rps=ip_stats.max_burst_rps,
            max_burst_requests=ip_stats.max_burst_requests,
        ):
            continue
        seen_ips.add(ip_stats.key)
        reason = (
            "high_burst_rps"
            if ip_stats.max_burst_rps >= thresholds.min_burst_rps
            else "high_ip_rps"
        )
        recommendations.append(
            BlockRecommendation(
                block_type="ip",
                target=ip_stats.key,
                country_code=None,
                country_name=None,
                requests=ip_stats.requests,
                rps=max(ip_stats.rps, ip_stats.max_burst_rps),
                reason=reason,
                detail=(
                    f"burst {ip_stats.max_burst_rps:.1f} rps / "
                    f"{ip_stats.max_burst_requests} req; "
                    f"UA: {ip_stats.top_user_agent[:60]}"
                ),
            )
        )

    for subnet_stats in snapshot.subnets:
        if not _is_abusive_subnet(
            subnet_stats.rps,
            subnet_stats.requests,
            thresholds,
            max_burst_rps=subnet_stats.max_burst_rps,
            max_burst_requests=subnet_stats.max_burst_requests,
        ):
            continue
        if any(item.target == subnet_stats.key for item in recommendations):
            continue
        reason = (
            "high_burst_rps"
            if subnet_stats.max_burst_rps >= thresholds.min_burst_rps
            else "high_subnet_rps"
        )
        recommendations.append(
            BlockRecommendation(
                block_type="subnet",
                target=subnet_stats.key,
                country_code=None,
                country_name=None,
                requests=subnet_stats.requests,
                rps=max(subnet_stats.rps, subnet_stats.max_burst_rps),
                reason=reason,
                detail=(
                    f"burst {subnet_stats.max_burst_rps:.1f} rps / "
                    f"{subnet_stats.max_burst_requests} req; "
                    f"UA: {subnet_stats.top_user_agent[:60]}"
                ),
            )
        )

    return tuple(
        sorted(
            recommendations,
            key=lambda item: (-item.rps, -item.requests, item.target),
        )
    )

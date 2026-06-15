from __future__ import annotations

from dataclasses import dataclass

from parser import TrafficStats

SIMPLE_MONTH_DAYS = 30.0
ANNUAL_MONTHS = 12.0


@dataclass(frozen=True)
class ProjectedTraffic:
    observed_days: float
    scale_factor: float
    safety_margin: float
    monthly_requests: float
    monthly_bytes: float
    annual_requests: float
    annual_bytes: float


def project_traffic(
    stats: TrafficStats,
    *,
    safety_margin: float = 0.0,
) -> ProjectedTraffic:
    """
    Scale observed log traffic to a 30-day month and annual totals.

    safety_margin adds headroom on top of the scaled traffic (e.g. 0.2 = +20%).
    """
    if stats.total_records == 0 or stats.observed_days <= 0:
        return ProjectedTraffic(
            observed_days=stats.observed_days,
            scale_factor=0.0,
            safety_margin=safety_margin,
            monthly_requests=0.0,
            monthly_bytes=0.0,
            annual_requests=0.0,
            annual_bytes=0.0,
        )

    scale_factor = SIMPLE_MONTH_DAYS / stats.observed_days
    margin_multiplier = 1.0 + max(safety_margin, 0.0)

    monthly_requests = stats.total_records * scale_factor * margin_multiplier
    monthly_bytes = stats.total_bytes * scale_factor * margin_multiplier

    return ProjectedTraffic(
        observed_days=stats.observed_days,
        scale_factor=scale_factor,
        safety_margin=safety_margin,
        monthly_requests=monthly_requests,
        monthly_bytes=monthly_bytes,
        annual_requests=monthly_requests * ANNUAL_MONTHS,
        annual_bytes=monthly_bytes * ANNUAL_MONTHS,
    )

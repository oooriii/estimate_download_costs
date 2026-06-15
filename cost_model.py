from __future__ import annotations

from dataclasses import dataclass

from parser import TrafficStats
from pricing.schema import PricingConfig
from pricing.tiers import tiered_cost
from projection import project_traffic

BYTES_PER_GB = 1024**3
DEFAULT_CONSERVATIVE_SAFETY_MARGIN = 0.20


@dataclass(frozen=True)
class Inventory:
    storage_gb: float
    items: int
    annual_growth_rate: float = 0.0


@dataclass(frozen=True)
class CostLine:
    label: str
    usd: float


@dataclass(frozen=True)
class ScenarioCosts:
    name: str
    monthly: tuple[CostLine, ...]
    annual: tuple[CostLine, ...]

    @property
    def monthly_total(self) -> float:
        return sum(line.usd for line in self.monthly)

    @property
    def annual_total(self) -> float:
        return sum(line.usd for line in self.annual)


@dataclass(frozen=True)
class EstimateResult:
    realistic_s3: ScenarioCosts
    conservative: ScenarioCosts
    realistic_cloudfront: ScenarioCosts | None


def _egress_cost(
    bytes_amount: float,
    pricing: PricingConfig,
    *,
    use_cloudfront: bool,
    first_tier_only: bool,
) -> float:
    amount_gb = bytes_amount / BYTES_PER_GB
    if amount_gb <= 0:
        return 0.0

    tiers = (
        pricing.cloudfront.data_transfer_out_per_gb
        if use_cloudfront and pricing.cloudfront
        else pricing.s3.data_transfer_out_per_gb
    )
    if first_tier_only:
        return amount_gb * tiers[0].price
    return tiered_cost(amount_gb, tiers)


def _storage_monthly_cost(
    inventory: Inventory,
    pricing: PricingConfig,
    storage_class: str,
) -> float:
    return inventory.storage_gb * pricing.s3.storage_per_gb_month[storage_class]


def _monitoring_monthly_cost(inventory: Inventory, pricing: PricingConfig) -> float:
    return (inventory.items / 1000.0) * (
        pricing.s3.intelligent_tiering_monitoring_per_1000_objects
    )


def _annualize(monthly: tuple[CostLine, ...]) -> tuple[CostLine, ...]:
    return tuple(CostLine(line.label, line.usd * 12.0) for line in monthly)


def calculate_s3_direct(
    traffic_monthly_requests: float,
    traffic_monthly_bytes: float,
    inventory: Inventory,
    pricing: PricingConfig,
    storage_class: str,
    *,
    scenario_name: str = "S3 direct",
    first_tier_egress_only: bool = False,
) -> ScenarioCosts:
    monthly_lines = [
        CostLine("Storage", _storage_monthly_cost(inventory, pricing, storage_class)),
    ]
    if storage_class == "INTELLIGENT_TIERING":
        monthly_lines.append(
            CostLine(
                "Intelligent-Tiering monitoring",
                _monitoring_monthly_cost(inventory, pricing),
            )
        )
    monthly_lines.extend(
        [
            CostLine(
                "GET requests",
                (traffic_monthly_requests / 1000.0)
                * pricing.s3.requests_per_1000["GET"],
            ),
            CostLine(
                "Data transfer out",
                _egress_cost(
                    traffic_monthly_bytes,
                    pricing,
                    use_cloudfront=False,
                    first_tier_only=first_tier_egress_only,
                ),
            ),
        ]
    )
    monthly = tuple(monthly_lines)
    return ScenarioCosts(
        name=scenario_name,
        monthly=monthly,
        annual=_annualize(monthly),
    )


def calculate_cloudfront(
    traffic_monthly_requests: float,
    traffic_monthly_bytes: float,
    inventory: Inventory,
    pricing: PricingConfig,
    storage_class: str,
    *,
    cache_hit_ratio: float,
    scenario_name: str,
    first_tier_egress_only: bool = False,
) -> ScenarioCosts:
    if pricing.cloudfront is None:
        raise ValueError("CloudFront pricing is not configured")

    cache_miss_ratio = 1.0 - cache_hit_ratio
    monthly_lines = [
        CostLine("Storage", _storage_monthly_cost(inventory, pricing, storage_class)),
    ]
    if storage_class == "INTELLIGENT_TIERING":
        monthly_lines.append(
            CostLine(
                "Intelligent-Tiering monitoring",
                _monitoring_monthly_cost(inventory, pricing),
            )
        )

    origin_requests = traffic_monthly_requests * cache_miss_ratio
    monthly_lines.extend(
        [
            CostLine(
                "S3 origin GET requests",
                (origin_requests / 1000.0) * pricing.s3.requests_per_1000["GET"],
            ),
            CostLine(
                "S3 origin data transfer",
                _egress_cost(
                    traffic_monthly_bytes * cache_miss_ratio,
                    pricing,
                    use_cloudfront=False,
                    first_tier_only=first_tier_egress_only,
                ),
            ),
            CostLine(
                "CloudFront data transfer",
                _egress_cost(
                    traffic_monthly_bytes,
                    pricing,
                    use_cloudfront=True,
                    first_tier_only=first_tier_egress_only,
                ),
            ),
            CostLine(
                "CloudFront requests",
                (traffic_monthly_requests / 10000.0)
                * pricing.cloudfront.requests_per_10000["GET"],
            ),
        ]
    )
    monthly = tuple(monthly_lines)
    return ScenarioCosts(
        name=scenario_name,
        monthly=monthly,
        annual=_annualize(monthly),
    )


def build_estimates(
    stats: TrafficStats,
    inventory: Inventory,
    pricing: PricingConfig,
    storage_class: str,
) -> EstimateResult:
    realistic_traffic = project_traffic(stats, safety_margin=0.0)
    conservative_traffic = project_traffic(
        stats,
        safety_margin=DEFAULT_CONSERVATIVE_SAFETY_MARGIN,
    )

    realistic_s3 = calculate_s3_direct(
        realistic_traffic.monthly_requests,
        realistic_traffic.monthly_bytes,
        inventory,
        pricing,
        storage_class,
    )

    conservative_candidates = [
        calculate_s3_direct(
            conservative_traffic.monthly_requests,
            conservative_traffic.monthly_bytes,
            inventory,
            pricing,
            storage_class,
            scenario_name="Conservative (S3 direct)",
            first_tier_egress_only=True,
        )
    ]

    realistic_cloudfront: ScenarioCosts | None = None
    if pricing.cloudfront is not None:
        realistic_cloudfront = calculate_cloudfront(
            realistic_traffic.monthly_requests,
            realistic_traffic.monthly_bytes,
            inventory,
            pricing,
            storage_class,
            cache_hit_ratio=pricing.cloudfront.recommended_cache_hit_ratio,
            scenario_name=(
                "S3 + CloudFront "
                f"({pricing.cloudfront.recommended_cache_hit_ratio:.0%} cache hit)"
            ),
        )
        conservative_candidates.append(
            calculate_cloudfront(
                conservative_traffic.monthly_requests,
                conservative_traffic.monthly_bytes,
                inventory,
                pricing,
                storage_class,
                cache_hit_ratio=0.0,
                scenario_name="Conservative (S3 + CloudFront, 0% cache)",
                first_tier_egress_only=True,
            )
        )

    conservative = max(conservative_candidates, key=lambda item: item.annual_total)
    conservative = ScenarioCosts(
        name=f"Conservative worst case ({conservative.name})",
        monthly=conservative.monthly,
        annual=conservative.annual,
    )

    return EstimateResult(
        realistic_s3=realistic_s3,
        conservative=conservative,
        realistic_cloudfront=realistic_cloudfront,
    )

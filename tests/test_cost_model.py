from datetime import UTC, date, datetime

import pytest

from cost_model import (
    Inventory,
    build_estimates,
    calculate_s3_direct,
    compare_storage_classes,
)
from parser import TrafficStats
from pricing.schema import (
    STORAGE_CLASSES,
    CloudFrontPricing,
    DisplayConfig,
    PriceTier,
    PricingConfig,
    S3Pricing,
)
from projection import project_traffic


@pytest.fixture
def pricing_config() -> PricingConfig:
    return PricingConfig(
        effective_date=date(2026, 6, 15),
        region="eu-south-2",
        currency="USD",
        display=DisplayConfig(
            show_eur=True,
            usd_eur_rate=0.92,
            rate_note="test",
        ),
        sources={},
        s3=S3Pricing(
            storage_per_gb_month={
                "STANDARD": 0.023,
                "STANDARD_IA": 0.0125,
                "INTELLIGENT_TIERING": 0.023,
                "GLACIER_INSTANT": 0.005,
            },
            intelligent_tiering_monitoring_per_1000_objects=0.0025,
            requests_per_1000={"GET": 0.0004, "PUT": 0.005, "LIST": 0.005},
            data_transfer_out_per_gb=(
                PriceTier(up_to_gb=10240, price=0.09),
                PriceTier(up_to_gb=None, price=0.085),
            ),
        ),
        cloudfront=CloudFrontPricing(
            data_transfer_out_per_gb=(
                PriceTier(up_to_gb=10240, price=0.085),
                PriceTier(up_to_gb=None, price=0.08),
            ),
            requests_per_10000={"GET": 0.012},
            recommended_cache_hit_ratio=0.85,
        ),
    )


@pytest.fixture
def sample_stats() -> TrafficStats:
    return TrafficStats(
        min_date=datetime(2026, 6, 1, tzinfo=UTC),
        max_date=datetime(2026, 6, 16, tzinfo=UTC),
        total_records=1000,
        total_bytes=100 * 1024**3,
    )


def test_calculate_s3_direct_includes_storage_and_transfer(pricing_config):
    scenario = calculate_s3_direct(
        traffic_monthly_requests=10_000,
        traffic_monthly_bytes=500 * 1024**3,
        inventory=Inventory(storage_gb=1000, items=10_000),
        pricing=pricing_config,
        storage_class="STANDARD",
    )

    assert scenario.monthly_total > 0
    assert scenario.monthly_total == pytest.approx(scenario.annual_total / 12.0)
    assert any(line.label == "Storage" for line in scenario.monthly)
    assert any(line.label == "Data transfer out" for line in scenario.monthly)


def test_conservative_estimate_is_higher_than_realistic(pricing_config, sample_stats):
    result = build_estimates(
        sample_stats,
        Inventory(storage_gb=1000, items=10_000),
        pricing_config,
        "STANDARD",
    )

    assert result.conservative.annual_total >= result.realistic_s3.annual_total
    assert result.realistic_cloudfront is not None


def test_projected_traffic_used_in_estimates(pricing_config, sample_stats):
    traffic = project_traffic(sample_stats)
    result = build_estimates(
        sample_stats,
        Inventory(storage_gb=100, items=1000),
        pricing_config,
        "STANDARD",
    )
    assert traffic.monthly_requests > 0
    assert result.realistic_s3.monthly_total > 0


def test_compare_storage_classes_covers_all_classes(pricing_config, sample_stats):
    inventory = Inventory(storage_gb=1000, items=10_000)
    comparisons = compare_storage_classes(
        sample_stats,
        inventory,
        pricing_config,
        STORAGE_CLASSES,
    )

    assert len(comparisons) == len(STORAGE_CLASSES)
    assert {item.name for item in comparisons} == set(STORAGE_CLASSES)


def test_compare_storage_classes_glacier_is_cheapest_storage(
    pricing_config, sample_stats
):
    inventory = Inventory(storage_gb=10_000, items=100_000)
    comparisons = compare_storage_classes(
        sample_stats,
        inventory,
        pricing_config,
        STORAGE_CLASSES,
    )
    by_name = {item.name: item for item in comparisons}

    assert by_name["GLACIER_INSTANT"].monthly_total < by_name["STANDARD"].monthly_total

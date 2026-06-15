import json
from datetime import date
from pathlib import Path

import pytest

from pricing.loader import load_pricing_config, save_pricing_config
from pricing.schema import (
    CloudFrontPricing,
    DisplayConfig,
    PriceTier,
    PricingConfig,
    PricingValidationError,
    S3Pricing,
    parse_pricing_config,
)
from pricing.tiers import tiered_cost

TEMPLATE_PATH = Path("pricing/templates/eu-south-2.json")


@pytest.fixture
def sample_config() -> PricingConfig:
    return PricingConfig(
        effective_date=date(2026, 6, 15),
        region="eu-south-2",
        currency="USD",
        display=DisplayConfig(
            show_eur=True,
            usd_eur_rate=0.92,
            rate_note="test",
        ),
        sources={"s3": "https://aws.amazon.com/s3/pricing/"},
        s3=S3Pricing(
            storage_per_gb_month={
                "STANDARD": 0.0255,
                "STANDARD_IA": 0.014,
                "INTELLIGENT_TIERING": 0.0255,
                "GLACIER_INSTANT": 0.0045,
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
            requests_per_10000={"GET": 0.0075},
            recommended_cache_hit_ratio=0.85,
        ),
    )


def test_template_file_is_valid():
    config, warnings = load_pricing_config(TEMPLATE_PATH)
    assert config.region == "eu-south-2"
    assert config.s3.storage_per_gb_month["STANDARD"] > 0
    assert isinstance(warnings, list)


def test_parse_rejects_unordered_tiers():
    with pytest.raises(PricingValidationError):
        parse_pricing_config(
            {
                "effective_date": "2026-06-15",
                "region": "eu-south-2",
                "display": {"usd_eur_rate": 0.92},
                "s3": {
                    "storage_per_gb_month": {
                        "STANDARD": 0.02,
                        "STANDARD_IA": 0.01,
                        "INTELLIGENT_TIERING": 0.02,
                        "GLACIER_INSTANT": 0.004,
                    },
                    "intelligent_tiering_monitoring_per_1000_objects": 0.0025,
                    "requests_per_1000": {"GET": 0.0004, "PUT": 0.005, "LIST": 0.005},
                    "data_transfer_out_per_gb": [
                        {"up_to_gb": 20480, "price": 0.09},
                        {"up_to_gb": 10240, "price": 0.085},
                        {"up_to_gb": None, "price": 0.08},
                    ],
                },
            }
        )


def test_tiered_cost_applies_multiple_tiers():
    tiers = (
        PriceTier(up_to_gb=10, price=0.10),
        PriceTier(up_to_gb=None, price=0.05),
    )
    assert tiered_cost(5, tiers) == pytest.approx(0.50)
    assert tiered_cost(15, tiers) == pytest.approx(1.25)


def test_save_and_load_roundtrip(tmp_path, sample_config):
    target = tmp_path / "pricing.json"
    save_pricing_config(target, sample_config)
    loaded, _ = load_pricing_config(target)
    assert loaded.region == sample_config.region
    assert loaded.s3.storage_per_gb_month == sample_config.s3.storage_per_gb_month
    assert loaded.cloudfront is not None
    assert loaded.cloudfront.recommended_cache_hit_ratio == 0.85


def test_load_invalid_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(PricingValidationError):
        load_pricing_config(bad)

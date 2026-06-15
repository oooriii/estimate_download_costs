import json

import pytest

from pricing.generate import (
    CLOUDFRONT_GET_USAGETYPE,
    S3_USAGETYPE_BY_STORAGE_CLASS,
    generate_pricing_config,
)
from pricing.loader import save_pricing_config
from pricing.schema import parse_pricing_config


@pytest.fixture
def fake_offers(tmp_path, monkeypatch):
    s3_offer = {
        "publicationDate": "2026-06-15T00:00:00Z",
        "products": {},
        "terms": {"OnDemand": {}},
    }
    cf_offer = {
        "publicationDate": "2026-06-15T00:00:00Z",
        "products": {},
        "terms": {"OnDemand": {}},
    }

    def add_s3(usagetype: str, unit_price: float, begin=0, end="Inf"):
        sku = f"s3-{usagetype}"
        s3_offer["products"][sku] = {"attributes": {"usagetype": usagetype}}
        s3_offer["terms"]["OnDemand"][sku] = {
            "term": {
                "priceDimensions": {
                    "dim": {
                        "beginRange": str(begin),
                        "endRange": end,
                        "pricePerUnit": {"USD": str(unit_price)},
                    }
                }
            }
        }

    def add_cf(usagetype: str, unit_price: float, begin=0, end="Inf", suffix=""):
        sku = f"cf-{suffix}-{usagetype}"
        cf_offer["products"][sku] = {"attributes": {"usagetype": usagetype}}
        cf_offer["terms"]["OnDemand"][sku] = {
            "term": {
                "priceDimensions": {
                    "dim": {
                        "beginRange": str(begin),
                        "endRange": end,
                        "pricePerUnit": {"USD": str(unit_price)},
                    }
                }
            }
        }

    add_s3(S3_USAGETYPE_BY_STORAGE_CLASS["STANDARD"], 0.023)
    add_s3(S3_USAGETYPE_BY_STORAGE_CLASS["STANDARD_IA"], 0.0125)
    add_s3(S3_USAGETYPE_BY_STORAGE_CLASS["INTELLIGENT_TIERING"], 0.023)
    add_s3(S3_USAGETYPE_BY_STORAGE_CLASS["GLACIER_INSTANT"], 0.005)
    add_s3("EUS2-Requests-Tier2", 0.0000004)
    add_s3("EUS2-Requests-Tier1", 0.0000053)
    add_s3("EUS2-Monitoring-Automation-INT", 0.0000025)
    add_cf("EU-DataTransfer-Out-Bytes", 0.085, begin=0, end="10240", suffix="t1")
    add_cf("EU-DataTransfer-Out-Bytes", 0.08, begin="10240", end="Inf", suffix="t2")
    add_cf(CLOUDFRONT_GET_USAGETYPE, 0.0000012)

    offers_dir = tmp_path / "aws-offers"
    offers_dir.mkdir()
    (offers_dir / "amazon-s3-eu-south-2.json").write_text(
        json.dumps(s3_offer),
        encoding="utf-8",
    )
    (offers_dir / "amazon-cloudfront-eu.json").write_text(
        json.dumps(cf_offer),
        encoding="utf-8",
    )
    (offers_dir / "manifest.json").write_text(
        json.dumps({"downloaded_at": "2026-06-15T12:00:00+00:00"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "pricing.aws_offers.OFFERS_DIR",
        offers_dir,
    )
    monkeypatch.setattr(
        "pricing.aws_offers.CACHED_FILES",
        {
            "amazon-s3-eu-south-2": offers_dir / "amazon-s3-eu-south-2.json",
            "amazon-cloudfront": offers_dir / "amazon-cloudfront.json",
            "amazon-cloudfront-eu": offers_dir / "amazon-cloudfront-eu.json",
            "manifest": offers_dir / "manifest.json",
        },
    )
    return offers_dir


def test_generate_pricing_config_from_cached_offers(fake_offers):
    config, warnings = generate_pricing_config(usd_eur_rate=0.95)

    assert config.region == "eu-south-2"
    assert config.s3.storage_per_gb_month["STANDARD"] == 0.023
    assert config.s3.requests_per_1000["GET"] == pytest.approx(0.0004)
    assert config.s3.requests_per_1000["PUT"] == pytest.approx(0.0053)
    assert config.cloudfront is not None
    assert config.cloudfront.requests_per_10000["GET"] == pytest.approx(0.012)
    assert config.cloudfront.data_transfer_out_per_gb[0].price == 0.085
    assert any("egress" in warning.lower() for warning in warnings)
    parse_pricing_config(config.to_dict())


def test_generate_pricing_config_can_write_file(fake_offers, tmp_path):
    config, _ = generate_pricing_config()
    target = tmp_path / "eu-south-2.json"
    save_pricing_config(target, config)
    assert target.is_file()


def test_generate_cli_uses_repo_cache():
    from pricing.generate import generate_pricing_config

    config, _ = generate_pricing_config()
    assert config.s3.storage_per_gb_month["STANDARD"] == 0.023
    assert config.s3.storage_per_gb_month["STANDARD_IA"] == 0.0125

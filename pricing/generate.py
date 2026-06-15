from __future__ import annotations

from datetime import date
from typing import Any

from pricing.aws_offers import load_cached_offer, load_manifest
from pricing.defaults import EU_SOUTH_2_DEFAULTS
from pricing.schema import (
    DEFAULT_USD_EUR_RATE,
    CloudFrontPricing,
    DisplayConfig,
    PriceTier,
    PricingConfig,
    S3Pricing,
    parse_pricing_config,
)

# S3 internet egress is not published per region in the S3 offer file.
# These are the standard AWS data transfer out rates used for EU regions.
S3_EGRESS_FALLBACK_TIERS: tuple[PriceTier, ...] = (
    PriceTier(up_to_gb=10240, price=0.09),
    PriceTier(up_to_gb=None, price=0.085),
)

S3_USAGETYPE_BY_STORAGE_CLASS = {
    "STANDARD": "EUS2-TimedStorage-ByteHrs",
    "STANDARD_IA": "EUS2-TimedStorage-SIA-ByteHrs",
    "INTELLIGENT_TIERING": "EUS2-TimedStorage-INT-FA-ByteHrs",
    "GLACIER_INSTANT": "EUS2-TimedStorage-GIR-ByteHrs",
}

S3_REQUEST_USAGETYPES = {
    "GET": "EUS2-Requests-Tier2",
    "PUT": "EUS2-Requests-Tier1",
    "LIST": "EUS2-Requests-Tier1",
}

CLOUDFRONT_GET_USAGETYPE = "EU-Requests-Tier2-HTTPS"
CLOUDFRONT_TRANSFER_USAGETYPE = "EU-DataTransfer-Out-Bytes"


class PricingGenerationError(RuntimeError):
    pass


def _iter_price_dimensions(
    offer: dict[str, Any],
    usagetype: str,
) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    for sku, product in offer["products"].items():
        if product["attributes"].get("usagetype") != usagetype:
            continue
        for term in offer["terms"]["OnDemand"][sku].values():
            for dimension in term["priceDimensions"].values():
                begin = dimension.get("beginRange")
                end = dimension.get("endRange")
                dimensions.append(
                    {
                        "begin": float(begin) if begin is not None else 0.0,
                        "end": None if end in (None, "Inf") else float(end),
                        "price": float(dimension["pricePerUnit"]["USD"]),
                        "description": dimension.get("description", ""),
                    }
                )
    if not dimensions:
        raise PricingGenerationError(f"Usage type not found in AWS offer: {usagetype}")
    return sorted(dimensions, key=lambda item: item["begin"])


def _first_tier_unit_price(offer: dict[str, Any], usagetype: str) -> float:
    return _iter_price_dimensions(offer, usagetype)[0]["price"]


def _per_thousand_price(offer: dict[str, Any], usagetype: str) -> float:
    return _first_tier_unit_price(offer, usagetype) * 1000


def _per_ten_thousand_price(offer: dict[str, Any], usagetype: str) -> float:
    return _first_tier_unit_price(offer, usagetype) * 10000


def _transfer_tiers_from_offer(
    offer: dict[str, Any], usagetype: str
) -> tuple[PriceTier, ...]:
    dimensions = _iter_price_dimensions(offer, usagetype)
    tiers: list[PriceTier] = []
    for index, dimension in enumerate(dimensions):
        if index == len(dimensions) - 1:
            tiers.append(PriceTier(up_to_gb=None, price=dimension["price"]))
        else:
            tiers.append(PriceTier(up_to_gb=dimension["end"], price=dimension["price"]))
    return tuple(tiers)


def _effective_date_from_offers() -> date:
    manifest = load_manifest()
    downloaded_at = manifest.get("downloaded_at", "")
    if downloaded_at:
        return date.fromisoformat(downloaded_at[:10])

    s3_offer = load_cached_offer("amazon-s3-eu-south-2")
    publication_date = s3_offer.get("publicationDate", "")
    if publication_date:
        return date.fromisoformat(publication_date[:10])
    return date.today()


def generate_pricing_config(
    *,
    region: str = "eu-south-2",
    usd_eur_rate: float = DEFAULT_USD_EUR_RATE,
    include_cloudfront: bool = True,
) -> tuple[PricingConfig, list[str]]:
    s3_offer = load_cached_offer("amazon-s3-eu-south-2")
    warnings: list[str] = [
        "S3 internet egress tiers are not present in the regional S3 offer file; "
        "using standard AWS data transfer out rates (0.09 / 0.085 USD per GB).",
    ]

    storage = {
        storage_class: _first_tier_unit_price(s3_offer, usagetype)
        for storage_class, usagetype in S3_USAGETYPE_BY_STORAGE_CLASS.items()
    }
    requests = {
        request_type: _per_thousand_price(s3_offer, usagetype)
        for request_type, usagetype in S3_REQUEST_USAGETYPES.items()
    }

    cloudfront: CloudFrontPricing | None = None
    if include_cloudfront:
        cf_offer = load_cached_offer("amazon-cloudfront-eu")
        cloudfront = CloudFrontPricing(
            data_transfer_out_per_gb=_transfer_tiers_from_offer(
                cf_offer,
                CLOUDFRONT_TRANSFER_USAGETYPE,
            ),
            requests_per_10000={
                "GET": _per_ten_thousand_price(cf_offer, CLOUDFRONT_GET_USAGETYPE),
            },
            recommended_cache_hit_ratio=EU_SOUTH_2_DEFAULTS[
                "recommended_cache_hit_ratio"
            ],
        )

    config = PricingConfig(
        effective_date=_effective_date_from_offers(),
        region=region,
        currency="USD",
        display=DisplayConfig(
            show_eur=True,
            usd_eur_rate=usd_eur_rate,
            rate_note="Manual rate; update when estimating for finance reports.",
        ),
        sources={
            "s3": "https://aws.amazon.com/s3/pricing/",
            "cloudfront": "https://aws.amazon.com/cloudfront/pricing/",
            "region": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
            "aws_offer_cache": "pricing/aws-offers/",
        },
        s3=S3Pricing(
            storage_per_gb_month=storage,
            intelligent_tiering_monitoring_per_1000_objects=_per_thousand_price(
                s3_offer,
                "EUS2-Monitoring-Automation-INT",
            ),
            requests_per_1000=requests,
            data_transfer_out_per_gb=S3_EGRESS_FALLBACK_TIERS,
        ),
        cloudfront=cloudfront,
    )

    parse_pricing_config(config.to_dict())
    return config, warnings

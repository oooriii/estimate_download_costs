from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


DEFAULT_USD_EUR_RATE = 0.92
DEFAULT_USD_EUR_RATE_WARNING = (
    "Using default USD/EUR rate (0.92). Update it to match current exchange rates."
)
STORAGE_CLASSES = (
    "STANDARD",
    "STANDARD_IA",
    "INTELLIGENT_TIERING",
    "GLACIER_INSTANT",
)
REQUEST_TYPES = ("GET", "PUT", "LIST")
DEFAULT_GROWTH_RATE = 0.10


@dataclass(frozen=True)
class PriceTier:
    up_to_gb: float | None
    price: float


@dataclass(frozen=True)
class DisplayConfig:
    show_eur: bool
    usd_eur_rate: float
    rate_note: str


@dataclass(frozen=True)
class S3Pricing:
    storage_per_gb_month: dict[str, float]
    intelligent_tiering_monitoring_per_1000_objects: float
    requests_per_1000: dict[str, float]
    data_transfer_out_per_gb: tuple[PriceTier, ...]


@dataclass(frozen=True)
class CloudFrontPricing:
    data_transfer_out_per_gb: tuple[PriceTier, ...]
    requests_per_10000: dict[str, float]
    recommended_cache_hit_ratio: float


@dataclass(frozen=True)
class PricingConfig:
    effective_date: date
    region: str
    currency: str
    display: DisplayConfig
    sources: dict[str, str]
    s3: S3Pricing
    cloudfront: CloudFrontPricing | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_date": self.effective_date.isoformat(),
            "region": self.region,
            "currency": self.currency,
            "display": {
                "show_eur": self.display.show_eur,
                "usd_eur_rate": self.display.usd_eur_rate,
                "rate_note": self.display.rate_note,
            },
            "sources": dict(self.sources),
            "s3": {
                "storage_per_gb_month": dict(self.s3.storage_per_gb_month),
                "intelligent_tiering_monitoring_per_1000_objects": (
                    self.s3.intelligent_tiering_monitoring_per_1000_objects
                ),
                "requests_per_1000": dict(self.s3.requests_per_1000),
                "data_transfer_out_per_gb": [
                    {"up_to_gb": tier.up_to_gb, "price": tier.price}
                    for tier in self.s3.data_transfer_out_per_gb
                ],
            },
            "cloudfront": None
            if self.cloudfront is None
            else {
                "data_transfer_out_per_gb": [
                    {"up_to_gb": tier.up_to_gb, "price": tier.price}
                    for tier in self.cloudfront.data_transfer_out_per_gb
                ],
                "requests_per_10000": dict(self.cloudfront.requests_per_10000),
                "recommended_cache_hit_ratio": (
                    self.cloudfront.recommended_cache_hit_ratio
                ),
            },
        }


class PricingValidationError(ValueError):
    pass


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise PricingValidationError(f"{field} must be a string in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PricingValidationError(
            f"{field} must be a valid date in YYYY-MM-DD format"
        ) from exc


def _parse_price_tiers(value: Any, field: str) -> tuple[PriceTier, ...]:
    if not isinstance(value, list) or not value:
        raise PricingValidationError(f"{field} must be a non-empty list")

    tiers: list[PriceTier] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise PricingValidationError(f"{field}[{index}] must be an object")
        if "price" not in item:
            raise PricingValidationError(f"{field}[{index}] missing price")
        price = item["price"]
        if not isinstance(price, (int, float)) or price < 0:
            raise PricingValidationError(f"{field}[{index}].price must be >= 0")

        up_to_gb = item.get("up_to_gb")
        if up_to_gb is not None and (not isinstance(up_to_gb, (int, float)) or up_to_gb <= 0):
            raise PricingValidationError(
                f"{field}[{index}].up_to_gb must be null or a positive number"
            )
        tiers.append(PriceTier(up_to_gb=up_to_gb, price=float(price)))

    if tiers[-1].up_to_gb is not None:
        raise PricingValidationError(f"{field} last tier must have up_to_gb = null")

    limits = [tier.up_to_gb for tier in tiers[:-1]]
    if limits != sorted(limits):
        raise PricingValidationError(f"{field} tiers must be in ascending order")

    return tuple(tiers)


def _parse_price_map(value: Any, field: str, required_keys: tuple[str, ...]) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise PricingValidationError(f"{field} must be a non-empty object")

    parsed: dict[str, float] = {}
    for key, price in value.items():
        if not isinstance(key, str):
            raise PricingValidationError(f"{field} keys must be strings")
        if not isinstance(price, (int, float)) or price < 0:
            raise PricingValidationError(f"{field}.{key} must be >= 0")
        parsed[key] = float(price)

    missing = [key for key in required_keys if key not in parsed]
    if missing:
        raise PricingValidationError(f"{field} missing required keys: {', '.join(missing)}")

    return parsed


def parse_pricing_config(data: dict[str, Any]) -> PricingConfig:
    if not isinstance(data, dict):
        raise PricingValidationError("Pricing file must contain a JSON object")

    effective_date = _parse_date(data.get("effective_date"), "effective_date")
    region = data.get("region")
    if not isinstance(region, str) or not region.strip():
        raise PricingValidationError("region must be a non-empty string")

    currency = data.get("currency", "USD")
    if currency != "USD":
        raise PricingValidationError("currency must be USD (AWS bills in USD)")

    display_data = data.get("display")
    if not isinstance(display_data, dict):
        raise PricingValidationError("display must be an object")
    usd_eur_rate = display_data.get("usd_eur_rate")
    if not isinstance(usd_eur_rate, (int, float)) or usd_eur_rate <= 0:
        raise PricingValidationError("display.usd_eur_rate must be > 0")
    show_eur = display_data.get("show_eur", True)
    if not isinstance(show_eur, bool):
        raise PricingValidationError("display.show_eur must be a boolean")
    rate_note = display_data.get("rate_note", "")
    if not isinstance(rate_note, str):
        raise PricingValidationError("display.rate_note must be a string")

    sources = data.get("sources", {})
    if not isinstance(sources, dict):
        raise PricingValidationError("sources must be an object")

    s3_data = data.get("s3")
    if not isinstance(s3_data, dict):
        raise PricingValidationError("s3 must be an object")

    monitoring = s3_data.get("intelligent_tiering_monitoring_per_1000_objects")
    if not isinstance(monitoring, (int, float)) or monitoring < 0:
        raise PricingValidationError(
            "s3.intelligent_tiering_monitoring_per_1000_objects must be >= 0"
        )

    s3 = S3Pricing(
        storage_per_gb_month=_parse_price_map(
            s3_data.get("storage_per_gb_month"),
            "s3.storage_per_gb_month",
            STORAGE_CLASSES,
        ),
        intelligent_tiering_monitoring_per_1000_objects=float(monitoring),
        requests_per_1000=_parse_price_map(
            s3_data.get("requests_per_1000"),
            "s3.requests_per_1000",
            REQUEST_TYPES,
        ),
        data_transfer_out_per_gb=_parse_price_tiers(
            s3_data.get("data_transfer_out_per_gb"),
            "s3.data_transfer_out_per_gb",
        ),
    )

    cloudfront_data = data.get("cloudfront")
    cloudfront: CloudFrontPricing | None = None
    if cloudfront_data is not None:
        if not isinstance(cloudfront_data, dict):
            raise PricingValidationError("cloudfront must be an object")
        ratio = cloudfront_data.get("recommended_cache_hit_ratio")
        if not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
            raise PricingValidationError(
                "cloudfront.recommended_cache_hit_ratio must be between 0 and 1"
            )
        cloudfront = CloudFrontPricing(
            data_transfer_out_per_gb=_parse_price_tiers(
                cloudfront_data.get("data_transfer_out_per_gb"),
                "cloudfront.data_transfer_out_per_gb",
            ),
            requests_per_10000=_parse_price_map(
                cloudfront_data.get("requests_per_10000"),
                "cloudfront.requests_per_10000",
                ("GET",),
            ),
            recommended_cache_hit_ratio=float(ratio),
        )

    return PricingConfig(
        effective_date=effective_date,
        region=region.strip(),
        currency=currency,
        display=DisplayConfig(
            show_eur=show_eur,
            usd_eur_rate=float(usd_eur_rate),
            rate_note=rate_note,
        ),
        sources={str(key): str(value) for key, value in sources.items()},
        s3=s3,
        cloudfront=cloudfront,
    )


def collect_warnings(config: PricingConfig, today: date | None = None) -> list[str]:
    warnings: list[str] = []
    current = today or date.today()
    age_days = (current - config.effective_date).days
    if age_days > 180:
        warnings.append(
            f"Pricing effective date is {age_days} days old "
            f"({config.effective_date.isoformat()}). AWS prices may have changed."
        )
    if config.display.usd_eur_rate == DEFAULT_USD_EUR_RATE:
        warnings.append(DEFAULT_USD_EUR_RATE_WARNING)
    return warnings


def format_money(usd: float, rate: float, show_eur: bool = True) -> str:
    if show_eur:
        return f"${usd:,.2f} (€{usd * rate:,.2f})"
    return f"${usd:,.2f}"

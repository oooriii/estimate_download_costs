from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

OFFERS_DIR = Path(__file__).resolve().parent / "aws-offers"

OFFER_SOURCES = {
    "amazon-s3": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/index.json",
    "amazon-cloudfront": (
        "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudFront/current/index.json"
    ),
}

CACHED_FILES = {
    "amazon-s3-eu-south-2": OFFERS_DIR / "amazon-s3-eu-south-2.json",
    "amazon-cloudfront": OFFERS_DIR / "amazon-cloudfront.json",
    "amazon-cloudfront-eu": OFFERS_DIR / "amazon-cloudfront-eu.json",
    "manifest": OFFERS_DIR / "manifest.json",
}


@dataclass(frozen=True)
class DownloadResult:
    name: str
    path: Path
    product_count: int
    publication_date: str | None


def _fetch_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=120) as response:
        return json.load(response)


def _filter_offer(
    data: dict[str, Any],
    product_filter,
) -> dict[str, Any]:
    products = {
        sku: product
        for sku, product in data["products"].items()
        if product_filter(product["attributes"])
    }
    terms = {
        sku: data["terms"]["OnDemand"][sku]
        for sku in products
        if sku in data["terms"]["OnDemand"]
    }
    return {
        "formatVersion": data.get("formatVersion"),
        "offerCode": data.get("offerCode"),
        "version": data.get("version"),
        "publicationDate": data.get("publicationDate"),
        "products": products,
        "terms": {"OnDemand": terms},
    }


def _s3_eu_south_2_filter(attributes: dict[str, Any]) -> bool:
    return attributes.get("regionCode") == "eu-south-2"


def _cloudfront_eu_filter(attributes: dict[str, Any]) -> bool:
    return attributes.get("usagetype", "").startswith("EU-")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_cached_offer(name: str) -> dict[str, Any]:
    path = CACHED_FILES[name]
    if not path.is_file():
        raise FileNotFoundError(
            f"Cached AWS offer '{name}' not found at {path}. "
            "Run: uv run python main.py pricing download-offers"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest() -> dict[str, Any]:
    return load_cached_offer("manifest")


def download_offers(fetch: Any = _fetch_json) -> list[DownloadResult]:
    OFFERS_DIR.mkdir(parents=True, exist_ok=True)
    downloaded_at = datetime.now(UTC).isoformat()
    results: list[DownloadResult] = []

    s3_data = fetch(OFFER_SOURCES["amazon-s3"])
    s3_filtered = _filter_offer(s3_data, _s3_eu_south_2_filter)
    _write_json(CACHED_FILES["amazon-s3-eu-south-2"], s3_filtered)
    results.append(
        DownloadResult(
            name="amazon-s3-eu-south-2",
            path=CACHED_FILES["amazon-s3-eu-south-2"],
            product_count=len(s3_filtered["products"]),
            publication_date=s3_data.get("publicationDate"),
        )
    )

    cloudfront_data = fetch(OFFER_SOURCES["amazon-cloudfront"])
    _write_json(CACHED_FILES["amazon-cloudfront"], cloudfront_data)
    results.append(
        DownloadResult(
            name="amazon-cloudfront",
            path=CACHED_FILES["amazon-cloudfront"],
            product_count=len(cloudfront_data["products"]),
            publication_date=cloudfront_data.get("publicationDate"),
        )
    )

    cloudfront_eu = _filter_offer(cloudfront_data, _cloudfront_eu_filter)
    _write_json(CACHED_FILES["amazon-cloudfront-eu"], cloudfront_eu)
    results.append(
        DownloadResult(
            name="amazon-cloudfront-eu",
            path=CACHED_FILES["amazon-cloudfront-eu"],
            product_count=len(cloudfront_eu["products"]),
            publication_date=cloudfront_data.get("publicationDate"),
        )
    )

    manifest = {
        "downloaded_at": downloaded_at,
        "sources": OFFER_SOURCES,
        "files": {
            result.name: {
                "path": str(result.path.relative_to(OFFERS_DIR.parent.parent)),
                "product_count": result.product_count,
                "publication_date": result.publication_date,
            }
            for result in results
        },
        "notes": (
            "Filtered S3 offer contains only eu-south-2 SKUs. "
            "Full CloudFront offer is stored unfiltered. "
            "CloudFront EU file keeps usagetype prefixes starting with EU-."
        ),
    }
    _write_json(CACHED_FILES["manifest"], manifest)
    results.append(
        DownloadResult(
            name="manifest",
            path=CACHED_FILES["manifest"],
            product_count=len(manifest["files"]),
            publication_date=None,
        )
    )
    return results

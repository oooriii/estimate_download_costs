import json

import pytest

from pricing.aws_offers import (
    CACHED_FILES,
    OFFERS_DIR,
    _cloudfront_eu_filter,
    _filter_offer,
    _s3_eu_south_2_filter,
    download_offers,
    load_cached_offer,
    load_manifest,
)


def test_s3_filter_keeps_only_eu_south_2():
    data = {
        "formatVersion": "v1.0",
        "offerCode": "AmazonS3",
        "version": "test",
        "publicationDate": "2026-06-15T00:00:00Z",
        "products": {
            "a": {"attributes": {"regionCode": "eu-south-2", "usagetype": "EUS2-X"}},
            "b": {"attributes": {"regionCode": "eu-west-1", "usagetype": "EUW1-X"}},
        },
        "terms": {
            "OnDemand": {
                "a": {"term": "a"},
                "b": {"term": "b"},
            }
        },
    }

    filtered = _filter_offer(data, _s3_eu_south_2_filter)

    assert set(filtered["products"]) == {"a"}
    assert set(filtered["terms"]["OnDemand"]) == {"a"}


def test_cloudfront_filter_keeps_eu_usagetypes():
    assert _cloudfront_eu_filter({"usagetype": "EU-DataTransfer-Out-Bytes"})
    assert not _cloudfront_eu_filter({"usagetype": "US-DataTransfer-Out-Bytes"})


def test_download_offers_writes_cached_files(tmp_path, monkeypatch):
    def fake_fetch(url: str):
        if "AmazonS3" in url:
            return {
                "formatVersion": "v1.0",
                "offerCode": "AmazonS3",
                "version": "1",
                "publicationDate": "2026-06-15T00:00:00Z",
                "products": {
                    "s3sku": {
                        "attributes": {
                            "regionCode": "eu-south-2",
                            "usagetype": "EUS2-TimedStorage-ByteHrs",
                        }
                    }
                },
                "terms": {"OnDemand": {"s3sku": {"offerTermCode": "x"}}},
            }
        return {
            "formatVersion": "v1.0",
            "offerCode": "AmazonCloudFront",
            "version": "1",
            "publicationDate": "2026-06-15T00:00:00Z",
            "products": {
                "cfsku": {"attributes": {"usagetype": "EU-Requests-Tier2-HTTPS"}},
                "ussku": {"attributes": {"usagetype": "US-Requests-Tier2-HTTPS"}},
            },
            "terms": {
                "OnDemand": {
                    "cfsku": {"offerTermCode": "x"},
                    "ussku": {"offerTermCode": "y"},
                }
            },
        }

    offers_dir = tmp_path / "aws-offers"
    monkeypatch.setattr("pricing.aws_offers.OFFERS_DIR", offers_dir)
    monkeypatch.setattr(
        "pricing.aws_offers.CACHED_FILES",
        {
            "amazon-s3-eu-south-2": offers_dir / "amazon-s3-eu-south-2.json",
            "amazon-cloudfront": offers_dir / "amazon-cloudfront.json",
            "amazon-cloudfront-eu": offers_dir / "amazon-cloudfront-eu.json",
            "manifest": offers_dir / "manifest.json",
        },
    )

    results = download_offers(fetch=fake_fetch)

    assert len(results) == 4
    assert (offers_dir / "amazon-s3-eu-south-2.json").is_file()
    assert (offers_dir / "amazon-cloudfront.json").is_file()
    assert (offers_dir / "manifest.json").is_file()

    s3_cached = json.loads((offers_dir / "amazon-s3-eu-south-2.json").read_text())
    assert set(s3_cached["products"]) == {"s3sku"}


def test_load_cached_offer_reads_repo_files():
    if not CACHED_FILES["manifest"].is_file():
        pytest.skip("cached AWS offers not present")

    manifest = load_manifest()
    assert "downloaded_at" in manifest
    assert "amazon-s3-eu-south-2" in manifest["files"]

    s3_offer = load_cached_offer("amazon-s3-eu-south-2")
    assert s3_offer["offerCode"] == "AmazonS3"
    assert OFFERS_DIR.is_dir()

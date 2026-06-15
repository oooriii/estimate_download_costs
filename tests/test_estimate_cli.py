from pathlib import Path

import pytest

from estimate_cli import cmd_estimate, parse_growth_rate, parse_storage_classes


def test_parse_growth_rate_accepts_percent():
    assert parse_growth_rate("10%") == 0.1


def test_parse_growth_rate_accepts_decimal():
    assert parse_growth_rate("0.15") == 0.15


def test_parse_storage_classes_accepts_comma_list():
    assert parse_storage_classes("STANDARD,STANDARD_IA") == (
        "STANDARD",
        "STANDARD_IA",
    )


def test_parse_storage_classes_rejects_unknown():
    with pytest.raises(ValueError, match="unknown storage class"):
        parse_storage_classes("STANDARD,INVALID")


def test_cmd_estimate_runs_on_sample_log(sample_log_file, tmp_path):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(
        Path("pricing/templates/eu-south-2.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "file": sample_log_file,
            "storage_gb": 1000.0,
            "items": 10_000,
            "growth": "10%",
            "pricing": pricing,
            "storage_class": "STANDARD",
            "compare_storage_classes": None,
        },
    )()
    assert cmd_estimate(args) == 0


def test_cmd_estimate_with_storage_class_comparison(sample_log_file, tmp_path):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(
        Path("pricing/templates/eu-south-2.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "file": sample_log_file,
            "storage_gb": 1000.0,
            "items": 10_000,
            "growth": "10%",
            "pricing": pricing,
            "storage_class": "STANDARD",
            "compare_storage_classes": "STANDARD,GLACIER_INSTANT",
        },
    )()
    assert cmd_estimate(args) == 0

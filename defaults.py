from __future__ import annotations

from pathlib import Path

from pricing.schema import STORAGE_CLASSES

DEFAULT_REPORT_OUTPUT_DIR = Path("reports")
DEFAULT_REPORT_PDF_NAME = "management-report.pdf"
DEFAULT_REPORT_CSV_NAME = "problematic-ips.csv"
DEFAULT_DEMAND_PDF_NAME = "file-demand.pdf"
DEFAULT_DEMAND_CSV_NAME = "top-files.csv"
DEFAULT_STATIC_FILES_CSV_NAME = "top-static-files.csv"
DEFAULT_STATIC_DAILY_CSV_NAME = "static-daily.csv"
DEFAULT_STATIC_SUMMARY_CSV_NAME = "static-summary.csv"
DEFAULT_COMPARE_STORAGE_CLASSES = ",".join(STORAGE_CLASSES)


def discover_geoip_db(search_dir: Path | None = None) -> Path | None:
    root = search_dir or Path.cwd()
    matches = sorted(root.glob("GeoLite2-Country*/GeoLite2-Country.mmdb"))
    if not matches:
        return None
    return matches[-1]


def default_report_paths(
    *,
    output_dir: Path = DEFAULT_REPORT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    return (
        output_dir / DEFAULT_REPORT_PDF_NAME,
        output_dir / DEFAULT_REPORT_CSV_NAME,
    )


def default_demand_paths(
    *,
    output_dir: Path = DEFAULT_REPORT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    return (
        output_dir / DEFAULT_DEMAND_PDF_NAME,
        output_dir / DEFAULT_DEMAND_CSV_NAME,
    )


def default_static_paths(
    *,
    output_dir: Path = DEFAULT_REPORT_OUTPUT_DIR,
) -> tuple[Path, Path, Path]:
    return (
        output_dir / DEFAULT_STATIC_FILES_CSV_NAME,
        output_dir / DEFAULT_STATIC_DAILY_CSV_NAME,
        output_dir / DEFAULT_STATIC_SUMMARY_CSV_NAME,
    )

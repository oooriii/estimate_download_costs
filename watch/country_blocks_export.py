from __future__ import annotations

import csv
from pathlib import Path

from watch.blocking import BlockRecommendation
from watch.country_blocks import CountryBlocksResolver


def write_country_cidrs_csv(
    path: Path,
    *,
    country_code: str,
    country_name: str,
    cidrs: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["country_code", "country_name", "cidr", "source"])
        for cidr in cidrs:
            writer.writerow(
                [country_code, country_name, cidr, "geolite2-country-blocks"]
            )


def export_flagged_country_cidrs(
    directory: Path,
    blocks: tuple[BlockRecommendation, ...],
    resolver: CountryBlocksResolver,
) -> list[Path]:
    """Write one CSV per flagged country with all official CIDR ranges."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    flagged_countries = {
        item.target
        for item in blocks
        if item.block_type == "country" and item.target
    }

    for country_code in sorted(flagged_countries):
        cidrs = resolver.blocks_for_country(country_code)
        if not cidrs:
            continue
        path = directory / f"{country_code.lower()}-official-cidrs.csv"
        write_country_cidrs_csv(
            path,
            country_code=country_code,
            country_name=resolver.country_name(country_code),
            cidrs=cidrs,
        )
        written.append(path)

    return written

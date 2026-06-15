from __future__ import annotations

import json
from pathlib import Path

from pricing.schema import (
    PricingConfig,
    PricingValidationError,
    collect_warnings,
    parse_pricing_config,
)


def load_pricing_config(path: Path) -> tuple[PricingConfig, list[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PricingValidationError(f"Invalid JSON in {path}: {exc}") from exc

    config = parse_pricing_config(raw)
    warnings = collect_warnings(config)
    return config, warnings


def save_pricing_config(path: Path, config: PricingConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

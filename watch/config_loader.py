from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from watch.config import (
    CountryBlocksSettings,
    SnapshotSettings,
    WatchConfig,
    WatchThresholds,
)


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required for --config. Install with: uv add pyyaml"
        ) from exc
    return yaml


def _as_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid float for '{field_name}': {value!r}") from exc


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer for '{field_name}': {value!r}") from exc


def _load_thresholds(raw: dict[str, Any] | None) -> WatchThresholds:
    if not raw:
        return WatchThresholds()

    thresholds = WatchThresholds()
    field_map = {
        "window_seconds": ("window_seconds", _as_float),
        "burst_window_seconds": ("burst_window_seconds", _as_float),
        "min_burst_rps": ("min_burst_rps", _as_float),
        "min_burst_requests": ("min_burst_requests", _as_int),
        "min_rps_per_ip": ("min_rps_per_ip", _as_float),
        "min_rps_per_subnet": ("min_rps_per_subnet", _as_float),
        "min_rps_per_country": ("min_rps_per_country", _as_float),
        "min_requests_per_ip": ("min_requests_per_ip", _as_int),
        "min_requests_per_subnet": ("min_requests_per_subnet", _as_int),
        "min_requests_per_country": ("min_requests_per_country", _as_int),
        "subnet_mask_v4": ("subnet_mask_v4", _as_int),
        "subnet_mask_v6": ("subnet_mask_v6", _as_int),
        "top_n": ("top_n", _as_int),
    }
    for key, (attr, caster) in field_map.items():
        if key in raw:
            setattr(thresholds, attr, caster(raw[key], key))
    return thresholds


def _load_snapshots(raw: dict[str, Any] | None) -> SnapshotSettings:
    if not raw:
        return SnapshotSettings()

    settings = SnapshotSettings()
    if "directory" in raw:
        settings.directory = str(raw["directory"])
    if "every_seconds" in raw:
        settings.every_seconds = _as_float(raw["every_seconds"], "every_seconds")
    return settings


def _load_country_blocks(raw: dict[str, Any] | None) -> CountryBlocksSettings:
    if not raw:
        return CountryBlocksSettings()

    settings = CountryBlocksSettings()
    if "locations" in raw and raw["locations"] is not None:
        settings.locations = str(raw["locations"])
    if "blocks_ipv4" in raw and raw["blocks_ipv4"] is not None:
        settings.blocks_ipv4 = str(raw["blocks_ipv4"])
    if "blocks_ipv6" in raw and raw["blocks_ipv6"] is not None:
        settings.blocks_ipv6 = str(raw["blocks_ipv6"])
    if "display_limit" in raw:
        settings.display_limit = _as_int(raw["display_limit"], "display_limit")
    if "export_with_snapshots" in raw:
        settings.export_with_snapshots = bool(raw["export_with_snapshots"])
    return settings


def load_watch_config(path: Path) -> WatchConfig:
    yaml = _require_yaml()
    if not path.is_file():
        raise FileNotFoundError(f"Config file '{path}' does not exist.")

    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if raw is None:
        return WatchConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"Config file '{path}' must contain a YAML mapping.")

    config = WatchConfig()
    if "geoip_db" in raw and raw["geoip_db"] is not None:
        config.geoip_db = str(raw["geoip_db"])
    if "refresh_seconds" in raw:
        config.refresh_seconds = _as_float(raw["refresh_seconds"], "refresh_seconds")
    if "live" in raw:
        config.live = bool(raw["live"])
    if "thresholds" in raw:
        if raw["thresholds"] is not None and not isinstance(raw["thresholds"], dict):
            raise ValueError("'thresholds' must be a mapping.")
        config.thresholds = _load_thresholds(raw.get("thresholds"))
    if "snapshots" in raw:
        if raw["snapshots"] is not None and not isinstance(raw["snapshots"], dict):
            raise ValueError("'snapshots' must be a mapping.")
        config.snapshots = _load_snapshots(raw.get("snapshots"))
    if "country_blocks" in raw:
        if raw["country_blocks"] is not None and not isinstance(
            raw["country_blocks"], dict
        ):
            raise ValueError("'country_blocks' must be a mapping.")
        config.country_blocks = _load_country_blocks(raw.get("country_blocks"))

    return config


def _cli_flag_provided(flag: str, argv: list[str] | None = None) -> bool:
    argv = argv if argv is not None else sys.argv[1:]
    return flag in argv or any(arg.startswith(f"{flag}=") for arg in argv)


def resolve_watch_runtime(
    args: Namespace,
    *,
    argv: list[str] | None = None,
) -> tuple[WatchConfig, WatchThresholds]:
    """Merge optional YAML config with CLI flags (CLI wins when provided)."""
    if args.config is not None:
        config = load_watch_config(args.config)
    else:
        config = WatchConfig()
    thresholds = config.thresholds

    if _cli_flag_provided("--geoip-db", argv) and args.geoip_db is not None:
        config.geoip_db = str(args.geoip_db)
    elif args.geoip_db is not None and config.geoip_db is None:
        config.geoip_db = str(args.geoip_db)

    if _cli_flag_provided("--refresh", argv):
        config.refresh_seconds = args.refresh
    if _cli_flag_provided("--live", argv) or _cli_flag_provided("--no-live", argv):
        config.live = args.live

    threshold_overrides = {
        "window_seconds": ("--window", args.window),
        "burst_window_seconds": ("--burst-window", args.burst_window),
        "min_burst_rps": ("--min-burst-rps", args.min_burst_rps),
        "min_burst_requests": ("--min-burst-req", args.min_burst_req),
        "min_rps_per_ip": ("--min-rps-ip", args.min_rps_ip),
        "min_rps_per_subnet": ("--min-rps-subnet", args.min_rps_subnet),
        "min_rps_per_country": ("--min-rps-country", args.min_rps_country),
        "min_requests_per_ip": ("--min-req-ip", args.min_req_ip),
        "min_requests_per_subnet": ("--min-req-subnet", args.min_req_subnet),
        "min_requests_per_country": ("--min-req-country", args.min_req_country),
        "subnet_mask_v4": ("--subnet-v4", args.subnet_v4),
        "top_n": ("--top", args.top),
    }
    for attr, (flag, value) in threshold_overrides.items():
        if _cli_flag_provided(flag, argv):
            setattr(thresholds, attr, value)

    if _cli_flag_provided("--snapshot-dir", argv) and args.snapshot_dir is not None:
        config.snapshots.directory = str(args.snapshot_dir)
    if _cli_flag_provided("--snapshot-every", argv):
        config.snapshots.every_seconds = args.snapshot_every

    country_blocks = config.country_blocks
    if _cli_flag_provided("--country-blocks-locations", argv):
        country_blocks.locations = (
            str(args.country_blocks_locations)
            if args.country_blocks_locations is not None
            else None
        )
    if _cli_flag_provided("--country-blocks-ipv4", argv):
        country_blocks.blocks_ipv4 = (
            str(args.country_blocks_ipv4)
            if args.country_blocks_ipv4 is not None
            else None
        )
    if _cli_flag_provided("--country-blocks-ipv6", argv):
        country_blocks.blocks_ipv6 = (
            str(args.country_blocks_ipv6)
            if args.country_blocks_ipv6 is not None
            else None
        )
    if _cli_flag_provided("--country-cidr-limit", argv):
        country_blocks.display_limit = args.country_cidr_limit

    return config, thresholds

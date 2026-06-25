from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WatchThresholds:
    """RPS-focused thresholds for flagging abusive traffic."""

    window_seconds: float = 300.0
    burst_window_seconds: float = 3.0
    min_burst_rps: float = 10.0
    min_burst_requests: int = 20
    min_rps_per_ip: float = 2.0
    min_rps_per_subnet: float = 5.0
    min_rps_per_country: float = 10.0
    min_requests_per_ip: int = 50
    min_requests_per_subnet: int = 100
    min_requests_per_country: int = 200
    subnet_mask_v4: int = 24
    subnet_mask_v6: int = 48
    top_n: int = 15


@dataclass
class SnapshotSettings:
    directory: str = "reports/live"
    every_seconds: float = 0.0


@dataclass
class CountryBlocksSettings:
    locations: str | None = None
    blocks_ipv4: str | None = None
    blocks_ipv6: str | None = None
    display_limit: int = 5
    export_with_snapshots: bool = True


@dataclass
class WatchConfig:
    geoip_db: str | None = None
    refresh_seconds: float = 2.0
    live: bool = True
    thresholds: WatchThresholds = field(default_factory=WatchThresholds)
    snapshots: SnapshotSettings = field(default_factory=SnapshotSettings)
    country_blocks: CountryBlocksSettings = field(default_factory=CountryBlocksSettings)

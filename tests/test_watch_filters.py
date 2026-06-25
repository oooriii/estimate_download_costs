from datetime import datetime

from events import LogEvent
from geo import StaticGeoIpResolver
from watch.aggregator import WatchAggregator
from watch.config import WatchThresholds
from watch.filters import WatchFilters


def _event(ip: str, *, ts: datetime) -> LogEvent:
    return LogEvent(
        source="access.log",
        kind="access",
        timestamp=ts,
        remote_host=ip,
        user_agent="Mozilla/5.0",
        path="/",
        status=200,
        bytes_sent=100,
        message=None,
    )


def test_filters_ignore_localhost():
    base = datetime(2026, 6, 25, 10, 0, 0)
    agg = WatchAggregator(
        thresholds=WatchThresholds(window_seconds=60, top_n=5),
        filters=WatchFilters(),
    )
    agg.ingest(_event("127.0.0.1", ts=base))
    agg.ingest(_event("8.8.8.8", ts=base))

    snapshot = agg.snapshot(now=base)
    assert snapshot.total_requests == 1
    assert agg.skipped_events == 1


def test_filters_whitelist_country_and_org_subnet():
    base = datetime(2026, 6, 25, 10, 0, 0)
    resolver = StaticGeoIpResolver(
        {
            "84.88.160.225": ("ES", "Spain"),
            "8.8.8.8": ("US", "United States"),
        }
    )
    filters = WatchFilters(
        whitelist_countries=("ES",),
        whitelist_cidrs=("84.88.0.0/16",),
    )
    agg = WatchAggregator(
        thresholds=WatchThresholds(window_seconds=60, top_n=5),
        geo_resolver=resolver,
        filters=filters,
    )
    agg.ingest(_event("84.88.160.225", ts=base))
    agg.ingest(_event("8.8.8.8", ts=base))

    snapshot = agg.snapshot(now=base)
    assert snapshot.total_requests == 1
    assert snapshot.ips[0].key == "8.8.8.8"
    assert agg.skipped_events == 1

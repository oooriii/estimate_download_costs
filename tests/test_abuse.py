import pytest

from abuse import is_abusive, parse_log, top_items
from bots import classify_user_agent
from geo import StaticGeoIpResolver


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("Mozilla/5.0 (compatible; Googlebot/2.1)", "bot"),
        ("CoreAutoPDFPretrainingBot (+contact URL)", "bot"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "human"),
        ("", "unknown"),
        ("-", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_classify_user_agent(user_agent, expected):
    assert classify_user_agent(user_agent) == expected


def test_is_abusive_flags_high_volume():
    assert is_abusive(
        records=100,
        bytes=10_000,
        total_records=1000,
        total_bytes=100_000,
        min_bytes_pct=5.0,
    )
    assert not is_abusive(
        records=1,
        bytes=100,
        total_records=1000,
        total_bytes=100_000,
        min_bytes_pct=5.0,
    )


def _log_line(ip: str, size: int, user_agent: str = "Mozilla/5.0") -> str:
    return (
        f"/var/log/apache2/access_ssl.log:{ip} - - "
        f'[15/Jun/2026:06:26:23 +0200] "GET /bitstream/handle/10256/x.pdf HTTP/1.1" '
        f'200 {size} "-" "{user_agent}"'
    )


def test_parse_log_aggregates_bots_ips_and_user_agents(tmp_path):
    log_file = tmp_path / "abuse.log"
    log_file.write_text(
        "\n".join(
            [
                _log_line("8.8.8.8", 1000, "Mozilla/5.0 (compatible; Googlebot/2.1)"),
                _log_line("8.8.8.8", 2000, "Mozilla/5.0 (compatible; Googlebot/2.1)"),
                _log_line("1.1.1.1", 500, "Mozilla/5.0"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    resolver = StaticGeoIpResolver(
        {
            "8.8.8.8": ("US", "United States"),
            "1.1.1.1": ("ES", "Spain"),
        }
    )

    result = parse_log(log_file, geo_resolver=resolver)

    assert result.stats.total_records == 3
    assert result.stats.total_bytes == 3500
    assert result.countries is not None
    assert {(item.country_code, item.bytes) for item in result.countries} == {
        ("US", 3000),
        ("ES", 500),
    }

    bot = {item.category: item for item in result.bot_traffic}
    assert bot["bot"].records == 2
    assert bot["bot"].bytes == 3000
    assert bot["human"].records == 1
    assert bot["human"].bytes == 500

    assert result.ips[0].remote_host == "8.8.8.8"
    assert result.ips[0].bytes == 3000
    assert result.ips[0].country_code == "US"
    assert "Googlebot" in result.ips[0].top_user_agent

    assert result.user_agents[0].records == 2
    assert result.user_agents[0].ip_count == 1


def test_top_items_limits_results():
    items = (1, 2, 3, 4)
    assert top_items(items, limit=2) == (1, 2)
    assert top_items(items, limit=0) == items

from geo import (
    StaticGeoIpResolver,
    classify_remote_host,
    country_for_line,
    parse_with_countries,
    top_countries,
)
from parser import LogLine


def test_classify_remote_host_handles_missing_and_local():
    assert classify_remote_host("-") == ("??", "Unknown")
    assert classify_remote_host("::1") == ("LOCAL", "Local / private")
    assert classify_remote_host("10.0.0.5") == ("LOCAL", "Local / private")


def test_country_for_line_uses_resolver_for_public_ip():
    line = LogLine(
        log_file="/var/log/apache2/access_ssl.log",
        remote_host="8.8.8.8",
        timestamp=__import__("datetime").datetime(
            2026, 6, 15, tzinfo=__import__("datetime").UTC
        ),
        method="GET",
        path="/bitstream/handle/10256/test.pdf",
        protocol="HTTP/1.1",
        status=200,
        bytes_sent=1000,
        referrer="-",
        user_agent="Mozilla/5.0",
    )
    resolver = StaticGeoIpResolver({"8.8.8.8": ("US", "United States")})

    assert country_for_line(line, resolver) == ("US", "United States")


def _log_line(ip: str, size: int) -> str:
    return (
        f"/var/log/apache2/access_ssl.log:{ip} - - "
        f'[15/Jun/2026:06:26:23 +0200] "GET /bitstream/handle/10256/x.pdf HTTP/1.1" '
        f'200 {size} "-" "Mozilla/5.0"'
    )


def test_parse_with_countries_aggregates_by_country(tmp_path):
    log_file = tmp_path / "geo.log"
    log_file.write_text(
        "\n".join(
            [
                _log_line("8.8.8.8", 1000),
                _log_line("1.1.1.1", 2000),
                _log_line("8.8.8.8", 500),
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

    stats, countries = parse_with_countries(log_file, resolver)

    assert stats.total_records == 3
    assert stats.total_bytes == 3500
    assert {(item.country_code, item.bytes) for item in countries} == {
        ("US", 1500),
        ("ES", 2000),
    }


def test_top_countries_groups_remainder():
    from geo import CountryTraffic

    countries = (
        CountryTraffic("C3", "Country 3", 1, 300),
        CountryTraffic("C2", "Country 2", 1, 200),
        CountryTraffic("C1", "Country 1", 1, 100),
    )

    top = top_countries(countries, limit=2)

    assert len(top) == 3
    assert top[0].country_code == "C3"
    assert top[1].country_code == "C2"
    assert top[2].country_code == "OTHER"

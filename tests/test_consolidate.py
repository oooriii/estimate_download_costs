from pathlib import Path

from geo import StaticGeoIpResolver
from watch.iptables_consolidate import (
    consolidate_ip_file,
    write_consolidation_csv,
    write_ipset_script,
)


def test_consolidate_ip_file_collapses_adjacent_ips(tmp_path: Path):
    ip_file = tmp_path / "blocked.txt"
    ip_file.write_text(
        "\n".join(
            [
                "10.0.0.1",
                "10.0.0.2",
                "10.0.0.3",
                "82.115.10.20",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    resolver = StaticGeoIpResolver(
        {
            "10.0.0.1": ("US", "United States"),
            "10.0.0.2": ("US", "United States"),
            "10.0.0.3": ("US", "United States"),
            "82.115.10.20": ("IS", "Iceland"),
        }
    )

    result = consolidate_ip_file(ip_file, geo_resolver=resolver)
    assert result.unique_ips == 4
    assert result.output_ranges < result.unique_ips

    us_ranges = [r for r in result.ranges if r.country_code == "US"]
    assert us_ranges
    assert any("/" in r.cidr for r in us_ranges)

    csv_path = tmp_path / "out.csv"
    write_consolidation_csv(csv_path, result)
    assert "cidr" in csv_path.read_text(encoding="utf-8")

    ipset_path = tmp_path / "blocked.sh"
    write_ipset_script(ipset_path, result)
    content = ipset_path.read_text(encoding="utf-8")
    assert "ipset add" in content

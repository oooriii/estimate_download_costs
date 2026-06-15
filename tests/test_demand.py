from demand import parse_file_demand, display_filename
from export_demand_csv import write_top_files_csv


def _log_line(path: str, size: int, ip: str = "1.2.3.4", user_agent: str = "Mozilla/5.0") -> str:
    return (
        f"/var/log/apache2/access.log:{ip} - - "
        f'[15/Jun/2026:06:26:23 +0200] "GET {path} HTTP/1.1" '
        f'200 {size} "-" "{user_agent}"'
    )


def test_parse_file_demand_groups_bitstream_url_variants(tmp_path):
    log_file = tmp_path / "demand.log"
    log_file.write_text(
        "\n".join(
            [
                _log_line(
                    "/bitstream/10256/12046/4/GibertSoteloPujolPayet_2015_Morphology.pdf",
                    1000,
                    ip="1.1.1.1",
                ),
                _log_line(
                    "/bitstream/handle/10256/12046/GibertSoteloPujolPayet_2015_Morphology.pdf?sequence=4",
                    2000,
                    ip="2.2.2.2",
                    user_agent="CoreAutoPDFPretrainingBot (+contact)",
                ),
                _log_line("/bitstream/10256/999/1/other.pdf", 500, ip="3.3.3.3"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = parse_file_demand(log_file)

    assert result.stats.total_records == 3
    assert result.stats.total_bytes == 3500
    assert len(result.files) == 2

    top = result.files[0]
    assert top.path.endswith("GibertSoteloPujolPayet_2015_Morphology.pdf")
    assert top.records == 2
    assert top.bytes == 3000
    assert top.unique_ips == 2
    assert top.bot_records == 1
    assert top.human_records == 1


def test_parse_file_demand_all_paths_includes_static_assets(tmp_path):
    log_file = tmp_path / "demand.log"
    log_file.write_text(
        "\n".join(
            [
                _log_line("/bitstream/10256/1/1/doc.pdf", 100),
                _log_line("/favicon.ico", 50),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bitstreams_only = parse_file_demand(log_file, bitstreams_only=True)
    all_paths = parse_file_demand(log_file, bitstreams_only=False)

    assert len(bitstreams_only.files) == 1
    assert len(all_paths.files) == 2
    assert all_paths.other_records == 1


def test_display_filename_falls_back_to_path_tail():
    from demand import FileDemand

    item = FileDemand(
        path="/bitstream/10256/1/1/example.pdf",
        item_id="10256/1",
        filename=None,
        records=1,
        bytes=100,
        unique_ips=1,
        bot_records=0,
        human_records=1,
    )
    assert display_filename(item) == "example.pdf"


def test_write_top_files_csv(tmp_path):
    from demand import FileDemand

    files = (
        FileDemand(
            path="/bitstream/10256/1/1/a.pdf",
            item_id="10256/1",
            filename="a.pdf",
            records=10,
            bytes=1000,
            unique_ips=3,
            bot_records=2,
            human_records=8,
        ),
    )
    csv_path = tmp_path / "top-files.csv"
    rows = write_top_files_csv(
        csv_path,
        files,
        total_records=10,
        total_bytes=1000,
    )

    assert rows == 1
    content = csv_path.read_text(encoding="utf-8")
    assert "a.pdf" in content
    assert "10256/1" in content

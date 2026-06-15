from parser import LogLine, parse_file


def test_from_line_parses_standard_log_line():
    line = (
        "/var/log/apache2/access_ssl_anubis.log:- - - [15/Jun/2026:06:26:23 +0200] "
        '"GET /bitstream/handle/10256/23347/document.pdf HTTP/1.1" '
        '200 11555603 "-" "Mozilla/5.0"'
    )
    log_line = LogLine.from_line(line)

    assert log_line is not None
    assert log_line.remote_host == "-"
    assert log_line.status == 200
    assert log_line.bytes_sent == 11555603
    assert log_line.path.endswith("document.pdf")


def test_from_line_parses_ipv6_host():
    line = (
        "/var/log/apache2/access_ssl.log.9.gz:::1 - - [06/Jun/2026:06:12:36 +0200] "
        '"GET /bitstream/handle/10256/20572/034821.pdf HTTP/1.1" '
        '200 947967 "-" "Mozilla/5.0"'
    )
    log_line = LogLine.from_line(line)

    assert log_line is not None
    assert log_line.remote_host == "::1"
    assert log_line.bytes_sent == 947967


def test_from_line_returns_none_for_invalid_line():
    assert LogLine.from_line("not a log line") is None


def test_parse_file_aggregates_stats(sample_log_file):
    stats = parse_file(sample_log_file)

    assert stats.total_records == 3
    assert stats.total_bytes == 11555603 + 947967 + 328118
    assert stats.min_date is not None
    assert stats.max_date is not None
    assert stats.observed_days >= 1.0

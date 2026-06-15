import pytest

SAMPLE_LOG_LINE = (
    '/var/log/apache2/access_ssl_anubis.log:- - - [15/Jun/2026:06:26:23 +0200] '
    '"GET /bitstream/handle/10256/23347/document.pdf?sequence=1 HTTP/1.1" '
    '200 11555603 "-" "Mozilla/5.0 (compatible; Googlebot/2.1)"'
)

SAMPLE_LOG_LINE_IPV6 = (
    '/var/log/apache2/access_ssl.log.9.gz:::1 - - [06/Jun/2026:06:12:36 +0200] '
    '"GET /bitstream/handle/10256/20572/034821.pdf?sequence=1 HTTP/1.1" '
    '200 947967 "-" "Mozilla/5.0"'
)

SAMPLE_LOG_LINE_BAD_UA = (
    '/var/log/apache2/access_ssl_anubis.log.10.gz:- - - [05/Jun/2026:02:09:21 +0200] '
    '"GET /bitstream/handle/10256/3594/Validated-Methodology.pdf?sequence=1 HTTP/1.1" '
    '200 328118 "-" "Not A;Brand\\";v=\\"99\\""'
)


@pytest.fixture
def sample_log_file(tmp_path):
    log_file = tmp_path / "sample.log"
    log_file.write_text(
        "\n".join([SAMPLE_LOG_LINE, SAMPLE_LOG_LINE_IPV6, SAMPLE_LOG_LINE_BAD_UA]) + "\n",
        encoding="utf-8",
    )
    return log_file

import re
from dataclasses import dataclass
from datetime import datetime

LOG_HEADER_RE = re.compile(
    r"^(?P<log_file>/var/log/apache2/\S+?):"
    r"(?P<remote_host>(?:\d{1,3}\.){3}\d{1,3}|::[\da-fA-F:]+|-) "
    r"- - \[(?P<timestamp>[^\]]+)\] "
    r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>[^"]+)" '
    r"(?P<status>\d+) (?P<bytes>\S+) "
    r'"(?P<referrer>[^"]*)" '
    r"(?P<user_agent>.+)$"
)

TIMESTAMP_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


@dataclass
class LogLine:
    """
    Línia de log Apache amb prefix de fitxer d'origen.

    Exemple:
    /var/log/apache2/access_ssl_anubis.log:- - - [15/Jun/2026:06:26:23 +0200] "GET /bitstream/handle/10256/23347/TobosoSalaElisabet_Annexos.pdf?sequence=2&isAllowed=y HTTP/1.1" 200 11555603 "-" "Mozilla/5.0 ..."
    """

    log_file: str
    remote_host: str
    timestamp: datetime
    method: str
    path: str
    protocol: str
    status: int
    bytes_sent: int
    referrer: str
    user_agent: str

    @classmethod
    def from_line(cls, line: str) -> "LogLine | None":
        match = LOG_HEADER_RE.match(line.strip())
        if not match:
            return None

        raw_bytes = match.group("bytes")
        user_agent = match.group("user_agent").strip()
        if user_agent.startswith('"') and user_agent.endswith('"'):
            user_agent = user_agent[1:-1]

        return cls(
            log_file=match.group("log_file"),
            remote_host=match.group("remote_host"),
            timestamp=datetime.strptime(match.group("timestamp"), TIMESTAMP_FORMAT),
            method=match.group("method"),
            path=match.group("path"),
            protocol=match.group("protocol"),
            status=int(match.group("status")),
            bytes_sent=0 if raw_bytes == "-" else int(raw_bytes),
            referrer=match.group("referrer"),
            user_agent=user_agent,
        )


@dataclass
class FileStats:
    min_date: datetime | None
    max_date: datetime | None
    total_records: int
    total_bytes: int


def parse_file(file_path: str) -> FileStats:
    """
    Parseja un fitxer en format de log Apache i retorna estadístiques agregades:
    data mínima i màxima, nombre total de registres i bytes descarregats.
    """
    min_date: datetime | None = None
    max_date: datetime | None = None
    total_records = 0
    total_bytes = 0

    with open(file_path, encoding="utf-8") as file:
        for line in file:
            log_line = LogLine.from_line(line)
            if log_line is None:
                continue

            total_records += 1
            total_bytes += log_line.bytes_sent

            if min_date is None or log_line.timestamp < min_date:
                min_date = log_line.timestamp
            if max_date is None or log_line.timestamp > max_date:
                max_date = log_line.timestamp

    return FileStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )


def main() -> None:
    stats = parse_file("20260615_downloads_ddocs.txt")
    print(f"Data mínima: {stats.min_date}")
    print(f"Data màxima: {stats.max_date}")
    print(f"Registres: {stats.total_records}")
    print(f"Bytes descarregats: {stats.total_bytes}")


if __name__ == "__main__":
    main()

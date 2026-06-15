import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.progress import Progress

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
    """Apache log line with a source log file prefix."""

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
class TrafficStats:
    min_date: datetime | None
    max_date: datetime | None
    total_records: int
    total_bytes: int

    @property
    def observed_days(self) -> float:
        if self.min_date is None or self.max_date is None:
            return 0.0
        return max((self.max_date - self.min_date).total_seconds() / 86400, 1.0)


# Backward-compatible alias used by earlier code and docs.
FileStats = TrafficStats


def iter_log_lines(file_path: Path) -> Iterator[LogLine]:
    with file_path.open(encoding="utf-8") as file:
        for line in file:
            log_line = LogLine.from_line(line)
            if log_line is not None:
                yield log_line


def parse_file(file_path: Path, progress: Progress | None = None) -> TrafficStats:
    """
    Parse an Apache log file and return aggregated traffic statistics:
    min/max date, total record count, and total bytes downloaded.
    """
    min_date: datetime | None = None
    max_date: datetime | None = None
    total_records = 0
    total_bytes = 0

    task_id = None
    if progress is not None:
        task_id = progress.add_task("Parsing log...", total=None)

    for log_line in iter_log_lines(file_path):
        total_records += 1
        total_bytes += log_line.bytes_sent

        if min_date is None or log_line.timestamp < min_date:
            min_date = log_line.timestamp
        if max_date is None or log_line.timestamp > max_date:
            max_date = log_line.timestamp

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=total_records)

    return TrafficStats(
        min_date=min_date,
        max_date=max_date,
        total_records=total_records,
        total_bytes=total_bytes,
    )

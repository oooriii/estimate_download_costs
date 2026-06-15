# estimate_download_costs

Tool for analyzing Apache log files of document downloads and computing aggregated statistics: date range, record count, and total transferred data volume.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recommended) or another dependency manager

## Installation

```bash
git clone git@github.com:oooriii/estimate_download_costs.git
cd estimate_download_costs
uv sync
```

## Usage

Pass the log file as an argument:

```bash
uv run python main.py 20260615_downloads_ddocs.txt
```

Help:

```bash
uv run python main.py --help
```

### Output

The tool displays a panel with:

| Field | Description |
|-------|-------------|
| **File** | Path to the analyzed file |
| **Min date** | Timestamp of the oldest record |
| **Max date** | Timestamp of the newest record |
| **Records** | Total number of valid parsed lines |
| **Bytes downloaded** | Sum of transferred bytes (human-readable: KB, MB, GB, etc.) |

While processing the file, a progress bar shows the number of records read.

## Expected log format

Each line follows the Apache *combined* format with a prefix indicating the source log file:

```
/var/log/apache2/access_ssl_anubis.log:- - - [15/Jun/2026:06:26:23 +0200] "GET /bitstream/handle/10256/23347/document.pdf?sequence=1 HTTP/1.1" 200 11555603 "-" "Mozilla/5.0 ..."
```

The parser extracts per line:

- source log file
- remote host (IP, IPv6, or `-`)
- date and time
- HTTP method, path, and protocol
- status code and transferred bytes
- referrer and user-agent

Lines that do not match this format are ignored.

## Library usage

```python
from pathlib import Path
from main import parse_file

stats = parse_file(Path("20260615_downloads_ddocs.txt"))
print(stats.min_date, stats.max_date, stats.total_records, stats.total_bytes)
```

## Data files

Input log files (`20260615_downloads_*.txt`) are excluded from version control via `.gitignore` due to their size. You need them locally to run the analysis.

## License

See [LICENSE](LICENSE).

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

### Analyze logs

```bash
uv run python main.py analyze 20260615_downloads_ddocs.txt
```

Traffic by country (requires a [MaxMind GeoLite2 Country](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data) database):

```bash
uv run python main.py analyze 20260615_downloads_ddocs.txt \
  --geoip-db /path/to/GeoLite2-Country.mmdb
```

The analyze command also reports bot vs human traffic (from user-agent heuristics), top clients by IP and user-agent (with abuse highlighting), and optionally traffic by country. Use `--abuse-top` and `--abuse-min-bytes-pct` to tune the abuse tables.

The country table shows records and bytes per country (top 15 plus an “Other” row). Use this to see how much traffic comes from outside your target region before configuring CloudFront geo restrictions.

Export an analysis PDF or a CSV of problematic IPs:

```bash
uv run python main.py analyze 20260615_downloads_ddocs.txt \
  --geoip-db /path/to/GeoLite2-Country.mmdb \
  --pdf reports/traffic-analysis.pdf \
  --csv-ips reports/problematic-ips.csv
```

### File demand report

Rank downloaded files (DSpace bitstreams) by records and bytes. URL variants such as `/bitstream/10256/…/file.pdf` and `/bitstream/handle/10256/…/file.pdf?sequence=N` are normalized to one path per document. The report shows a compact ranking by filename plus a separate path reference table.

By default writes:

- `reports/file-demand.pdf`
- `reports/top-files.csv`

```bash
uv run python main.py demand 20260615_downloads_ddocs_anubis.txt --top 25
```

| Flag | Description |
|------|-------------|
| `--top` | Top N files in terminal and exports (default: `25`) |
| `--all-paths` | Include non-bitstream paths (static assets, etc.) |
| `--output-dir` | Default directory for PDF and CSV (default: `reports/`) |
| `--pdf` / `--no-pdf` | PDF output path or skip PDF |
| `--csv` / `--no-csv` | CSV output path or skip CSV |

### Management report (PDF + CSV)

Combined report: traffic analysis, bots, countries, AWS cost estimate, and optional storage-class comparison. By default writes:

- `reports/management-report.pdf`
- `reports/problematic-ips.csv`

(`output-dir` defaults to `reports/`. Override paths with `--pdf`, `--csv-ips`, or `--output-dir`.)

```bash
uv run python main.py report 20260615_downloads_ddocs.txt \
  --storage-gb 5000 \
  --items 120000 \
  --geoip-db /path/to/GeoLite2-Country.mmdb \
  --compare-storage-classes \
  --forecast-years 3
```

| Flag | Description |
|------|-------------|
| `--storage-gb` | Total stored data volume in GB (required) |
| `--items` | Number of stored objects (required) |
| `--geoip-db` | GeoLite2-Country.mmdb for country breakdown (auto-detected in cwd if omitted) |
| `--output-dir` | Directory for PDF and CSV outputs (default: `reports/`) |
| `--pdf` | PDF output path (default: `<output-dir>/management-report.pdf`) |
| `--csv-ips` | CSV output path (default: `<output-dir>/problematic-ips.csv`) |
| `--no-csv-ips` | Skip CSV export |
| `--growth` | Annual growth rate (default: `10%`) |
| `--forecast-years` | Multi-year forecast in PDF (default: `0` = hide) |
| `--compare-storage-classes` | Include storage-class comparison (omit value to compare all) |
| `--show-calculations` | Print step-by-step formulas (quantity × unit price), AWS calculator style |
| `--abuse-top` | Top N IPs and user-agents in PDF (default: `15`) |
| `--abuse-min-bytes-pct` | Abuse threshold for CSV highlighting (default: `5`) |

Example for the current DUGi-Doc assetstore (202 GB, 26,768 items, 10% growth):

```bash
uv run python main.py report 20260615_downloads_ddocs_anubis.txt \
  --storage-gb 202 \
  --items 26768 \
  --geoip-db GeoLite2-Country_20260612/GeoLite2-Country.mmdb \
  --compare-storage-classes \
  --forecast-years 3
```

Cost estimate PDF only:

```bash
uv run python main.py estimate 20260615_downloads_ddocs.txt \
  --storage-gb 5000 \
  --items 120000 \
  --compare-storage-classes \
  --pdf reports/cost-estimate.pdf
```

Help:

```bash
uv run python main.py --help
uv run python main.py analyze --help
uv run python main.py report --help
```

### Estimate AWS costs

Project log traffic to a 30-day month and estimate S3 (and optional CloudFront) costs using a pricing config:

```bash
uv run python main.py estimate 20260615_downloads_ddocs.txt \
  --storage-gb 5000 \
  --items 120000
```

Options:

| Flag | Description |
|------|-------------|
| `--storage-gb` | Total stored data volume in GB (required) |
| `--items` | Number of stored objects, used for Intelligent-Tiering monitoring (required) |
| `--growth` | Annual growth rate applied to annual totals (default: `10%`) |
| `--projection-mode` | `simple` (30-day month, default) or `calendar` (days in log month) |
| `--forecast-years` | Multi-year forecast table for realistic S3 (0 = hide) |
| `--pricing` | Pricing JSON file (default: `pricing/eu-south-2.json`) |
| `--storage-class` | `STANDARD`, `STANDARD_IA`, `INTELLIGENT_TIERING`, or `GLACIER_INSTANT` (detailed estimate) |
| `--compare-storage-classes` | Compare S3 direct costs across classes (comma-separated, or omit value to compare all) |
| `--show-calculations` | Print step-by-step formulas (quantity × unit price), AWS calculator style |

Compare storage classes (egress and GET costs are the same; only storage and IT monitoring differ):

```bash
uv run python main.py estimate 20260615_downloads_ddocs.txt \
  --storage-gb 5000 \
  --items 120000 \
  --compare-storage-classes STANDARD,INTELLIGENT_TIERING,GLACIER_INSTANT
```

```bash
uv run python main.py estimate 20260615_downloads_ddocs.txt \
  --storage-gb 5000 \
  --items 120000 \
  --projection-mode calendar \
  --forecast-years 3
```

The report shows:

- **Realistic S3 direct** — tiered egress, observed traffic scaled to 30 days
- **Realistic S3 + CloudFront** — recommended cache hit ratio from pricing config
- **Conservative worst case** — +20% traffic, first-tier egress only, CloudFront at 0% cache hit; picks the higher annual total between S3 direct and CloudFront
- **Storage class comparison** (with `--compare-storage-classes`) — side-by-side monthly/annual totals for S3 direct

Amounts are shown in USD with indicative EUR (from the pricing file's `display.usd_eur_rate`). This is an estimate, not a billing guarantee.

**Monthly vs annual:** each scenario prints both a **monthly** table (current run rate) and an **annual** table (monthly × 12, with growth applied to annual lines when `--growth` is set). The multi-year forecast table shows **annual** totals per year, not monthly.

EUR conversion is controlled in `pricing/eu-south-2.json` under `display.show_eur` and `display.usd_eur_rate` (no extra CLI flag). Terminal output uses `€`; PDF uses `USD … (EUR …)` for compatibility.

```bash
uv run python main.py estimate --help
```

### Pricing configuration

### Generate pricing from cached AWS offers

```bash
uv run python main.py pricing generate --output pricing/eu-south-2.json --force
```

This reads `pricing/aws-offers/` and writes a validated `eu-south-2.json`. Use `--download` to refresh AWS offers first:

```bash
uv run python main.py pricing generate --download --output pricing/eu-south-2.json --force
```

To regenerate the reference template:

```bash
uv run python main.py pricing generate --output pricing/templates/eu-south-2.json --force
```

Interactive wizard (manual overrides):

```bash
uv run python main.py pricing init --output pricing/eu-south-2.json
```

Show or validate an existing file:

```bash
uv run python main.py pricing show pricing/eu-south-2.json
uv run python main.py pricing validate pricing/eu-south-2.json
```

Refresh cached AWS public price list files (stored under `pricing/aws-offers/`):

```bash
uv run python main.py pricing download-offers
```

Cached files:

| File | Contents |
|------|----------|
| `amazon-s3-eu-south-2.json` | S3 offer filtered to region `eu-south-2` (~150 KB) |
| `amazon-cloudfront.json` | Full CloudFront offer (~220 KB) |
| `amazon-cloudfront-eu.json` | CloudFront SKUs with `EU-*` usage types |
| `manifest.json` | Download timestamp and source URLs |

### Automated quarterly refresh (GitHub Actions)

The workflow [`.github/workflows/update-aws-pricing.yml`](.github/workflows/update-aws-pricing.yml) runs on the **1st of January, April, July, and October** (06:00 UTC). It:

1. Runs the test suite
2. Downloads fresh AWS offer files into `pricing/aws-offers/`
3. Regenerates `pricing/templates/eu-south-2.json`
4. Opens a pull request **only if** AWS prices changed

It does **not** modify `pricing/eu-south-2.json` (your local/working config). After merging a pricing PR, refresh your config manually if needed:

```bash
uv run python main.py pricing generate --output pricing/eu-south-2.json --force
```

You can also trigger the workflow manually from the GitHub Actions tab (**Run workflow**).

AWS prices are stored in **USD** (how AWS bills). The wizard also asks for a **USD/EUR rate** to display indicative EUR amounts. The default rate is `0.92` and triggers a warning — update it to match current exchange rates.

A starter template is available at `pricing/templates/eu-south-2.json` for reference; use `pricing init` to create a validated config file. Use `pricing download-offers` to refresh the cached AWS JSON files when AWS updates prices.

### Output

The tool displays a panel with:

| Field | Description |
|-------|-------------|
| **File** | Path to the analyzed file |
| **Min date** | Timestamp of the oldest record |
| **Max date** | Timestamp of the newest record |
| **Observed days** | Length of the sampled period |
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
from parser import parse_file

stats = parse_file(Path("20260615_downloads_ddocs.txt"))
print(stats.min_date, stats.max_date, stats.total_records, stats.total_bytes)
```

## Generating input files

Input files are extracted from Apache access logs on the server. Example for DUGi-Doc (`ddocs`):

```bash
sudo zgrep '/bitstream/handle/10256' /var/log/apache2/access_ssl* \
  | grep 'HTTP/1.1" 200' > /home/pencaire/20260615_downloads_ddocs.txt
```

The command does two things:

1. **`zgrep '/bitstream/handle/10256'`** — selects log lines for DSpace bitstream downloads (handles starting with `10256`).
2. **`grep 'HTTP/1.1" 200'`** — keeps only successful responses (HTTP 200).

The HTTP 200 filter is intentional: we only count **real, completed downloads**. Redirects (3xx), missing files (404), server errors (5xx), and other non-success responses are excluded so byte totals reflect actual transferred data.

`zgrep` is used so both plain and rotated/compressed logs (`access_ssl.log`, `access_ssl.log.1.gz`, etc.) are searched.

Adapt the handle prefix and output filename for other repositories (e.g. `10256.2` for DFE).

## Data files

Input log files (`20260615_downloads_*.txt`) are excluded from version control via `.gitignore` for two reasons:

- **Data protection** — logs contain user IP addresses and other request metadata that should not be published in a repository.
- **File size** — extracted log files can be very large.

Generate them on the server (see above) and keep them local to run the analysis.

## Tests and CI

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

GitHub Actions runs the same checks on every push and pull request to `main` (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## License

See [LICENSE](LICENSE).

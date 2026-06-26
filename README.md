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

### Live abuse monitor (`watch`)

Monitor Apache **access** and **error** logs in real time to detect abusive
request rates (RPS) and suggest blocks by country, subnet, or IP. Designed to
protect server stability rather than analyze download bytes.

**Live via SSH + tail** (recommended):

```bash
ssh user@server 'sudo tail -F /var/log/apache2/access_ssl.log /var/log/apache2/error_ssl.log' \
  | uv run python main.py watch --config watch.example.yaml
```

Or use the helper script:

```bash
chmod +x scripts/remote-watch.sh
GEOIP_DB=GeoLite2-Country_20260612/GeoLite2-Country.mmdb ./scripts/remote-watch.sh user@server
```

**Batch analysis** (local files or stdin):

```bash
uv run python main.py watch --no-live access_ssl.log error_ssl.log \
  --config watch.example.yaml \
  --export-csv reports/blocks.csv
```

**YAML config** (`watch.example.yaml`):

```yaml
geoip_db: GeoLite2-Country_20260612/GeoLite2-Country.mmdb
thresholds:
  burst_window_seconds: 3      # group rapid requests as one incident
  min_burst_rps: 10            # flag short bursts even if sustained RPS is low
  min_rps_per_country: 10
snapshots:
  directory: reports/live
  every_seconds: 900           # periodic JSON + CSV during live monitoring
```

| Flag | Description |
|------|-------------|
| `--config` | YAML config file (CLI flags override when provided) |
| `--geoip-db` | GeoLite2-Country.mmdb for country breakdown and block suggestions |
| `--live` / `--no-live` | Rich live dashboard (default: live) |
| `--window` | Sliding window in seconds for RPS (default: `300`) |
| `--burst-window` | Group requests within N seconds as one burst (default: `3`) |
| `--min-burst-rps` | Flag actor when a burst reaches this RPS (default: `10`) |
| `--min-rps-country` | Flag country at or above this sustained RPS (default: `10`) |
| `--min-rps-subnet` | Flag /24 subnet at or above this sustained RPS (default: `5`) |
| `--min-rps-ip` | Flag IP at or above this sustained RPS (default: `2`) |
| `--snapshot-dir` / `--snapshot-every` | Periodic snapshot export during live mode |
| `--export-csv` / `--export-json` | Export block recommendations (batch mode) |
| `--export-country-cidrs DIR` | Export all official GeoLite2 CIDRs for flagged countries |

The live dashboard shows top IPs (with peak burst RPS), user-agents, countries, and **suggested blocks**.
Burst detection helps catch short scraping floods that might not yet dominate the full window.

**Blocking strategies:**

| Type | Source | Use for |
|------|--------|---------|
| `country` | Traffic + GeoIP | CloudFront geo restriction, WAF |
| `country_cidr` | GeoLite2-Country-Blocks CSV | Firewall, ipset, mod_security |
| `subnet` | Observed /24 clusters in logs | Targeted blocks for active abuse |
| `ip` | Individual abusive clients | Surgical block |

Official country CIDR files are auto-detected next to `--geoip-db` when
`GeoLite2-Country-Locations-en.csv` and `GeoLite2-Country-Blocks-IPv4.csv` exist
(download the full GeoLite2 Country CSV archive from MaxMind, not just the `.mmdb`).
The dashboard shows the largest official prefixes; use `--export-country-cidrs` or
snapshots to export the complete list for firewall rules.

**Filters and whitelist** (ignore localhost, trust your users):

```yaml
filters:
  ignore_ips: [127.0.0.1, ::1]
  ignore_private: true
  whitelist_countries: [ES, LOCAL]   # never flag Spain / private nets
  whitelist_cidrs: [84.88.0.0/16]  # UDG campus range
```

CLI equivalents: `--ignore-ip`, `--whitelist-country ES`, `--whitelist-cidr 84.88.0.0/16`.
Filtered traffic is excluded from abuse metrics so bot floods are easier to see.

**Large log analysis** (recommended when the server is under stress):

```bash
# On the server: extract recent lines only (low overhead)
ssh user@server 'sudo tail -n 1000000 \
  /var/log/apache2/anubis_access.log \
  /var/log/apache2/anubis_error.log' > logs_stress.txt

# Analyze locally (memory stays bounded by --window)
uv run python main.py watch --no-live logs_stress.txt \
  --config watch.example.yaml \
  --export-csv reports/blocks.csv \
  --export-country-cidrs reports/country-cidrs
```

`tail -n 1000000` is preferable to `cat` on multi-GB rotated logs: you get the
most recent traffic without reading the entire history. Use `grep` first if you
need a specific hour.

**Consolidate iptables IP lists** (reduce kernel memory):

```bash
uv run python main.py consolidate blocked_ips.txt \
  --geoip-db GeoLite2-Country_20260612/GeoLite2-Country.mmdb \
  --csv reports/consolidated.csv \
  --ipset reports/blocked-abuse.sh
```

Collapses thousands of per-IP rules into fewer CIDR ranges, grouped by country.
Review the output before applying firewall changes.

**Note on spoofed bots:** user-agent strings like `Applebot` can be faked.
Treat UA as a hint; prefer IP reputation, GeoIP country, request patterns
(`/discover`, `/search-filter`), and burst RPS when deciding blocks.

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

### Static asset demand report

Analyze CSS, JS, fonts, and image requests extracted from full access logs. The parser streams line-by-line (safe for multi-GB files) and groups paths by category: theme assets, bitstream images (covers/thumbnails), and other static files.

**DSpace version:** theme path rules (`/static/`, `/handle/static/`, `loadJQuery.js`, discovery CSS/JS, etc.) are written for **DSpace 5.x**, matching DUGi Fons Especials and DUGi-Doc. Classification for **DSpace 7.x–10.x** (different theme and asset URLs) is future work; counts and byte totals still work for any log extract.

By default writes:

- `reports/top-static-files.csv`
- `reports/static-daily.csv`
- `reports/static-summary.csv`

```bash
uv run python main.py static 20260615_static_dfe.txt --top 50
```

| Flag | Description |
|------|-------------|
| `--top` | Top N paths in terminal and files CSV (default: `25`) |
| `--projection-mode` | `simple` (30-day month, default) or `calendar` |
| `--output-dir` | Default directory for CSV exports (default: `reports/`) |
| `--csv` / `--csv-daily` / `--csv-summary` | Override export paths |
| `--no-csv` | Skip CSV exports |

See [Generating input files](#generating-input-files) for how to extract static-asset logs on the server.

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

Input files are extracted from Apache access logs on the server.

### Bitstream downloads

Example for DUGi-Doc (`ddocs`):

```bash
sudo zgrep '/bitstream/handle/10256' /var/log/apache2/access_ssl* \
  | grep 'HTTP/1.1" 200' > /home/pencaire/20260615_downloads_ddocs.txt
```

Example for DUGi Fons Especials (`dfe`):

```bash
sudo zgrep '/bitstream/handle/10256.2' /var/log/apache2/access_ssl.log* \
  | grep 'HTTP/1.1" 200' > /home/pencaire/20260615_downloads_dfe.txt
```

The command does two things:

1. **`zgrep '/bitstream/handle/…'`** — selects log lines for DSpace bitstream downloads (adapt the handle prefix per repository).
2. **`grep 'HTTP/1.1" 200'`** — keeps only successful responses (HTTP 200).

The HTTP 200 filter is intentional: we only count **real, completed downloads**. Redirects (3xx), missing files (404), server errors (5xx), and other non-success responses are excluded so byte totals reflect actual transferred data.

`zgrep` is used so both plain and rotated/compressed logs (`access_ssl.log`, `access_ssl.log.1.gz`, etc.) are searched.

### Static assets (CSS, JS, fonts, images)

For the `static` command, extract lines whose URL ends in a static file extension:

```bash
STATIC_RE='\.(css|js|woff2?|ttf|eot|svg|png|jpe?g|gif|webp|ico) HTTP'
```

DUGi-Doc (`ddocs`) — traffic behind Anubis:

```bash
sudo zgrep -E "$STATIC_RE" /var/log/apache2/anubis_access.log* \
  | grep 'HTTP/1.1" 200' > /home/pencaire/20260615_static_ddocs.txt
```

DUGi Fons Especials (`dfe`) — direct SSL access log:

```bash
sudo zgrep -E "$STATIC_RE" /var/log/apache2/access_ssl.log* \
  | grep 'HTTP/1.1" 200' > /home/pencaire/20260615_static_dfe.txt
```

This captures theme files (`/static/`, `/themes/`, `loadJQuery.js`, etc.) and bitstream images (covers, thumbnails) served with an image extension. It does **not** include HTML pages or PDF bitstreams.

## Data files

Input log files (`20260615_downloads_*.txt`, `20260615_static_*.txt`) are excluded from version control via `.gitignore` for two reasons:

- **Data protection** — logs contain user IP addresses and other request metadata that should not be published in a repository.
- **File size** — extracted log files can be very large.

Generate them on the server (see above) and keep them local to run the analysis.

### Server stability runbook

For production triage (vmstat, iostat, swap, Tomcat/Solr/Postgres, firewall
relief strategy) and how it connects to `watch` / `ruleset`, see
[docs/diagnostic-runbook.md](docs/diagnostic-runbook.md).

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

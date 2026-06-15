from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from abuse import AnalysisResult, top_items
from bots import BOT_CATEGORY_LABELS
from cost_model import EstimateResult, ScenarioCosts
from geo import top_countries
from parser import TrafficStats
from pricing.schema import PricingConfig
from projection import ProjectedTraffic, yearly_forecast_totals
from report import format_bytes


@dataclass(frozen=True)
class EstimatePdfContext:
    pricing: PricingConfig
    traffic: ProjectedTraffic
    result: EstimateResult
    selected_storage_class: str
    growth_rate: float
    forecast_years: int
    storage_comparisons: tuple[ScenarioCosts, ...] | None = None
    pricing_warnings: tuple[str, ...] = ()


def write_analyze_pdf(
    path: Path,
    *,
    log_file: Path,
    result: AnalysisResult,
    abuse_top: int = 15,
    countries_top: int = 15,
    abuse_min_bytes_pct: float = 5.0,
    title: str = "Log traffic analysis",
) -> None:
    builder = _PdfBuilder(title=title, subtitle=str(log_file))
    _add_traffic_summary(builder, log_file, result.stats)
    _add_bot_section(builder, result, abuse_min_bytes_pct)
    _add_ip_section(builder, result, abuse_top, abuse_min_bytes_pct)
    _add_user_agent_section(builder, result, abuse_top, abuse_min_bytes_pct)
    if result.countries is not None:
        _add_country_section(builder, result, countries_top)
    builder.save(path)


def write_estimate_pdf(
    path: Path,
    *,
    log_file: Path,
    context: EstimatePdfContext,
    title: str = "AWS cost estimate",
) -> None:
    builder = _PdfBuilder(title=title, subtitle=str(log_file))
    _add_estimate_sections(builder, log_file, context)
    builder.save(path)


def write_combined_pdf(
    path: Path,
    *,
    log_file: Path,
    result: AnalysisResult,
    estimate: EstimatePdfContext,
    abuse_top: int = 15,
    countries_top: int = 15,
    abuse_min_bytes_pct: float = 5.0,
    title: str = "S3 download study report",
) -> None:
    builder = _PdfBuilder(title=title, subtitle=str(log_file))
    _add_traffic_summary(builder, log_file, result.stats)
    _add_bot_section(builder, result, abuse_min_bytes_pct)
    _add_ip_section(builder, result, abuse_top, abuse_min_bytes_pct)
    _add_user_agent_section(builder, result, abuse_top, abuse_min_bytes_pct)
    if result.countries is not None:
        _add_country_section(builder, result, countries_top)
    builder.add_page_break()
    _add_estimate_sections(builder, log_file, estimate)
    builder.save(path)


class _PdfBuilder:
    def __init__(self, *, title: str, subtitle: str) -> None:
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=15)
        self.pdf.add_page()
        self.pdf.set_font("Helvetica", "B", 16)
        self.pdf.cell(0, 10, _pdf_text(title), new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("Helvetica", "", 10)
        self.pdf.set_text_color(80, 80, 80)
        self.pdf.cell(0, 6, _pdf_text(subtitle), new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_text_color(0, 0, 0)
        generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
        self.pdf.cell(
            0,
            6,
            _pdf_text(f"Generated: {generated}"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.pdf.ln(4)

    def add_page_break(self) -> None:
        self.pdf.add_page()

    def add_section(self, title: str, *, subtitle: str | None = None) -> None:
        self.pdf.ln(3)
        self.pdf.set_font("Helvetica", "B", 12)
        self.pdf.cell(0, 8, _pdf_text(title), new_x="LMARGIN", new_y="NEXT")
        if subtitle:
            self.pdf.set_font("Helvetica", "", 9)
            self.pdf.set_text_color(80, 80, 80)
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.multi_cell(self.pdf.epw, 5, _pdf_text(subtitle))
            self.pdf.set_text_color(0, 0, 0)

    def add_key_values(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.pdf.set_font("Helvetica", "", 10)
        for label, value in rows:
            self.pdf.set_font("Helvetica", "B", 10)
            self.pdf.cell(52, 6, _pdf_text(f"{label}:"), new_x="RIGHT")
            self.pdf.set_font("Helvetica", "", 10)
            self.pdf.cell(0, 6, _pdf_text(value), new_x="LMARGIN", new_y="NEXT")

    def add_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        *,
        col_widths: tuple[float, ...] | None = None,
    ) -> None:
        if not rows:
            self.pdf.set_font("Helvetica", "I", 10)
            self.pdf.cell(0, 6, _pdf_text("No data."), new_x="LMARGIN", new_y="NEXT")
            return

        widths = col_widths or _auto_col_widths(headers, rows)
        line_height = 5
        self.pdf.set_font("Helvetica", "B", 9)
        for header, width in zip(headers, widths, strict=True):
            self.pdf.cell(width, line_height, _pdf_text(header), border=1)
        self.pdf.ln(line_height)

        self.pdf.set_font("Helvetica", "", 8)
        for row in rows:
            if self.pdf.get_y() > 270:
                self.pdf.add_page()
                self.pdf.set_font("Helvetica", "B", 9)
                for header, width in zip(headers, widths, strict=True):
                    self.pdf.cell(width, line_height, _pdf_text(header), border=1)
                self.pdf.ln(line_height)
                self.pdf.set_font("Helvetica", "", 8)
            for value, width in zip(row, widths, strict=True):
                self.pdf.cell(width, line_height, _pdf_text(value), border=1)
            self.pdf.ln(line_height)

    def add_bullets(self, items: tuple[str, ...]) -> None:
        self.pdf.set_font("Helvetica", "", 9)
        for item in items:
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.multi_cell(self.pdf.epw, 5, _pdf_text(f"- {item}"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.pdf.output(str(path))


def _add_traffic_summary(
    builder: _PdfBuilder,
    log_file: Path,
    stats: TrafficStats,
) -> None:
    builder.add_section("Study results")
    builder.add_key_values(
        (
            ("Log file", str(log_file)),
            ("Min date", str(stats.min_date) if stats.min_date else "-"),
            ("Max date", str(stats.max_date) if stats.max_date else "-"),
            ("Observed days", f"{stats.observed_days:.1f}"),
            ("Records", f"{stats.total_records:,}"),
            ("Bytes downloaded", format_bytes(stats.total_bytes)),
        )
    )


def _add_bot_section(
    builder: _PdfBuilder,
    result: AnalysisResult,
    abuse_min_bytes_pct: float,
) -> None:
    stats = result.stats
    builder.add_section(
        "Bot vs human traffic",
        subtitle=(
            "Based on user-agent heuristics. "
            f"Clients above {abuse_min_bytes_pct:.0f}% of traffic "
            "are flagged as abusive."
        ),
    )
    rows = tuple(
        (
            BOT_CATEGORY_LABELS[item.category],
            f"{item.records:,}",
            _share(item.records, stats.total_records),
            format_bytes(item.bytes),
            _share(item.bytes, stats.total_bytes),
        )
        for item in result.bot_traffic
    )
    builder.add_table(
        ("Category", "Records", "% rec.", "Bytes", "% bytes"),
        rows,
        col_widths=(35, 28, 22, 35, 22),
    )


def _add_ip_section(
    builder: _PdfBuilder,
    result: AnalysisResult,
    abuse_top: int,
    abuse_min_bytes_pct: float,
) -> None:
    stats = result.stats
    builder.add_section(
        "Top clients by IP",
        subtitle=f"Top {abuse_top} IPs by bytes transferred.",
    )
    rows = tuple(
        (
            item.remote_host,
            _country_label(item.country_name, item.country_code),
            f"{item.records:,}",
            format_bytes(item.bytes),
            _share(item.bytes, stats.total_bytes),
            _truncate(item.top_user_agent, 40),
        )
        for item in top_items(result.ips, limit=abuse_top)
    )
    builder.add_table(
        ("IP", "Country", "Records", "Bytes", "% bytes", "Top user-agent"),
        rows,
        col_widths=(32, 30, 22, 28, 20, 58),
    )


def _add_user_agent_section(
    builder: _PdfBuilder,
    result: AnalysisResult,
    abuse_top: int,
    abuse_min_bytes_pct: float,
) -> None:
    stats = result.stats
    builder.add_section(
        "Top clients by user-agent",
        subtitle=f"Top {abuse_top} user-agents by bytes transferred.",
    )
    rows = tuple(
        (
            _truncate(item.user_agent, 55),
            f"{item.records:,}",
            format_bytes(item.bytes),
            _share(item.bytes, stats.total_bytes),
            str(item.ip_count),
        )
        for item in top_items(result.user_agents, limit=abuse_top)
    )
    builder.add_table(
        ("User-agent", "Records", "Bytes", "% bytes", "IPs"),
        rows,
        col_widths=(85, 22, 28, 20, 15),
    )


def _add_country_section(
    builder: _PdfBuilder,
    result: AnalysisResult,
    countries_top: int,
) -> None:
    stats = result.stats
    builder.add_section(
        "Traffic by country",
        subtitle="Based on client IP geolocation (GeoLite2).",
    )
    rows = tuple(
        (
            item.country_name,
            item.country_code,
            f"{item.records:,}",
            _share(item.records, stats.total_records),
            format_bytes(item.bytes),
            _share(item.bytes, stats.total_bytes),
        )
        for item in top_countries(result.countries or (), limit=countries_top)
    )
    builder.add_table(
        ("Country", "Code", "Records", "% rec.", "Bytes", "% bytes"),
        rows,
        col_widths=(50, 16, 24, 20, 30, 20),
    )


def _add_estimate_sections(
    builder: _PdfBuilder,
    log_file: Path,
    context: EstimatePdfContext,
) -> None:
    pricing = context.pricing
    traffic = context.traffic
    result = context.result
    rate = pricing.display.usd_eur_rate

    builder.add_section("Estimate disclaimer")
    bullets = [
        (
            f"Observed period: {traffic.observed_days:.1f} days "
            f"(scaled x{traffic.scale_factor:.2f} -> "
            f"{traffic.target_month_days:.0f}-day month, {traffic.mode} mode)."
        ),
        f"Region: {pricing.region} | Pricing date: {pricing.effective_date}",
        f"FX: 1 USD = {rate:.4f} EUR (indicative only).",
        f"Detailed estimate storage class: {context.selected_storage_class}",
    ]
    if context.growth_rate > 0:
        bullets.append(
            f"Annual totals assume {context.growth_rate:.0%}/yr growth "
            "on all cost lines."
        )
    bullets.append("AWS prices change. This is not a billing guarantee.")
    builder.add_bullets(tuple(bullets))

    builder.add_section("Projected traffic (realistic)")
    builder.add_key_values(
        (
            ("Log file", str(log_file)),
            ("Projected monthly requests", f"{traffic.monthly_requests:,.0f}"),
            ("Projected monthly transfer", format_bytes(int(traffic.monthly_bytes))),
            (
                "Conservative traffic buffer",
                f"+{traffic.safety_margin:.0%} on worst-case scenario only",
            ),
        )
    )

    _add_scenario_table(builder, result.realistic_s3, pricing, "monthly")
    _add_scenario_table(builder, result.realistic_s3, pricing, "annual")
    if result.realistic_cloudfront is not None:
        _add_scenario_table(builder, result.realistic_cloudfront, pricing, "monthly")
        _add_scenario_table(builder, result.realistic_cloudfront, pricing, "annual")
    _add_scenario_table(builder, result.conservative, pricing, "monthly")
    _add_scenario_table(builder, result.conservative, pricing, "annual")

    if context.storage_comparisons:
        _add_storage_comparison(builder, context, pricing)

    if context.forecast_years > 0:
        _add_forecast(builder, context, pricing)

    if context.pricing_warnings:
        builder.add_section("Pricing warnings")
        builder.add_bullets(tuple(context.pricing_warnings))


def _add_scenario_table(
    builder: _PdfBuilder,
    scenario: ScenarioCosts,
    pricing: PricingConfig,
    period: str,
) -> None:
    rate = pricing.display.usd_eur_rate
    show_eur = pricing.display.show_eur
    lines = scenario.monthly if period == "monthly" else scenario.annual
    total = scenario.monthly_total if period == "monthly" else scenario.annual_total
    rows = tuple(
        (line.label, _format_money_pdf(line.usd, rate, show_eur)) for line in lines
    ) + (("Total", _format_money_pdf(total, rate, show_eur)),)
    builder.add_section(f"{scenario.name} - {period}")
    builder.add_table(("Component", "Cost"), rows, col_widths=(120, 70))


def _add_storage_comparison(
    builder: _PdfBuilder,
    context: EstimatePdfContext,
    pricing: PricingConfig,
) -> None:
    comparisons = context.storage_comparisons
    if not comparisons:
        return
    rate = pricing.display.usd_eur_rate
    show_eur = pricing.display.show_eur
    sorted_rows = sorted(comparisons, key=lambda item: item.monthly_total)
    cheapest = sorted_rows[0].monthly_total
    builder.add_section(
        "Storage class comparison (S3 direct, realistic)",
        subtitle=(
            "GET and egress costs are identical across classes; "
            "only storage and Intelligent-Tiering monitoring differ."
        ),
    )
    rows = tuple(
        (
            scenario.name
            + (
                " (selected)"
                if scenario.name == context.selected_storage_class
                else ""
            ),
            _format_money_pdf(scenario.monthly_total, rate, show_eur),
            _format_money_pdf(scenario.annual_total, rate, show_eur),
            "-"
            if scenario.monthly_total == cheapest
            else _format_money_pdf(
                scenario.monthly_total - cheapest, rate, show_eur
            ),
        )
        for scenario in sorted_rows
    )
    builder.add_table(
        ("Storage class", "Monthly", "Annual", "Delta vs cheapest/mo"),
        rows,
        col_widths=(55, 40, 40, 45),
    )


def _add_forecast(
    builder: _PdfBuilder,
    context: EstimatePdfContext,
    pricing: PricingConfig,
) -> None:
    forecast = yearly_forecast_totals(
        context.result.realistic_s3.annual_total,
        context.growth_rate,
        context.forecast_years,
    )
    if not forecast:
        return
    rate = pricing.display.usd_eur_rate
    show_eur = pricing.display.show_eur
    builder.add_section(
        "Multi-year forecast (realistic S3 direct)",
        subtitle=(
            f"Year 1 uses growth-adjusted annual totals "
            f"({context.growth_rate:.0%}/yr); later years compound on year 1."
        ),
    )
    rows = tuple(
        (str(year), _format_money_pdf(total, rate, show_eur))
        for year, total in forecast
    )
    builder.add_table(("Year", "Annual total (S3 direct)"), rows, col_widths=(30, 80))


def _country_label(name: str | None, code: str | None) -> str:
    if not name:
        return "-"
    if code and code not in {"??", "LOCAL"}:
        return f"{name} ({code})"
    return name


def _share(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{100.0 * part / total:.1f}%"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _auto_col_widths(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
) -> tuple[float, ...]:
    usable = 190.0
    weight = tuple(
        max(len(header), *(len(row[idx]) for row in rows))
        for idx, header in enumerate(headers)
    )
    total = sum(weight) or 1
    return tuple(usable * w / total for w in weight)


def _format_money_pdf(usd: float, rate: float, show_eur: bool = True) -> str:
    if abs(usd) < 0.01:
        if show_eur:
            return f"USD {usd:,.4f} (EUR {usd * rate:,.4f})"
        return f"USD {usd:,.4f}"
    if show_eur:
        return f"USD {usd:,.2f} (EUR {usd * rate:,.2f})"
    return f"USD {usd:,.2f}"


def _pdf_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("latin-1", errors="replace").decode("latin-1")

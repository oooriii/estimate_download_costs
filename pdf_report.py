from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from abuse import AnalysisResult, top_items
from bots import BOT_CATEGORY_LABELS
from cost_model import EstimateResult, ScenarioCosts
from demand import FileDemandResult, display_filename
from estimate_report import scenario_calculation_lines
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
    show_calculations: bool = False


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


def write_demand_pdf(
    path: Path,
    *,
    log_file: Path,
    result: FileDemandResult,
    top: int = 25,
    bitstreams_only: bool = True,
    title: str = "File demand report",
) -> None:
    builder = _PdfBuilder(title=title, subtitle=str(log_file))
    _add_demand_sections(
        builder,
        log_file=log_file,
        result=result,
        top=top,
        bitstreams_only=bitstreams_only,
    )
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
            self.pdf.set_x(self.pdf.l_margin)

    def add_key_values(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.pdf.set_font("Helvetica", "", 10)
        for label, value in rows:
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.set_font("Helvetica", "B", 10)
            self.pdf.cell(52, 6, _pdf_text(f"{label}:"), new_x=XPos.RIGHT)
            self.pdf.set_font("Helvetica", "", 10)
            self.pdf.cell(
                0,
                6,
                _pdf_text(value),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    def add_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        *,
        col_widths: tuple[float, ...] | None = None,
    ) -> None:
        if not rows:
            self.pdf.set_font("Helvetica", "I", 10)
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.cell(
                0,
                6,
                _pdf_text("No data."),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            return

        widths = _fit_col_widths(
            col_widths or _auto_col_widths(headers, rows, self.pdf.epw),
            self.pdf.epw,
        )
        line_height = 5
        self._draw_table_row(headers, widths, line_height, style="B", size=9)

        self.pdf.set_font("Helvetica", "", 8)
        for row in rows:
            if self.pdf.get_y() > 270:
                self.pdf.add_page()
                self._draw_table_row(headers, widths, line_height, style="B", size=9)
                self.pdf.set_font("Helvetica", "", 8)
            self._draw_table_row(row, widths, line_height, style="", size=8)

    def _draw_table_row(
        self,
        cells: tuple[str, ...],
        widths: tuple[float, ...],
        line_height: float,
        *,
        style: str,
        size: int,
    ) -> None:
        self.pdf.set_x(self.pdf.l_margin)
        self.pdf.set_font("Helvetica", style, size)
        last_index = len(cells) - 1
        for index, (value, width) in enumerate(zip(cells, widths, strict=True)):
            self.pdf.cell(
                width,
                line_height,
                _pdf_text(value),
                border=1,
                new_x=XPos.LMARGIN if index == last_index else XPos.RIGHT,
                new_y=YPos.NEXT if index == last_index else YPos.TOP,
            )

    def add_bullets(self, items: tuple[str, ...]) -> None:
        self.pdf.set_font("Helvetica", "", 9)
        for item in items:
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.multi_cell(self.pdf.epw, 5, _pdf_text(f"- {item}"))

    def add_calculation_block(self, lines: tuple[str, ...]) -> None:
        self.pdf.set_font("Helvetica", "", 8)
        for line in lines:
            if self.pdf.get_y() > 275:
                self.pdf.add_page()
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.multi_cell(self.pdf.epw, 4.5, _pdf_text(line))
        self.pdf.ln(2)

    def add_numbered_path_reference(
        self,
        items: tuple[tuple[str, str, str], ...],
    ) -> None:
        """Render #, filename, and wrapped full path entries."""
        self.pdf.set_font("Helvetica", "", 8)
        for rank, filename, path in items:
            if self.pdf.get_y() > 265:
                self.pdf.add_page()
            self.pdf.set_x(self.pdf.l_margin)
            self.pdf.set_font("Helvetica", "B", 8)
            self.pdf.cell(
                0,
                5,
                _pdf_text(f"{rank}. {filename}"),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.pdf.set_font("Helvetica", "", 8)
            self.pdf.set_x(self.pdf.l_margin + 4)
            self.pdf.multi_cell(self.pdf.epw - 4, 4.5, _pdf_text(path))
            self.pdf.ln(1)

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


def _format_share_pct(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{100.0 * part / total:.1f}%"


def _truncate_pdf(text: str, limit: int = 72) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _add_demand_sections(
    builder: _PdfBuilder,
    *,
    log_file: Path,
    result: FileDemandResult,
    top: int,
    bitstreams_only: bool,
) -> None:
    stats = result.stats
    _add_traffic_summary(builder, log_file, stats)

    builder.add_section("File demand summary")
    summary_rows: list[tuple[str, str]] = [
        ("Unique paths", f"{len(result.files):,}"),
        ("Bitstream downloads", f"{result.bitstream_records:,}"),
    ]
    if not bitstreams_only:
        summary_rows.append(("Other paths", f"{result.other_records:,}"))
    builder.add_key_values(tuple(summary_rows))

    rows = top_items(result.files, limit=top)
    builder.add_section(
        "Top demanded files",
        subtitle=(
            "Ranked by bytes transferred. See the path reference section below."
        ),
    )
    table_rows = tuple(
        (
            str(index),
            _truncate_pdf(display_filename(item), limit=36),
            item.item_id or "-",
            f"{item.records:,}",
            _format_share_pct(item.records, stats.total_records),
            format_bytes(item.bytes),
            _format_share_pct(item.bytes, stats.total_bytes),
            str(item.unique_ips),
            f"{item.bot_records:,}",
        )
        for index, item in enumerate(rows, start=1)
    )
    builder.add_table(
        (
            "#",
            "Filename",
            "Item",
            "Records",
            "% rec.",
            "Bytes",
            "% bytes",
            "IPs",
            "Bot rec.",
        ),
        table_rows,
        col_widths=(8, 40, 24, 14, 12, 18, 12, 10, 12),
    )

    builder.add_section(
        "File paths (reference)",
        subtitle="Full normalized paths for the ranked files above.",
    )
    builder.add_numbered_path_reference(
        tuple(
            (str(index), display_filename(item), item.path)
            for index, item in enumerate(rows, start=1)
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
    if context.show_calculations:
        _add_scenario_calculations(
            builder,
            result.realistic_s3,
            period="monthly",
            growth_rate=context.growth_rate,
        )
    _add_scenario_table(builder, result.realistic_s3, pricing, "annual")
    if context.show_calculations:
        _add_scenario_calculations(
            builder,
            result.realistic_s3,
            period="annual",
            growth_rate=context.growth_rate,
        )
    if result.realistic_cloudfront is not None:
        _add_scenario_table(builder, result.realistic_cloudfront, pricing, "monthly")
        _add_scenario_table(builder, result.realistic_cloudfront, pricing, "annual")
    _add_scenario_table(builder, result.conservative, pricing, "monthly")
    _add_scenario_table(builder, result.conservative, pricing, "annual")

    if context.storage_comparisons:
        _add_storage_comparison(builder, context, pricing)
        if context.show_calculations:
            _add_storage_comparison_calculations(builder, context)

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


def _add_scenario_calculations(
    builder: _PdfBuilder,
    scenario: ScenarioCosts,
    *,
    period: str,
    growth_rate: float,
) -> None:
    builder.add_section(f"Show calculations — {scenario.name} ({period})")
    builder.add_calculation_block(
        scenario_calculation_lines(
            scenario,
            period=period,
            growth_rate=growth_rate,
        )
    )


def _add_storage_comparison_calculations(
    builder: _PdfBuilder,
    context: EstimatePdfContext,
) -> None:
    comparisons = context.storage_comparisons
    if not comparisons:
        return
    lines: list[str] = [
        "Storage and monitoring only; GET and egress are identical across classes.",
    ]
    for scenario in sorted(comparisons, key=lambda item: item.monthly_total):
        lines.append(f"{scenario.name}:")
        for line in scenario.monthly:
            if line.label not in {"Storage", "Intelligent-Tiering monitoring"}:
                continue
            for step in line.calculation:
                lines.append(f"  {step}")
    builder.add_section("Show calculations — storage class comparison")
    builder.add_calculation_block(tuple(lines))


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
    max_width: float,
) -> tuple[float, ...]:
    weight = tuple(
        max(len(header), *(len(row[idx]) for row in rows))
        for idx, header in enumerate(headers)
    )
    total = sum(weight) or 1
    return tuple(max_width * w / total for w in weight)


def _fit_col_widths(
    widths: tuple[float, ...],
    max_width: float,
) -> tuple[float, ...]:
    total = sum(widths)
    if total <= max_width:
        return widths
    scale = max_width / total
    return tuple(width * scale for width in widths)


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

"""Renders a submit_report payload (see orchestrator.SUBMIT_REPORT_TOOL) into a
self-contained Tailwind-styled HTML dashboard, following
skills/financial-report-formatting/SKILL.md's content
conventions and the dataviz skill's chart/color rules.

Chart colors reuse the validated reference palette verbatim (dataviz skill,
references/palette.md) -- slot 1 blue for the single-series price line, and the
fixed status pair (good/critical) for up/down deltas. Since no new categorical
ordering is introduced, no re-validation via validate_palette.js is required.
"""

import html
import json
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent

# -- validated palette (dataviz skill references/palette.md), reused as-is --
SERIES_BLUE = {"light": "#2a78d6", "dark": "#3987e5"}
GOOD = {"light": "#006300", "dark": "#0ca30c"}
CRITICAL = {"light": "#d03b3b", "dark": "#e66767"}


# ---------------------------------------------------------------------------
# Formatting helpers -- implement skills/financial-report-formatting/SKILL.md's table conventions.
# ---------------------------------------------------------------------------

def fmt_currency(value, abbreviate=False):
    if value is None:
        return "N/A"
    if abbreviate:
        abs_v = abs(value)
        if abs_v >= 1e12:
            return f"${value / 1e12:.2f}T"
        if abs_v >= 1e9:
            return f"${value / 1e9:.2f}B"
        if abs_v >= 1e6:
            return f"${value / 1e6:.2f}M"
    return f"${value:,.2f}"


def fmt_pct(value, signed=False):
    """For values already expressed as percentage points, e.g. surprise_pct == 4.9 (not 0.049)."""
    if value is None:
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.1f}%"


def fmt_ratio_as_pct(value, signed=False):
    """For fundamentals fields expressed as fractions (0.166 == 16.6%)."""
    if value is None:
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.1f}%"


def fmt_number(value):
    if value is None:
        return "N/A"
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs_v >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:,.0f}"


def fmt_plain(value, decimals=2):
    return "N/A" if value is None else f"{value:.{decimals}f}"


def fmt_date(value):
    return value or "N/A"


# ---------------------------------------------------------------------------
# Price history line chart -- hand-built inline SVG, per dataviz skill:
# sequential single hue, 2px line, 4px rounded/8px endpoint marker, hairline
# solid gridlines, hover crosshair + tooltip, direct end-label (no legend
# needed for a single series).
# ---------------------------------------------------------------------------

def _nice_ticks(min_v, max_v, count=4):
    if min_v == max_v:
        return [min_v]
    raw_step = (max_v - min_v) / count
    magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    residual = raw_step / magnitude
    step = 10 * magnitude if residual > 5 else 5 * magnitude if residual > 2 else 2 * magnitude if residual > 1 else magnitude
    start = math.floor(min_v / step) * step
    ticks = []
    v = start
    while v <= max_v + step:
        ticks.append(round(v, 2))
        v += step
    return ticks


def render_line_chart(price_history: list[dict]) -> str:
    if not price_history:
        return '<p class="text-sm text-[color:var(--text-muted)]">No price history available.</p>'

    W, H = 760, 220
    PAD_L, PAD_B, PAD_T = 56, 28, 12
    plot_w = W - PAD_L - 8
    plot_h = H - PAD_T - PAD_B

    closes = [p["close"] for p in price_history]
    min_c, max_c = min(closes), max(closes)
    ticks = _nice_ticks(min_c, max_c, 4)
    y_min, y_max = min(ticks[0], min_c), max(ticks[-1], max_c)

    def x_of(i):
        n = len(price_history)
        return PAD_L + (i / (n - 1) if n > 1 else 0) * plot_w

    def y_of(close):
        span = (y_max - y_min) or 1
        return PAD_T + (1 - (close - y_min) / span) * plot_h

    points = [(x_of(i), y_of(p["close"])) for i, p in enumerate(price_history)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_d = path_d + f" L {points[-1][0]:.1f},{PAD_T + plot_h:.1f} L {points[0][0]:.1f},{PAD_T + plot_h:.1f} Z"

    gridlines = "\n".join(
        f'<line x1="{PAD_L}" y1="{y_of(t):.1f}" x2="{W - 8}" y2="{y_of(t):.1f}" '
        f'class="stroke-[color:var(--gridline)]" stroke-width="1"/>\n'
        f'<text x="{PAD_L - 8}" y="{y_of(t) + 4:.1f}" text-anchor="end" '
        f'class="fill-[color:var(--text-muted)] text-[10px]">{html.escape(fmt_currency(t))}</text>'
        for t in ticks
        if y_min <= t <= y_max
    )

    n = len(price_history)
    label_idxs = sorted(set([0, n // 2, n - 1])) if n > 1 else [0]

    def _anchor(i):
        if i == label_idxs[0]:
            return "start"
        if i == label_idxs[-1]:
            return "end"
        return "middle"

    x_labels = "\n".join(
        f'<text x="{x_of(i):.1f}" y="{H - 6}" text-anchor="{_anchor(i)}" '
        f'class="fill-[color:var(--text-muted)] text-[10px]">{html.escape(price_history[i]["date"])}</text>'
        for i in label_idxs
    )

    last_x, last_y = points[-1]
    last_close = price_history[-1]["close"]

    chart_data = json.dumps(
        [{"x": round(x, 1), "y": round(y, 1), "date": p["date"], "close": p["close"]} for (x, y), p in zip(points, price_history)]
    )

    return f"""
<div class="relative" style="--series-1: {SERIES_BLUE['light']};">
  <style>
    @media (prefers-color-scheme: dark) {{
      :root:where(:not([data-theme="light"])) .price-chart-root {{ --series-1: {SERIES_BLUE['dark']}; }}
    }}
    :root[data-theme="dark"] .price-chart-root {{ --series-1: {SERIES_BLUE['dark']}; }}
  </style>
  <div class="price-chart-root">
    <svg viewBox="0 0 {W} {H}" class="w-full h-auto" id="price-chart-svg">
      {gridlines}
      <line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - 8}" y2="{PAD_T + plot_h}"
            class="stroke-[color:var(--axis-baseline)]" stroke-width="1"/>
      <path d="{area_d}" fill="var(--series-1)" opacity="0.10" stroke="none"/>
      <path d="{path_d}" fill="none" stroke="var(--series-1)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" fill="var(--series-1)"
              stroke="var(--surface-1)" stroke-width="2"/>
      <text x="{last_x - 6:.1f}" y="{last_y - 10:.1f}" text-anchor="end"
            class="fill-[color:var(--text-primary)] text-[11px] font-semibold">{html.escape(fmt_currency(last_close))}</text>
      {x_labels}
      <line id="price-chart-crosshair" x1="0" y1="{PAD_T}" x2="0" y2="{PAD_T + plot_h}"
            class="stroke-[color:var(--text-muted)]" stroke-width="1" style="display:none"/>
      <circle id="price-chart-hover-dot" r="4" fill="var(--series-1)" stroke="var(--surface-1)"
              stroke-width="2" style="display:none"/>
      <rect x="{PAD_L}" y="{PAD_T}" width="{plot_w:.1f}" height="{plot_h:.1f}" fill="transparent"
            id="price-chart-overlay"/>
    </svg>
    <div id="price-chart-tooltip"
         class="hidden absolute pointer-events-none rounded-md border px-2 py-1 text-xs shadow-sm"
         style="background: var(--surface-1); border-color: var(--border); color: var(--text-primary);">
    </div>
  </div>
</div>
<script>
(function() {{
  const data = {chart_data};
  const svg = document.getElementById('price-chart-svg');
  const overlay = document.getElementById('price-chart-overlay');
  const crosshair = document.getElementById('price-chart-crosshair');
  const dot = document.getElementById('price-chart-hover-dot');
  const tooltip = document.getElementById('price-chart-tooltip');
  if (!svg || !overlay) return;

  function nearestPoint(mouseX) {{
    let best = data[0], bestDist = Infinity;
    for (const d of data) {{
      const dist = Math.abs(d.x - mouseX);
      if (dist < bestDist) {{ bestDist = dist; best = d; }}
    }}
    return best;
  }}

  function handleMove(evt) {{
    const rect = svg.getBoundingClientRect();
    const scaleX = svg.viewBox.baseVal.width / rect.width;
    const mouseX = (evt.clientX - rect.left) * scaleX;
    const point = nearestPoint(mouseX);

    crosshair.setAttribute('x1', point.x);
    crosshair.setAttribute('x2', point.x);
    crosshair.style.display = '';
    dot.setAttribute('cx', point.x);
    dot.setAttribute('cy', point.y);
    dot.style.display = '';

    const dateEl = document.createElement('div');
    dateEl.textContent = point.date;
    dateEl.style.color = 'var(--text-muted)';
    const closeEl = document.createElement('div');
    closeEl.textContent = '$' + point.close.toFixed(2);
    closeEl.style.fontWeight = '600';

    tooltip.textContent = '';
    tooltip.appendChild(closeEl);
    tooltip.appendChild(dateEl);
    tooltip.classList.remove('hidden');

    const scaleFactor = rect.width / svg.viewBox.baseVal.width;
    tooltip.style.left = (point.x * scaleFactor + 12) + 'px';
    tooltip.style.top = (point.y * scaleFactor - 8) + 'px';
  }}

  function handleLeave() {{
    crosshair.style.display = 'none';
    dot.style.display = 'none';
    tooltip.classList.add('hidden');
  }}

  overlay.addEventListener('mousemove', handleMove);
  overlay.addEventListener('mouseleave', handleLeave);
}})();
</script>
"""


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

FUNDAMENTALS_FIELDS = [
    ("trailing_pe", "Trailing P/E", lambda v: fmt_plain(v)),
    ("forward_pe", "Forward P/E", lambda v: fmt_plain(v)),
    ("price_to_book", "Price / Book", lambda v: fmt_plain(v)),
    ("profit_margins", "Profit Margin", lambda v: fmt_ratio_as_pct(v)),
    ("return_on_equity", "Return on Equity", lambda v: fmt_ratio_as_pct(v)),
    ("revenue_growth", "Revenue Growth", lambda v: fmt_ratio_as_pct(v, signed=True)),
    ("trailing_eps", "Trailing EPS", lambda v: fmt_currency(v)),
]


def _delta_info(price, previous_close):
    if price is None or previous_close is None:
        return None
    change = price - previous_close
    change_pct = (change / previous_close * 100) if previous_close else None
    return {
        "change": change,
        "change_pct": change_pct,
        "is_up": change >= 0,
        "text": f"{'+' if change >= 0 else ''}{fmt_currency(change)} ({'+' if change >= 0 else ''}{change_pct:.1f}%)"
        if change_pct is not None
        else fmt_currency(change),
    }


def build_context(report: dict) -> dict:
    price_snapshot = report.get("price_snapshot") or {}
    fundamentals = report.get("fundamentals") or {}
    price_history = report.get("price_history") or []

    fundamentals_rows = [
        {"label": label, "value": fmt(fundamentals.get(key))} for key, label, fmt in FUNDAMENTALS_FIELDS
    ]

    earnings_rows = [
        {
            "date": fmt_date(q.get("earnings_date")),
            "estimate": fmt_currency(q.get("eps_estimate")) if q.get("eps_estimate") is not None else "N/A",
            "actual": fmt_currency(q.get("eps_actual")),
            "surprise": fmt_pct(q.get("surprise_pct"), signed=True) if q.get("surprise_pct") is not None else "N/A",
            "is_up": (q.get("surprise_pct") or 0) >= 0,
        }
        for q in (report.get("earnings_surprise") or [])
    ]

    filings_rows = [
        {"form": f.get("form", "N/A"), "date": fmt_date(f.get("filed_date")), "url": f.get("url")}
        for f in (report.get("recent_filings") or [])
    ]

    sources_rows = [
        {"tool": s.get("tool", ""), "args": ", ".join(f"{k}={v}" for k, v in (s.get("args") or {}).items())}
        for s in (report.get("sources") or [])
    ]

    delta = _delta_info(price_snapshot.get("price"), price_snapshot.get("previous_close"))

    kpis = [
        {
            "label": "Price",
            "value": fmt_currency(price_snapshot.get("price")),
            "delta": delta["text"] if delta else None,
            "is_up": delta["is_up"] if delta else None,
        },
        {
            "label": "Day range",
            "value": f"{fmt_currency(price_snapshot.get('day_low'))} – {fmt_currency(price_snapshot.get('day_high'))}"
            if price_snapshot.get("day_low") is not None
            else "N/A",
        },
        {"label": "Volume", "value": fmt_number(price_snapshot.get("volume"))},
        {"label": "Market cap", "value": fmt_currency(price_snapshot.get("market_cap"), abbreviate=True)},
    ]

    return {
        "header": report.get("header") or {},
        "executive_summary": report.get("executive_summary") or "",
        "kpis": kpis,
        "chart_html": render_line_chart(price_history),
        "fundamentals_rows": fundamentals_rows,
        "earnings_rows": earnings_rows,
        "filings_rows": filings_rows,
        "filing_excerpts": report.get("filing_excerpts") or [],
        "sources_rows": sources_rows,
        "good": GOOD,
        "critical": CRITICAL,
        "series_blue": SERIES_BLUE,
    }


def render_report(report: dict, output_path: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(ROOT)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("template.html")
    html_out = template.render(**build_context(report))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_out, encoding="utf-8")
    return output_path

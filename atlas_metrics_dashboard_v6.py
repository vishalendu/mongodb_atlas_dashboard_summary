#!/usr/bin/env python3
"""
Atlas Metrics Dashboard
------------------------
Usage:
    python atlas_metrics_dashboard.py metrics.json
    python atlas_metrics_dashboard.py metrics.json --output my_dashboard.html
    python atlas_metrics_dashboard.py metrics.json --open   # auto-open in browser

    # clip to a time window (HH:MM or HH:MM:SS, matched against UTC timestamps)
    python atlas_metrics_dashboard.py metrics.json --since 13:45 --until 14:15
    python atlas_metrics_dashboard.py metrics.json --since 13:45:30 --until 14:00:00

    # clip using full datetime (useful when data spans midnight)
    python atlas_metrics_dashboard.py metrics.json --since "2026-06-22 13:45" --until "2026-06-22 14:15"

    # last N minutes of the data
    python atlas_metrics_dashboard.py metrics.json --last 30
    python atlas_metrics_dashboard.py metrics.json --last 60 --output last-hour.html
"""

import json
import sys
import argparse
import math
import html
from datetime import datetime, timezone
from pathlib import Path

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.io as pio
except ImportError:
    print("plotly not found. Install with: pip install plotly")
    sys.exit(1)


# ── Colour palette ──────────────────────────────────────────────────────────
COLORS = [
    "#00ED64", "#1F6FEB", "#F5A623", "#E74C3C", "#9B59B6",
    "#1ABC9C", "#F39C12", "#3498DB", "#E67E22", "#2ECC71",
    "#E91E63", "#00BCD4", "#FF5722", "#8BC34A", "#795548",
]

# ── Chart group definitions (category → chart_key → display title) ──────────
CHART_GROUPS = [
    {
        "title": "Operations",
        "charts": [
            ("status", "fixed-opcounters-chart",       "Opcounters"),
            ("status", "document-metrics",             "Document Metrics"),
            ("status", "operations",                   "Operations"),
            ("status", "fixed-opcounters-repl-chart",  "Opcounters – Replication"),
        ],
    },
    {
        "title": "Connections & Cursors",
        "charts": [
            ("status", "fixed-connections-chart",      "Connections"),
            ("status", "fixed-connection-rate-chart",  "Connection Rate"),
            ("status", "fixed-cursors-chart",          "Cursors"),
        ],
    },
    {
        "title": "Query Performance",
        "charts": [
            ("status", "query-executor",                          "Query Executor"),
            ("status", "query-targeting",                         "Query Targeting"),
            ("status", "fixed-avg-operation-execution-times-chart","Avg Operation Time (ms)"),
            ("status", "query-sort-chart",                        "Query Sort"),
        ],
    },
    {
        "title": "CPU",
        "charts": [
            ("process", "normalized-process-cpu",    "Process CPU (Normalized) %"),
            ("process", "normalized-system-cpu",     "System CPU (Normalized) %"),
            ("process", "system-cpu",                "System CPU %"),
            ("process", "process-cpu",               "Process CPU %"),
            ("process", "max-normalized-system-cpu", "Max Normalized System CPU %"),
            ("process", "max-system-cpu",            "Max System CPU %"),
            ("process", "max-process-cpu",           "Max Process CPU %"),
            ("otherCpu", "fts-process-cpu",          "Search Process CPU %"),
            ("otherCpu", "fts-normalized-process-cpu","Search Process CPU (Normalized) %"),
        ],
    },
    {
        "title": "Memory",
        "charts": [
            ("status",    "fixed-mem-chart",     "Memory (MB)"),
            ("systemMem", "system-memory",        "System Memory"),
            ("systemMem", "max-system-memory",    "Max System Memory"),
            ("systemMem", "swap-usage",           "Swap Usage"),
        ],
    },
    {
        "title": "WiredTiger Cache",
        "charts": [
            ("status", "fixed-wtCache-usage-chart",       "WT Cache Usage"),
            ("status", "fixed-wtCache-activity-chart",    "WT Cache Activity"),
            ("status", "fixed-wtCache-cache-ratio-chart", "WT Cache Ratio"),
            ("status", "fixed-wtTickets-available-chart", "WT Tickets Available"),
        ],
    },
    {
        "title": "Disk",
        "charts": [
            ("disk", "disk-data-iops-chart",              "Disk IOPS"),
            ("disk", "max-disk-data-iops-chart",          "Max Disk IOPS"),
            ("disk", "disk-data-latency-chart",           "Disk Latency (ms)"),
            ("disk", "disk-data-throughput-chart",        "Disk Throughput"),
            ("disk", "disk-data-queue-depth-chart",       "Disk Queue Depth"),
            ("disk", "max-disk-data-queue-depth-chart",   "Max Disk Queue Depth"),
            ("disk", "disk-data-space-free-chart",        "Disk Space Free"),
            ("disk", "disk-data-space-used-chart",        "Disk Space Used"),
            ("disk", "disk-data-space-percent-free-chart","Disk Space Free %"),
            ("otherDisk", "fts-disk-space-used-chart",    "Search Disk Space Used"),
        ],
    },
    {
        "title": "Network",
        "charts": [
            ("process", "system-network",        "Network (bytes)"),
            ("status",  "fixed-network-chart",   "Network – Status"),
        ],
    },
    {
        "title": "Oplog",
        "charts": [
            ("status", "oplog-master-time-chart",              "Oplog Window (hours)"),
            ("status", "oplog-rate-chart",                     "Oplog Rate (GB/hr)"),
            ("status", "oplog-secondary-lag-master-time-chart","Replication Lag (sec)"),
        ],
    },
    {
        "title": "Locks & Asserts",
        "charts": [
            ("status", "fixed-global-lock-current-queue-chart", "Global Lock Queue"),
            ("status", "fixed-asserts-chart",                   "Asserts"),
            ("status", "fixed-extra-info-page-faults-chart",    "Page Faults"),
            ("status", "operation-throttling-chart",            "Operation Throttling"),
        ],
    },
    {
        "title": "Storage",
        "charts": [
            ("status", "db-storage-total",  "DB Storage Total"),
            ("status", "db-catalog-total",  "DB Catalog Total"),
        ],
    },
    {
        "title": "Atlas Search",
        "charts": [
            ("ftsIndexStats",  "search-query-status-chart",          "Search Query Status"),
            ("ftsIndexStats",  "search-repl-lag-chart",              "Search Replication Lag"),
            ("ftsIndexStats",  "search-opcounters-chart",            "Search Opcounters"),
            ("ftsIndexStats",  "search-index-size-chart",            "Search Index Size"),
            ("ftsIndexStats",  "search-num-index-fields-chart",      "Search Num Index Fields"),
            ("ftsIndexStats",  "search-max-num-index-fields-chart",  "Search Max Index Fields"),
            ("ftsIndexStats",  "search-max-number-of-lucene-docs-chart", "Search Max Lucene Docs"),
            ("otherMem",       "fts-process-memory-chart",           "Search Process Memory"),
            ("ftsServerStatus","fts-page-faults",                    "Search Page Faults"),
            ("ftsServerStatus","fts-jvm-heap-memory",                "Search JVM Heap Memory"),
            ("ftsServerStatus","fts-search-process-throttling",      "Search Process Throttling"),
        ],
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_val(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and math.isnan(v):
        return "—"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.1f}"


def compute_stats(values):
    """Return (avg, p95, p99) skipping None/NaN values."""
    clean = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not clean:
        return None, None, None
    clean.sort()
    n = len(clean)
    avg = sum(clean) / n
    p95 = clean[min(int(n * 0.95), n - 1)]
    p99 = clean[min(int(n * 0.99), n - 1)]
    return avg, p95, p99


def make_summary_html(group_stats) -> str:
    """Render a styled stats table for a group. group_stats = [(chart_title, series_label, avg, p95, p99)]."""
    if not group_stats:
        return ""

    from collections import OrderedDict
    buckets: OrderedDict = OrderedDict()
    for chart_title, series_label, avg, p95, p99 in group_stats:
        buckets.setdefault(chart_title, []).append((series_label, avg, p95, p99))

    rows = ""
    for chart_title, entries in buckets.items():
        for series_label, avg, p95, p99 in entries:
            chart_attr = html.escape(str(chart_title), quote=True)
            series_attr = html.escape(str(series_label), quote=True)
            rows += (
                f"<tr data-chart='{chart_attr}' data-series='{series_attr}'>"
                f"<td>{html.escape(str(chart_title))}</td>"
                f"<td>{html.escape(str(series_label))}</td>"
                f"<td data-stat='avg' style='color:#00ED64'>{fmt_val(avg)}</td>"
                f"<td data-stat='p95' style='color:#F5A623'>{fmt_val(p95)}</td>"
                f"<td data-stat='p99' style='color:#E74C3C'>{fmt_val(p99)}</td>"
                f"</tr>\n"
            )
        if len(entries) > 1:
            tot_avg = sum(e[1] for e in entries if e[1] is not None)
            tot_p95 = sum(e[2] for e in entries if e[2] is not None)
            tot_p99 = sum(e[3] for e in entries if e[3] is not None)
            chart_attr = html.escape(str(chart_title), quote=True)
            rows += (
                f"<tr data-chart='{chart_attr}' data-total='1' style='border-top:1px solid #2a3a4a;font-weight:bold'>"
                f"<td>{html.escape(str(chart_title))}</td>"
                f"<td style='color:#aabbcc'>Total</td>"
                f"<td data-stat='avg' style='color:#00ED64'>{fmt_val(tot_avg)}</td>"
                f"<td data-stat='p95' style='color:#F5A623'>{fmt_val(tot_p95)}</td>"
                f"<td data-stat='p99' style='color:#E74C3C'>{fmt_val(tot_p99)}</td>"
                f"</tr>\n"
            )

    return (
        '<div class="summary-label">Summary — Avg / P95 / P99</div>'
        '<table class="summary-table">'
        "<thead><tr>"
        "<th>Chart</th><th>Series</th>"
        "<th style='color:#00ED64'>Avg</th>"
        "<th style='color:#F5A623'>P95</th>"
        "<th style='color:#E74C3C'>P99</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def ts_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_clip_time(value: str, reference_dt: datetime) -> datetime:
    """
    Parse --since / --until into a timezone-aware UTC datetime.

    Accepts:
      "HH:MM"              →  same date as reference_dt (UTC)
      "HH:MM:SS"           →  same date as reference_dt (UTC)
      "YYYY-MM-DD HH:MM"   →  explicit date, treated as UTC
      "YYYY-MM-DD HH:MM:SS"→  explicit date, treated as UTC
    """
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(
            f"Cannot parse time '{value}'. "
            "Use HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]"
        )

    if parsed.year == 1900:
        # time-only: graft onto the reference date
        parsed = parsed.replace(
            year=reference_dt.year,
            month=reference_dt.month,
            day=reference_dt.day,
        )
    return parsed.replace(tzinfo=timezone.utc)


def extract_series(metrics: dict, category: str, chart_key: str,
                   clip_since: datetime = None, clip_until: datetime = None):
    """Return (timestamps_list, [{label, values}]) or None."""
    cat = metrics.get(category)
    if not cat:
        return None
    chart = cat.get(chart_key)
    if not chart or not isinstance(chart, list):
        return None
    raw_ts = cat.get("timestamps", [])
    if not raw_ts:
        return None

    timestamps = [ts_to_dt(t) for t in raw_ts]

    # apply time clipping
    if clip_since or clip_until:
        mask = [
            (clip_since is None or t >= clip_since) and
            (clip_until is None or t <= clip_until)
            for t in timestamps
        ]
        indices = [i for i, keep in enumerate(mask) if keep]
        if not indices:
            return None
        timestamps = [timestamps[i] for i in indices]
        chart = [
            {label: [vals[i] for i in indices] for label, vals in series_obj.items()}
            for series_obj in chart
        ]

    series = []
    for series_obj in chart:
        for label, values in series_obj.items():
            series.append({"label": label, "values": values})
    return timestamps, series


def make_figure(timestamps, series_list, title: str) -> go.Figure:
    fig = go.Figure()
    for i, s in enumerate(series_list):
        color = COLORS[i % len(COLORS)]
        fill = "tozeroy" if len(series_list) == 1 else "none"
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=s["values"],
                name=s["label"],
                mode="lines",
                line=dict(color=color, width=1.5),
                fill=fill,
                fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.1)",
                hovertemplate="%{x|%H:%M:%S}<br>" + s["label"] + ": %{y:,.3~f}<extra></extra>",
            )
        )
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#8899aa"), x=0, xref="paper"),
        height=220,
        margin=dict(l=50, r=10, t=30, b=30),
        plot_bgcolor="#16213e",
        paper_bgcolor="#16213e",
        font=dict(color="#8899aa", size=10),
        legend=dict(
            orientation="h",
            y=1.12,
            x=0,
            font=dict(size=9),
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode="x unified",
        xaxis=dict(
            gridcolor="#1a2a3a",
            linecolor="#1e4080",
            tickformat="%H:%M",
            tickfont=dict(size=9),
        ),
        yaxis=dict(
            gridcolor="#1a2a3a",
            linecolor="#1e4080",
            tickfont=dict(size=9),
            tickformat="~s",
        ),
    )
    return fig


# ── Main builder ─────────────────────────────────────────────────────────────

def build_dashboard(metrics_path: str, output_path: str, auto_open: bool = False,
                    clip_since: str = None, clip_until: str = None,
                    last_minutes: int = None):
    print(f"Loading {metrics_path} …")
    with open(metrics_path) as f:
        data = json.load(f)

    meta = data.get("meta", {})
    metrics = data.get("metrics", {})

    # full data window
    data_since = ts_to_dt(meta["window"]["since"])
    data_until = ts_to_dt(meta["window"]["until"])
    granularity = meta.get("granularities", {}).get("selected", {}).get("label", "?")

    # --last N  →  clip_since = data_until - N minutes
    if last_minutes is not None:
        from datetime import timedelta
        dt_until = data_until
        dt_since = data_until - timedelta(minutes=last_minutes)
        if dt_since < data_since:
            print(f"  ⚠  --last {last_minutes} exceeds data range, showing full data.")
            dt_since = data_since
    else:
        # parse explicit --since / --until
        dt_since = parse_clip_time(clip_since, data_since) if clip_since else None
        dt_until = parse_clip_time(clip_until, data_since) if clip_until else None

    # validate
    if dt_since and dt_since < data_since:
        print(f"  ⚠  --since {clip_since} is before data start "
              f"({data_since.strftime('%H:%M:%S')} UTC), clamping.")
        dt_since = data_since
    if dt_until and dt_until > data_until:
        print(f"  ⚠  --until {clip_until} is after data end "
              f"({data_until.strftime('%H:%M:%S')} UTC), clamping.")
        dt_until = data_until
    if dt_since and dt_until and dt_since >= dt_until:
        print("ERROR: --since must be earlier than --until")
        sys.exit(1)

    display_since = (dt_since or data_since).strftime("%Y-%m-%d %H:%M UTC")
    display_until = (dt_until or data_until).strftime("%Y-%m-%d %H:%M UTC")

    print(f"Data range : {data_since.strftime('%Y-%m-%d %H:%M UTC')} → "
          f"{data_until.strftime('%Y-%m-%d %H:%M UTC')}")
    if dt_since or dt_until:
        print(f"Clipped to : {display_since} → {display_until}")
    print(f"Granularity: {granularity}")

    # ── Build one HTML div per group, collect all figures ────────────────────
    group_htmls = []
    total_charts = 0

    for group in CHART_GROUPS:
        figs_in_group = []
        group_stats = []
        for cat, chart_key, display_title in group["charts"]:
            result = extract_series(metrics, cat, chart_key, dt_since, dt_until)
            if result is None:
                continue
            timestamps, series_list = result
            if not series_list:
                continue
            fig = make_figure(timestamps, series_list, display_title)
            figs_in_group.append(pio.to_html(fig, full_html=False, include_plotlyjs=False))
            total_charts += 1
            for s in series_list:
                avg, p95, p99 = compute_stats(s["values"])
                if avg is not None:
                    group_stats.append((display_title, s["label"], avg, p95, p99))

        if not figs_in_group:
            continue

        # two-column grid per group
        charts_html = "\n".join(
            f'<div class="chart-cell">{h}</div>' for h in figs_in_group
        )
        summary_html = make_summary_html(group_stats)
        group_htmls.append(
            f"""
            <section class="group" id="group-{group['title'].replace(' ', '-')}">
              <div class="group-title">{group['title']}</div>
              <div class="charts-grid">{charts_html}</div>
              {summary_html}
            </section>"""
        )

    print(f"Rendered   : {total_charts} charts across {len(group_htmls)} groups")

    # ── Nav links ────────────────────────────────────────────────────────────
    nav_links = "\n".join(
        f'<a href="#group-{g["title"].replace(" ", "-")}">{g["title"]}</a>'
        for g in CHART_GROUPS
        if any(
            extract_series(metrics, cat, ck, dt_since, dt_until) is not None
            for cat, ck, _ in g["charts"]
        )
    )

    # ── Assemble full HTML ────────────────────────────────────────────────────
    plotly_cdn = (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/'
        'plotly.js/2.27.0/plotly.min.js"></script>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atlas Metrics — {display_since}</title>
{plotly_cdn}
<style>
  :root {{
    --bg: #1a1a2e; --surface: #16213e; --border: #1e4080;
    --text: #e0e0e0; --muted: #8899aa; --accent: #00ED64;
    --header-bg: #0d1b2a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text);
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; }}

  header {{
    background: var(--header-bg); border-bottom: 1px solid var(--border);
    padding: 10px 20px; display: flex; align-items: center; gap: 14px;
    position: sticky; top: 0; z-index: 200;
  }}
  header h1 {{ font-size: 14px; font-weight: 600; color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: 11px; }}
  .badge {{
    background: #0f3460; border: 1px solid var(--border);
    padding: 2px 8px; border-radius: 4px; font-size: 11px; color: var(--accent);
  }}

  nav {{
    background: var(--header-bg); border-bottom: 1px solid var(--border);
    padding: 0 20px; display: flex; gap: 2px; overflow-x: auto;
    position: sticky; top: 41px; z-index: 199;
  }}
  nav a {{
    padding: 7px 11px; color: var(--muted); text-decoration: none;
    font-size: 11px; white-space: nowrap; border-bottom: 2px solid transparent;
    transition: color 0.15s;
  }}
  nav a:hover {{ color: var(--text); border-bottom-color: #2a5090; }}

  main {{ padding: 14px 20px; }}

  .group {{ margin-bottom: 26px; }}
  .group-title {{
    font-size: 11px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 8px; padding-bottom: 5px; border-bottom: 1px solid var(--border);
  }}
  .charts-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
    gap: 10px;
  }}
  .chart-cell {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px; overflow: hidden;
  }}
  .chart-cell:hover {{ border-color: #2a5090; }}
  .chart-cell .plotly-graph-div {{ width: 100% !important; }}

  .summary-label {{
    font-size: 10px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-top: 10px; margin-bottom: 4px;
  }}
  .summary-table {{
    width: 100%; border-collapse: collapse; font-size: 11px;
  }}
  .summary-table th {{
    background: #0d1b2a; color: var(--muted); text-align: left;
    padding: 5px 8px; border-bottom: 1px solid var(--border);
  }}
  .summary-table td {{
    padding: 4px 8px; border-bottom: 1px solid #1a2a3a; color: var(--text);
  }}
  .summary-table tr:hover td {{ background: #1a2a3a; }}
</style>
</head>
<body>

<header>
  <h1>MongoDB Atlas Metrics</h1>
  <div class="meta">{display_since} &rarr; {display_until}</div>
  <div class="badge">{granularity} granularity</div>
  <div class="badge" style="margin-left:auto">{total_charts} charts</div>
</header>

<nav>
{nav_links}
</nav>

<main>
{''.join(group_htmls)}
</main>

<script>
// ── Linked zoom ───────────────────────────────────────────────────────────────
(function () {{
  var suppressed = new WeakSet();
  var timer   = null;
  var CHUNK   = 8;

  function getAllDivs() {{
    return Array.from(document.querySelectorAll('.plotly-graph-div'));
  }}

  function applyChunked(divs, layoutUpdate) {{
    var i = 0;
    function step() {{
      var end = Math.min(i + CHUNK, divs.length);
      var updates = [];
      for (; i < end; i++) {{
        suppressed.add(divs[i]);
        updates.push(
          Promise.resolve(Plotly.relayout(divs[i], layoutUpdate))
            .finally((function(div) {{
              return function() {{ setTimeout(function() {{ suppressed.delete(div); }}, 50); }};
            }})(divs[i]))
        );
      }}
      Promise.allSettled(updates).then(function() {{
        if (i < divs.length) requestAnimationFrame(step);
      }});
    }}
    requestAnimationFrame(step);
  }}

  // ── Sync zoom across all charts ──────────────────────────────────────────
  function syncAll(sourceId, range) {{
    var others = getAllDivs().filter(function(d) {{ return d.id !== sourceId; }});
    var update = range
      ? {{ 'xaxis.range[0]': range[0], 'xaxis.range[1]': range[1] }}
      : {{ 'xaxis.autorange': true }};
    applyChunked(others, update);
  }}

  function fmtVal(v) {{
    if (v == null) return '—';
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (Number.isInteger(n)) return String(n);
    return n.toFixed(1);
  }}

  function computeStats(values) {{
    var clean = values.filter(function(v) {{
      return v != null && Number.isFinite(Number(v));
    }}).map(Number).sort(function(a, b) {{ return a - b; }});
    if (!clean.length) return {{ avg: null, p95: null, p99: null }};
    var n = clean.length;
    var avg = clean.reduce(function(a, b) {{ return a + b; }}, 0) / n;
    return {{
      avg: avg,
      p95: clean[Math.min(Math.floor(n * 0.95), n - 1)],
      p99: clean[Math.min(Math.floor(n * 0.99), n - 1)]
    }};
  }}

  function firstTraceDate(trace) {{
    var xs = trace.x || [];
    for (var i = 0; i < xs.length; i++) {{
      var ms = new Date(xs[i]).getTime();
      if (Number.isFinite(ms)) return new Date(ms);
    }}
    return null;
  }}

  function axisValueToMs(value, referenceDate) {{
    if (value == null) return null;
    if (value instanceof Date) return value.getTime();
    if (typeof value === 'number') return value;
    var text = String(value).trim();
    var full = text.match(/^(\\d{{4}})-(\\d\\d)-(\\d\\d)[ T](\\d\\d):(\\d\\d)(?::(\\d\\d(?:\\.\\d+)?))?$/);
    if (full) {{
      var sec = Number(full[6] || 0);
      return Date.UTC(
        Number(full[1]), Number(full[2]) - 1, Number(full[3]),
        Number(full[4]), Number(full[5]), Math.floor(sec),
        Math.round((sec - Math.floor(sec)) * 1000)
      );
    }}
    var m = text.match(/^(\\d\\d):(\\d\\d)(?::(\\d\\d(?:\\.\\d+)?))?$/);
    if (m && referenceDate) {{
      var shortSec = Number(m[3] || 0);
      var d = new Date(referenceDate.getTime());
      d.setUTCHours(Number(m[1]), Number(m[2]), Math.floor(shortSec), Math.round((shortSec - Math.floor(shortSec)) * 1000));
      return d.getTime();
    }}
    var parsed = new Date(text).getTime();
    return Number.isFinite(parsed) ? parsed : null;
  }}

  function traceStats(trace, range) {{
    var xs = trace.x || [];
    var ys = trace.y || [];
    var referenceDate = firstTraceDate(trace);
    var start = range ? axisValueToMs(range[0], referenceDate) : null;
    var end = range ? axisValueToMs(range[1], referenceDate) : null;
    var values = [];
    for (var i = 0; i < ys.length; i++) {{
      var t = range ? axisValueToMs(xs[i], referenceDate) : null;
      if (!range || (start != null && end != null && t >= start && t <= end)) values.push(ys[i]);
    }}
    return computeStats(values);
  }}

  function setRowStats(row, stats) {{
    row._visibleStats = stats;
    ['avg', 'p95', 'p99'].forEach(function(key) {{
      var cell = row.querySelector('[data-stat="' + key + '"]');
      if (cell) cell.textContent = fmtVal(stats[key]);
    }});
  }}

  function updateSummaries(range) {{
    document.querySelectorAll('section.group').forEach(function(group) {{
      var divs = Array.from(group.querySelectorAll('.plotly-graph-div'));
      var rows = Array.from(group.querySelectorAll('tr[data-chart]'));

      rows.filter(function(row) {{ return !row.dataset.total; }}).forEach(function(row) {{
        var chart = row.dataset.chart;
        var series = row.dataset.series;
        var stats = null;
        divs.some(function(div) {{
          var title = div.layout && div.layout.title;
          title = title && (title.text || title);
          if (String(title) !== chart) return false;
          var trace = (div.data || []).find(function(t) {{ return String(t.name) === series; }});
          if (!trace) return false;
          stats = traceStats(trace, range);
          return true;
        }});
        setRowStats(row, stats || {{ avg: null, p95: null, p99: null }});
      }});

      rows.filter(function(row) {{ return row.dataset.total; }}).forEach(function(row) {{
        var chart = row.dataset.chart;
        var stats = {{ avg: 0, p95: 0, p99: 0 }};
        rows.forEach(function(other) {{
          if (other.dataset.total || other.dataset.chart !== chart || !other._visibleStats) return;
          ['avg', 'p95', 'p99'].forEach(function(key) {{
            if (other._visibleStats[key] != null) stats[key] += other._visibleStats[key];
          }});
        }});
        setRowStats(row, stats);
      }});
    }});
  }}

  function visibleRange(div) {{
    var axis = div && div._fullLayout && div._fullLayout.xaxis;
    if (axis && axis.range && axis.range.length === 2) return axis.range;
    axis = div && div.layout && div.layout.xaxis;
    if (axis && axis.range && axis.range.length === 2) return axis.range;
    return null;
  }}

  function attachSync(div) {{
    div.on('plotly_relayout', function(e) {{
      if (suppressed.has(div)) return;
      var xr    = e['xaxis.range'];
      var x0    = e['xaxis.range[0]'] == null && xr ? xr[0] : e['xaxis.range[0]'];
      var x1    = e['xaxis.range[1]'] == null && xr ? xr[1] : e['xaxis.range[1]'];
      var reset = e['xaxis.autorange'] === true;
      if ((x0 == null || x1 == null) && !reset) return;
      clearTimeout(timer);
      timer = setTimeout(function() {{
        var range = reset ? null : (visibleRange(div) || [x0, x1]);
        syncAll(div.id, range);
        updateSummaries(range);
      }}, 200);
    }});
  }}

  window.addEventListener('load', function() {{
    getAllDivs().forEach(attachSync);
  }});
}})();
</script>

</body>
</html>"""

    out = Path(output_path)
    out.write_text(html, encoding="utf-8")
    size_mb = out.stat().st_size / 1_048_576
    print(f"Saved      : {out}  ({size_mb:.1f} MB)")

    if auto_open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate an interactive Plotly dashboard from Atlas metrics JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # full data range
  python atlas_metrics_dashboard.py metrics.json

  # last N minutes of the data
  python atlas_metrics_dashboard.py metrics.json --last 30
  python atlas_metrics_dashboard.py metrics.json --last 60 -o last-hour.html

  # clip by time-of-day (UTC)
  python atlas_metrics_dashboard.py metrics.json --since 13:45 --until 14:15

  # clip with seconds precision
  python atlas_metrics_dashboard.py metrics.json --since 13:45:30 --until 14:00:00

  # clip with explicit date (when data spans midnight)
  python atlas_metrics_dashboard.py metrics.json --since "2026-06-22 13:45" --until "2026-06-22 14:15"
        """,
    )
    parser.add_argument("metrics_json", help="Path to the metrics.json file")
    parser.add_argument(
        "--output", "-o",
        default="atlas_metrics_dashboard.html",
        help="Output HTML file (default: atlas_metrics_dashboard.html)",
    )
    parser.add_argument(
        "--since",
        default=None,
        metavar="TIME",
        help="Clip start: HH:MM, HH:MM:SS, or 'YYYY-MM-DD HH:MM' (UTC)",
    )
    parser.add_argument(
        "--until",
        default=None,
        metavar="TIME",
        help="Clip end:   HH:MM, HH:MM:SS, or 'YYYY-MM-DD HH:MM' (UTC)",
    )
    parser.add_argument(
        "--last",
        default=None,
        metavar="MINUTES",
        type=int,
        help="Show only the last N minutes of data (e.g. --last 30)",
    )
    parser.add_argument(
        "--open", dest="auto_open", action="store_true",
        help="Automatically open the dashboard in the browser after generating",
    )
    args = parser.parse_args()

    if args.last and (args.since or args.until):
        parser.error("--last cannot be combined with --since / --until")

    build_dashboard(
        args.metrics_json,
        args.output,
        auto_open=args.auto_open,
        clip_since=args.since,
        clip_until=args.until,
        last_minutes=args.last,
    )


if __name__ == "__main__":
    main()

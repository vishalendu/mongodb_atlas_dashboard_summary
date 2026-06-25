#!/usr/bin/env python3
"""
Atlas Metrics Dashboard
------------------------
Usage:
    python atlas_metrics_dashboard.py metrics.json
    python atlas_metrics_dashboard.py metrics.json --output my_dashboard.html
    python atlas_metrics_dashboard.py metrics.json --open   # auto-open in browser
"""

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
import math

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
            ("status", "db-storage-total",             "DB Storage Total"),
            ("status", "db-catalog-total",             "DB Catalog Total"),
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
            ("process", "normalized-process-cpu",      "Process CPU (Normalized) %"),
            ("process", "normalized-system-cpu",       "System CPU (Normalized) %"),
            ("process", "max-normalized-system-cpu",   "Max System CPU (Normalized) %"),
            ("process", "system-cpu",                  "System CPU %"),
            ("process", "max-system-cpu",              "Max System CPU %"),
            ("process", "process-cpu",                 "Process CPU %"),
            ("process", "max-process-cpu",             "Max Process CPU %"),
        ],
    },
    {
        "title": "Memory",
        "charts": [
            ("status",    "fixed-mem-chart",    "Memory (MB)"),
            ("systemMem", "system-memory",      "System Memory"),
            ("systemMem", "max-system-memory",  "Max System Memory"),
            ("systemMem", "swap-usage",         "Swap Usage"),
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
            ("disk", "disk-data-space-used-chart",        "Disk Space Used"),
            ("disk", "disk-data-space-free-chart",        "Disk Space Free"),
            ("disk", "disk-data-space-percent-free-chart","Disk Space Free %"),
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
        "title": "Atlas Search",
        "charts": [
            ("ftsIndexStats",  "search-query-status-chart",              "Search Query Status"),
            ("ftsIndexStats",  "search-repl-lag-chart",                  "Search Replication Lag"),
            ("ftsIndexStats",  "search-opcounters-chart",                "Search Opcounters"),
            ("ftsIndexStats",  "search-index-size-chart",                "Search Index Size"),
            ("ftsIndexStats",  "search-num-index-fields-chart",          "Search Index Fields"),
            ("ftsIndexStats",  "search-max-num-index-fields-chart",      "Search Max Index Fields"),
            ("ftsIndexStats",  "search-max-number-of-lucene-docs-chart", "Search Max Lucene Docs"),
            ("otherMem",       "fts-process-memory-chart",               "Search Process Memory"),
            ("otherCpu",       "fts-process-cpu",                        "Search Process CPU"),
            ("otherCpu",       "fts-normalized-process-cpu",             "Search Process CPU (Normalized)"),
            ("ftsServerStatus","fts-jvm-heap-memory",                    "Search JVM Heap Memory"),
            ("ftsServerStatus","fts-page-faults",                        "Search Page Faults"),
            ("ftsServerStatus","fts-search-process-throttling",          "Search Process Throttling"),
            ("otherDisk",      "fts-disk-space-used-chart",              "Search Disk Space Used"),
        ],
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_val(v) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "0"
    abs_v = abs(v)
    for threshold, suffix in [(1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")]:
        if abs_v >= threshold:
            scaled = v / threshold
            return f"{scaled:.3g}{suffix}"
    return f"{v:.3g}"


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

    # group by chart_title preserving order
    from collections import OrderedDict
    buckets: OrderedDict = OrderedDict()
    for chart_title, series_label, avg, p95, p99 in group_stats:
        buckets.setdefault(chart_title, []).append((series_label, avg, p95, p99))

    rows = ""
    for chart_title, entries in buckets.items():
        for series_label, avg, p95, p99 in entries:
            rows += (
                f"<tr>"
                f"<td>{chart_title}</td>"
                f"<td>{series_label}</td>"
                f"<td style='color:#00ED64'>{fmt_val(avg)}</td>"
                f"<td style='color:#F5A623'>{fmt_val(p95)}</td>"
                f"<td style='color:#E74C3C'>{fmt_val(p99)}</td>"
                f"</tr>\n"
            )
        if len(entries) > 1:
            tot_avg = sum(e[1] for e in entries if e[1] is not None)
            tot_p95 = sum(e[2] for e in entries if e[2] is not None)
            tot_p99 = sum(e[3] for e in entries if e[3] is not None)
            rows += (
                f"<tr style='border-top:1px solid #2a3a4a;font-weight:bold'>"
                f"<td>{chart_title}</td>"
                f"<td style='color:#aabbcc'>Total</td>"
                f"<td style='color:#00ED64'>{fmt_val(tot_avg)}</td>"
                f"<td style='color:#F5A623'>{fmt_val(tot_p95)}</td>"
                f"<td style='color:#E74C3C'>{fmt_val(tot_p99)}</td>"
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


def extract_series(metrics: dict, category: str, chart_key: str):
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

def build_dashboard(metrics_path: str, output_path: str, auto_open: bool = False):
    print(f"Loading {metrics_path} …")
    with open(metrics_path) as f:
        data = json.load(f)

    meta = data.get("meta", {})
    metrics = data.get("metrics", {})

    since = ts_to_dt(meta["window"]["since"]).strftime("%Y-%m-%d %H:%M UTC")
    until = ts_to_dt(meta["window"]["until"]).strftime("%Y-%m-%d %H:%M UTC")
    granularity = meta.get("granularities", {}).get("selected", {}).get("label", "?")

    print(f"Time range : {since} → {until}")
    print(f"Granularity: {granularity}")

    # ── Build one HTML div per group, collect all figures ────────────────────
    group_htmls = []
    total_charts = 0

    for group in CHART_GROUPS:
        figs_in_group = []
        group_stats = []
        for cat, chart_key, display_title in group["charts"]:
            result = extract_series(metrics, cat, chart_key)
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
            extract_series(metrics, cat, ck) is not None
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
<title>Atlas Metrics — {since}</title>
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
  <div class="meta">{since} &rarr; {until}</div>
  <div class="badge">{granularity} granularity</div>
  <div class="badge" style="margin-left:auto">{total_charts} charts</div>
</header>

<nav>
{nav_links}
</nav>

<main>
{''.join(group_htmls)}
</main>

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
        description="Generate an interactive Plotly dashboard from Atlas metrics JSON."
    )
    parser.add_argument("metrics_json", help="Path to the metrics.json file")
    parser.add_argument(
        "--output", "-o",
        default="atlas_metrics_dashboard.html",
        help="Output HTML file (default: atlas_metrics_dashboard.html)",
    )
    parser.add_argument(
        "--open", dest="auto_open", action="store_true",
        help="Automatically open the dashboard in the browser after generating",
    )
    args = parser.parse_args()
    build_dashboard(args.metrics_json, args.output, args.auto_open)


if __name__ == "__main__":
    main()

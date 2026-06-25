#!/usr/bin/env python3
"""
Generate a compact MongoDB Atlas metrics summary report.

Example:
  python3 atlas_metrics_summary.py metrics.json --since "2026-06-22 12:00" --until "2026-06-22 12:08"
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from atlas_metrics_core import METRICS, fmt, fmt_memory, parse_time, summarize, ts_to_dt, value_as_kb


def render_html(rows, since, until, output):
    sections = []
    order = []
    for row in rows:
        section = row["metric"].section
        if section not in order:
            order.append(section)

    for section in order:
        body = []
        for row in [r for r in rows if r["metric"].section == section]:
            m = row["metric"]
            if section == "Memory" and m.unit in {"KB", "MB"}:
                stat_cells = []
                for key in ("avg", "p5", "p95", "p99", "max"):
                    kb = value_as_kb(m, row[key])
                    data_kb = "" if kb is None else f"{kb:.12g}"
                    stat_cells.append(f"<td class='mem-value' data-kb='{data_kb}'>{fmt_memory(kb)}</td>")
                unit_cell = (
                    "<select class='unit-select' onchange='setMemoryUnit(this)'>"
                    "<option>KB</option><option>MB</option><option selected>GB</option>"
                    "</select>"
                )
            else:
                stat_cells = [
                    f"<td>{fmt(row['avg'])}</td>",
                    f"<td>{fmt(row['p5'])}</td>",
                    f"<td>{fmt(row['p95'])}</td>",
                    f"<td>{fmt(row['p99'])}</td>",
                    f"<td>{fmt(row['max'])}</td>",
                ]
                unit_cell = html.escape(m.unit)
            body.append(
                "<tr>"
                f"<td><span class='pill {row['severity']}'>{row['severity']}</span></td>"
                f"<td>{html.escape(m.name)}</td>"
                f"{''.join(stat_cells)}"
                f"<td>{unit_cell}</td>"
                f"<td>{html.escape(m.note)}</td>"
                "</tr>"
            )
        sections.append(
            f"<h2>{html.escape(section)}</h2>"
            "<table><thead><tr><th>Status</th><th>Metric</th><th>Avg</th><th>P5</th><th>P95</th><th>P99</th><th>Max</th><th>Unit</th><th>Why it matters</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Atlas Metrics Summary</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#111827; color:#e5e7eb; margin:24px; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
h2 {{ font-size:14px; margin:24px 0 8px; color:#93c5fd; }}
.meta {{ color:#9ca3af; margin-bottom:16px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; background:#0f172a; }}
th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #243244; vertical-align:top; }}
th {{ color:#9ca3af; background:#111f35; }}
.pill {{ display:inline-block; min-width:54px; text-align:center; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:700; text-transform:uppercase; }}
.ok {{ background:#064e3b; color:#6ee7b7; }}
.warn {{ background:#78350f; color:#fbbf24; }}
.critical {{ background:#7f1d1d; color:#fca5a5; }}
.info {{ background:#374151; color:#d1d5db; }}
.unit-select {{ background:#0b1220; color:#e5e7eb; border:1px solid #334155; border-radius:4px; padding:3px 6px; }}
</style>
<script>
function formatNumber(v) {{
  if (!Number.isFinite(v)) return '-';
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(1);
}}
function setMemoryUnit(select) {{
  var factor = {{ KB: 1, MB: 1024, GB: 1024 * 1024 }}[select.value];
  select.closest('tr').querySelectorAll('.mem-value').forEach(function(cell) {{
    var kb = Number(cell.dataset.kb);
    cell.textContent = Number.isFinite(kb) ? formatNumber(kb / factor) : '-';
  }});
}}
</script>
</head>
<body>
<h1>MongoDB Atlas Metrics Summary</h1>
<div class="meta">{since:%Y-%m-%d %H:%M:%S UTC} to {until:%Y-%m-%d %H:%M:%S UTC}</div>
{''.join(sections)}
</body>
</html>
"""
    Path(output).write_text(html_doc, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate a compact MongoDB Atlas metrics summary HTML report.")
    parser.add_argument("metrics_json")
    parser.add_argument("--since", required=True, help="UTC start: HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--until", required=True, help="UTC end: HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--output", "-o", default="atlas_metrics_summary.html")
    args = parser.parse_args()

    data = json.loads(Path(args.metrics_json).read_text())
    data_since = ts_to_dt(data["meta"]["window"]["since"])
    data_until = ts_to_dt(data["meta"]["window"]["until"])
    since = parse_time(args.since, data_since)
    until = parse_time(args.until, data_since)
    if since < data_since or until > data_until or since >= until:
        print(f"Data range is {data_since:%Y-%m-%d %H:%M:%S UTC} to {data_until:%Y-%m-%d %H:%M:%S UTC}", file=sys.stderr)
        raise SystemExit("Invalid --since/--until range")

    rows = summarize(data.get("metrics", {}), since, until)
    render_html(rows, since, until, args.output)
    print(f"Saved {args.output}")
    print(f"Sample timestamp range: {data_since:%Y-%m-%d %H:%M:%S UTC} to {data_until:%Y-%m-%d %H:%M:%S UTC}")


if __name__ == "__main__":
    main()

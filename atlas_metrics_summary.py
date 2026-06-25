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
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Metric:
    section: str
    name: str
    category: str
    chart: str
    series: tuple[str, ...]
    stat: str = "p95"
    unit: str = ""
    warn: float | None = None
    critical: float | None = None
    lower_is_bad: bool = False
    note: str = ""


METRICS = [
    Metric("System pressure", "Max normalized system CPU", "process", "max-normalized-system-cpu", ("user", "kernel", "nice", "iowait", "irq", "softirq", "guest", "steal"), stat="p99", unit="%", warn=60, critical=80, note="Full host CPU, includes OS and mongod."),
    Metric("System pressure", "Process CPU", "process", "normalized-process-cpu", ("user", "kernel"), unit="%", warn=60, critical=80, note="mongod process CPU."),
    Metric("System pressure", "Page faults", "status", "fixed-extra-info-page-faults-chart", ("page faults",), warn=1, critical=100),
    Metric("Memory", "Process resident memory", "status", "fixed-mem-chart", ("resident",), unit="MB", note="Physical memory used by mongod."),
    Metric("Memory", "Process virtual memory", "status", "fixed-mem-chart", ("virtual",), unit="MB"),
    Metric("Memory", "System memory used", "systemMem", "system-memory", ("mem used",), unit="KB"),
    Metric("Memory", "System memory available", "systemMem", "system-memory", ("mem available",), unit="KB"),
    Metric("Memory", "Swap used", "systemMem", "swap-usage", ("swap used",), unit="KB", warn=1, critical=1024 * 1024, note="Any swap use is worth checking."),
    Metric("Query efficiency", "Scanned / returned", "status", "query-targeting", ("scanned / returned",), warn=100, critical=1000, note="High values usually mean weak index targeting."),
    Metric("Query efficiency", "Scanned objects / returned", "status", "query-targeting", ("scanned objects / returned",), warn=100, critical=1000),
    Metric("Query efficiency", "Read latency", "status", "fixed-avg-operation-execution-times-chart", ("avg ms/read",), unit="ms", warn=10, critical=50),
    Metric("Query efficiency", "Write latency", "status", "fixed-avg-operation-execution-times-chart", ("avg ms/write",), unit="ms", warn=10, critical=50),
    Metric("Query efficiency", "Command latency", "status", "fixed-avg-operation-execution-times-chart", ("avg ms/command",), unit="ms", warn=10, critical=50),
    Metric("WiredTiger", "WT cache fill", "status", "fixed-wtCache-cache-ratio-chart", ("cache fill ratio",), unit="%", warn=85, critical=95),
    Metric("WiredTiger", "WT dirty cache", "status", "fixed-wtCache-cache-ratio-chart", ("dirty fill ratio",), unit="%", warn=10, critical=20),
    Metric("WiredTiger", "WT read tickets available", "status", "fixed-wtTickets-available-chart", ("reads",), stat="p5", warn=50, critical=10, lower_is_bad=True),
    Metric("WiredTiger", "WT write tickets available", "status", "fixed-wtTickets-available-chart", ("writes",), stat="p5", warn=50, critical=10, lower_is_bad=True),
    Metric("Disk", "Disk read latency", "disk", "disk-data-latency-chart", ("read latency",), unit="ms", warn=10, critical=25),
    Metric("Disk", "Disk write latency", "disk", "disk-data-latency-chart", ("write latency",), unit="ms", warn=10, critical=25),
    Metric("Disk", "Disk queue depth", "disk", "disk-data-queue-depth-chart", ("disk queue depth",), warn=5, critical=20),
    Metric("Disk", "Disk free", "disk", "disk-data-space-percent-free-chart", ("percent disk space free",), stat="p5", unit="%", warn=20, critical=10, lower_is_bad=True),
    Metric("Disk", "Disk IOPS", "disk", "disk-data-iops-chart", ("read iops", "write iops"), unit="iops", note="Average IOPS."),
    Metric("Disk", "Max disk IOPS", "disk", "max-disk-data-iops-chart", ("max read iops", "max write iops"), stat="p99", unit="iops", note="Peak IOPS; compare with average IOPS."),
    Metric("Connections", "Current connections", "status", "fixed-connections-chart", ("current",)),
    Metric("Connections", "Connection creation rate", "status", "fixed-connection-rate-chart", ("connections created",), unit="/sec", warn=50, critical=200),
    Metric("Replication", "Replication lag", "status", "oplog-secondary-lag-master-time-chart", ("lag time",), unit="sec", warn=10, critical=60),
    Metric("Replication", "Oplog window", "status", "oplog-master-time-chart", ("oplog window",), stat="p5", unit="hours", warn=24, critical=6, lower_is_bad=True),
    Metric("Errors / throttling", "Global lock queue", "status", "fixed-global-lock-current-queue-chart", ("total",), warn=1, critical=10),
    Metric("Errors / throttling", "Regular asserts", "status", "fixed-asserts-chart", ("regular",), warn=1, critical=100, note="Internal server assertion failures."),
    Metric("Errors / throttling", "Warning asserts", "status", "fixed-asserts-chart", ("warning",), warn=1, critical=100, note="Server warning assertions."),
    Metric("Errors / throttling", "Message asserts", "status", "fixed-asserts-chart", ("msg",), warn=1, critical=100, note="Server message assertions."),
    Metric("Errors / throttling", "User asserts", "status", "fixed-asserts-chart", ("user",), warn=1, critical=100, note="Client/application command errors, e.g. bad queries, duplicate keys, auth errors."),
    Metric("Errors / throttling", "Operation throttling", "status", "operation-throttling-chart", ("rejected", "killed", "rejected (IWM)", "terminated (killOp)"), warn=1, critical=100),
    Metric("Workload context", "Opcounters command", "status", "fixed-opcounters-chart", ("command",), unit="ops/sec", note="Context only; high is not automatically bad."),
    Metric("Workload context", "Opcounters query", "status", "fixed-opcounters-chart", ("query",), unit="ops/sec"),
    Metric("Workload context", "Opcounters getmore", "status", "fixed-opcounters-chart", ("getmore",), unit="ops/sec"),
    Metric("Workload context", "Opcounters insert", "status", "fixed-opcounters-chart", ("insert",), unit="ops/sec"),
    Metric("Workload context", "Opcounters update", "status", "fixed-opcounters-chart", ("update",), unit="ops/sec"),
    Metric("Workload context", "Opcounters delete", "status", "fixed-opcounters-chart", ("delete",), unit="ops/sec"),
    Metric("Workload context", "TTL deleted", "status", "fixed-opcounters-chart", ("ttldeleted",), unit="ops/sec"),
    Metric("Workload context", "Documents returned", "status", "document-metrics", ("returned",), unit="docs/sec"),
    Metric("Workload context", "Documents changed", "status", "document-metrics", ("inserted", "updated", "deleted"), unit="docs/sec"),
]


def ts_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_time(value: str, reference: datetime) -> datetime:
    for fmt in ("%H:%M", "%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError("Use HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]")
    if parsed.year == 1900:
        parsed = parsed.replace(year=reference.year, month=reference.month, day=reference.day)
    return parsed.replace(tzinfo=timezone.utc)


def clean(values):
    return [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]


def stats(values):
    values = sorted(clean(values))
    if not values:
        return {}
    n = len(values)
    return {
        "avg": sum(values) / n,
        "p5": values[min(int(n * 0.05), n - 1)],
        "p95": values[min(int(n * 0.95), n - 1)],
        "p99": values[min(int(n * 0.99), n - 1)],
        "max": values[-1],
    }


def fmt(v):
    if v is None:
        return "-"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.1f}"


def value_as_kb(metric: Metric, value):
    if value is None:
        return None
    if metric.unit == "KB":
        return value
    if metric.unit == "MB":
        return value * 1024
    return None


def fmt_memory(kb, unit="GB"):
    if kb is None:
        return "-"
    factor = {"KB": 1, "MB": 1024, "GB": 1024 * 1024}[unit]
    return fmt(kb / factor)


def series_values(metrics, metric: Metric, since: datetime, until: datetime):
    cat = metrics.get(metric.category, {})
    raw_ts = cat.get("timestamps", [])
    chart = cat.get(metric.chart, [])
    if not raw_ts or not chart:
        return []
    indices = [i for i, ms in enumerate(raw_ts) if since <= ts_to_dt(ms) <= until]
    by_label = {label: obj[label] for obj in chart for label in metric.series if label in obj}
    values = []
    for i in indices:
        point = [
            vals[i]
            for vals in by_label.values()
            if i < len(vals) and vals[i] is not None and not (isinstance(vals[i], float) and math.isnan(vals[i]))
        ]
        if point:
            values.append(sum(point))
    return values


def severity(metric: Metric, value):
    if value is None or metric.warn is None or metric.critical is None:
        return "info"
    if metric.lower_is_bad:
        if value <= metric.critical:
            return "critical"
        if value <= metric.warn:
            return "warn"
    else:
        if value >= metric.critical:
            return "critical"
        if value >= metric.warn:
            return "warn"
    return "ok"


def summarize(metrics, since, until):
    rows = []
    for metric in METRICS:
        s = stats(series_values(metrics, metric, since, until))
        value = s.get(metric.stat)
        rows.append({
            "metric": metric,
            "avg": s.get("avg"),
            "p5": s.get("p5"),
            "p95": s.get("p95"),
            "p99": s.get("p99"),
            "max": s.get("max"),
            "value": value,
            "severity": severity(metric, value),
        })
    return rows


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

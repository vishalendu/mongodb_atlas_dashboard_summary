#!/usr/bin/env python3
"""
Compare up to three MongoDB Atlas metrics windows from a JSON config.

Example:
  python3 atlas_metrics_compare.py compare_config.json
"""

import argparse
import html
import json
import sys
from pathlib import Path

import atlas_metrics_core as summary


STATUS_RANK = {"ok": 0, "info": 0, "warn": 1, "critical": 2}


def pct_change(before, after):
    if before is None or after is None:
        return None
    if before == 0:
        return None
    return ((after - before) / abs(before)) * 100


def delta_class(metric, before, after):
    if before is None or after is None or before == after:
        return "flat"
    worse = after < before if metric.lower_is_bad else after > before
    return "worse" if worse else "better"


def display_value(metric, value):
    if metric.section == "Memory" and metric.unit in {"KB", "MB"}:
        kb = summary.value_as_kb(metric, value)
        return None if kb is None else kb / (1024 * 1024)
    return value


def fmt_delta(metric, before, after):
    if before is None or after is None:
        return "-"
    display_before = display_value(metric, before)
    display_after = display_value(metric, after)
    if display_before is None or display_after is None:
        return "-"
    delta = display_after - display_before
    pct = pct_change(before, after)
    sign = "+" if delta > 0 else ""
    if pct is None:
        return f"{sign}{summary.fmt(delta)}"
    return f"{sign}{summary.fmt(delta)} ({sign}{summary.fmt(pct)}%)"


def load_window(window):
    metrics_path = Path(window["metrics_json"])
    data = json.loads(metrics_path.read_text())
    data_since = summary.ts_to_dt(data["meta"]["window"]["since"])
    data_until = summary.ts_to_dt(data["meta"]["window"]["until"])
    since = summary.parse_time(window["since"], data_since)
    until = summary.parse_time(window["until"], data_since)
    if since < data_since or until > data_until or since >= until:
        raise ValueError(
            f"{window.get('name', metrics_path.name)} range must be within "
            f"{data_since:%Y-%m-%d %H:%M:%S UTC} to {data_until:%Y-%m-%d %H:%M:%S UTC}"
        )
    rows = summary.summarize(data.get("metrics", {}), since, until)
    by_metric = {(r["metric"].section, r["metric"].name): r for r in rows}
    return {
        "name": window.get("name") or metrics_path.stem,
        "metrics_json": str(metrics_path),
        "since": since,
        "until": until,
        "rows": by_metric,
    }


def meaningful_changes(windows):
    if len(windows) < 2:
        return []
    before = windows[0]
    after = windows[-1]
    changes = []
    for key, left in before["rows"].items():
        right = after["rows"].get(key)
        if not right:
            continue
        metric = left["metric"]
        before_value = left.get(metric.stat)
        after_value = right.get(metric.stat)
        pct = pct_change(before_value, after_value)
        status_changed = left["severity"] != right["severity"]
        notable = status_changed or (pct is not None and abs(pct) >= 10)
        if notable:
            changes.append({
                "key": key,
                "metric": metric,
                "before": before_value,
                "after": after_value,
                "pct": pct,
                "status_before": left["severity"],
                "status_after": right["severity"],
                "class": delta_class(metric, before_value, after_value),
            })
    changes.sort(key=lambda c: (
        STATUS_RANK.get(c["status_after"], 0) - STATUS_RANK.get(c["status_before"], 0),
        abs(c["pct"] or 0),
    ), reverse=True)
    return changes


def unit_for(metric, value):
    if metric.section == "Memory" and metric.unit in {"KB", "MB"}:
        kb = summary.value_as_kb(metric, value)
        return summary.fmt_memory(kb), "GB"
    return summary.fmt(value), metric.unit


def render(config, windows, output):
    keys = []
    seen = set()
    for metric in summary.METRICS:
        key = (metric.section, metric.name)
        if key not in seen:
            keys.append(key)
            seen.add(key)

    changes = meaningful_changes(windows)
    cards = []
    for w in windows:
        counts = {"critical": 0, "warn": 0, "ok": 0, "info": 0}
        for row in w["rows"].values():
            counts[row["severity"]] = counts.get(row["severity"], 0) + 1
        cards.append(
            "<div class='card'>"
            f"<h2>{html.escape(w['name'])}</h2>"
            f"<div>{w['since']:%Y-%m-%d %H:%M UTC} to {w['until']:%H:%M UTC}</div>"
            f"<p><b class='critical-text'>{counts['critical']}</b> critical · "
            f"<b class='warn-text'>{counts['warn']}</b> warn · {counts['ok']} ok</p>"
            f"<small>{html.escape(w['metrics_json'])}</small>"
            "</div>"
        )

    change_rows = []
    for c in changes[:12]:
        metric = c["metric"]
        before, unit = unit_for(metric, c["before"])
        after, _ = unit_for(metric, c["after"])
        change_rows.append(
            f"<tr class='{c['class']}'>"
            f"<td>{html.escape(metric.section)}</td>"
            f"<td>{html.escape(metric.name)}</td>"
            f"<td>{html.escape(c['status_before'])} -> {html.escape(c['status_after'])}</td>"
            f"<td>{before}</td><td>{after}</td><td>{fmt_delta(metric, c['before'], c['after'])}</td>"
            f"<td>{html.escape(unit)}</td>"
            "</tr>"
        )
    if not change_rows:
        change_rows.append("<tr><td colspan='7'>No status changes or >=10% changes in the primary metric.</td></tr>")

    section_tables = []
    current_section = None
    rows = []
    for key in keys:
        metric = next(m for m in summary.METRICS if (m.section, m.name) == key)
        if metric.section != current_section:
            if rows:
                section_tables.append(section_html(current_section, rows, windows))
            current_section = metric.section
            rows = []
        rows.append(metric_row(metric, windows))
    if rows:
        section_tables.append(section_html(current_section, rows, windows))

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Atlas Metrics Comparison</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#111827; color:#e5e7eb; margin:24px; }}
h1 {{ font-size:22px; margin:0 0 12px; }}
h2 {{ font-size:15px; margin:0 0 8px; color:#93c5fd; }}
h3 {{ font-size:14px; margin:24px 0 8px; color:#bfdbfe; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; margin-bottom:22px; }}
.card {{ background:#0f172a; border:1px solid #243244; border-radius:6px; padding:12px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; background:#0f172a; margin-bottom:16px; }}
th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #243244; vertical-align:top; }}
th {{ color:#9ca3af; background:#111f35; }}
.pill {{ display:inline-block; min-width:54px; text-align:center; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:700; text-transform:uppercase; }}
.ok,.info {{ background:#374151; color:#d1d5db; }}
.warn {{ background:#78350f; color:#fbbf24; }}
.critical {{ background:#7f1d1d; color:#fca5a5; }}
.better td {{ color:#86efac; }}
.worse td {{ color:#fca5a5; }}
.flat {{ color:#d1d5db; }}
.critical-text {{ color:#fca5a5; }}
.warn-text {{ color:#fbbf24; }}
small {{ color:#9ca3af; }}
</style>
</head>
<body>
<h1>MongoDB Atlas Metrics Comparison</h1>
<div class="cards">{''.join(cards)}</div>
<h3>Important Changes</h3>
<table><thead><tr><th>Section</th><th>Metric</th><th>Status</th><th>{html.escape(windows[0]['name'])}</th><th>{html.escape(windows[-1]['name'])}</th><th>Delta</th><th>Unit</th></tr></thead><tbody>{''.join(change_rows)}</tbody></table>
{''.join(section_tables)}
</body>
</html>
"""
    Path(output).write_text(html_doc, encoding="utf-8")


def section_html(section, rows, windows):
    heads = "".join(f"<th>{html.escape(w['name'])}</th>" for w in windows)
    return (
        f"<h3>{html.escape(section)}</h3>"
        f"<table><thead><tr><th>Metric</th>{heads}<th>Delta</th><th>Unit</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def metric_row(metric, windows):
    values = []
    statuses = []
    for w in windows:
        row = w["rows"].get((metric.section, metric.name), {})
        value = row.get(metric.stat)
        rendered, unit = unit_for(metric, value)
        severity = row.get("severity", "info")
        statuses.append(severity)
        values.append(f"<td><span class='pill {severity}'>{severity}</span> {rendered}</td>")
    first = windows[0]["rows"].get((metric.section, metric.name), {}).get(metric.stat)
    last = windows[-1]["rows"].get((metric.section, metric.name), {}).get(metric.stat)
    cls = delta_class(metric, first, last)
    return (
        f"<tr class='{cls}'>"
        f"<td>{html.escape(metric.name)}</td>"
        f"{''.join(values)}"
        f"<td>{fmt_delta(metric, first, last)}</td>"
        f"<td>{html.escape(unit)}</td>"
        "</tr>"
    )


def main():
    parser = argparse.ArgumentParser(description="Compare 2-3 Atlas metrics summary windows from config JSON.")
    parser.add_argument("config_json")
    args = parser.parse_args()
    config_path = Path(args.config_json)
    config = json.loads(config_path.read_text())
    windows_config = config.get("windows") or config.get("comparisons")
    if not isinstance(windows_config, list) or not (2 <= len(windows_config) <= 3):
        raise SystemExit("config must contain 2 or 3 windows")
    try:
        windows = [load_window(w) for w in windows_config]
    except (KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    output = config.get("output", "atlas_metrics_compare.html")
    render(config, windows, output)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()

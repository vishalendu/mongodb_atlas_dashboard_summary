#!/usr/bin/env python3
"""
Export selected Atlas peak metrics to Parquet files.

Example:
  python3 export_peak_metrics_parquet.py metrics.json --since "2026-06-22 11:58" --until "2026-06-22 12:12" --filename incident
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atlas_metrics_core import parse_time, ts_to_dt


CPU_SERIES = ("user", "kernel", "nice", "iowait", "irq", "softirq", "guest", "steal")
DISK_IOPS_SERIES = ("max read iops", "max write iops")


def clipped_indices(raw_timestamps, since, until):
    return [i for i, ts in enumerate(raw_timestamps) if since <= ts_to_dt(ts) <= until]


def chart_series(metrics, category, chart_key):
    chart = metrics.get(category, {}).get(chart_key, [])
    return {label: values for item in chart for label, values in item.items()}


def value_at(series_map, label, index):
    values = series_map.get(label)
    if values is None or index >= len(values):
        return None
    return values[index]


def rows_for_metric(raw_timestamps, indices, series_map, labels, total_name):
    rows = []
    for i in indices:
        row = {"timestamp_ms": raw_timestamps[i], "timestamp_utc": ts_to_dt(raw_timestamps[i]).isoformat()}
        total = 0
        for label in labels:
            value = value_at(series_map, label, i)
            column = label.replace(" ", "_").replace("/", "_")
            row[column] = value
            if value is not None:
                total += value
        row[total_name] = total
        rows.append(row)
    return rows


def write_parquet(rows, path):
    if not rows:
        raise ValueError(f"No datapoints for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def output_paths(filename):
    base = Path(filename).stem
    out = Path("output")
    return (
        out / f"{base}_max_normalized_system_cpu.parquet",
        out / f"{base}_max_disk_iops.parquet",
    )


def main():
    parser = argparse.ArgumentParser(description="Export Max normalized system CPU and Max disk IOPS datapoints to Parquet.")
    parser.add_argument("metrics_json")
    parser.add_argument("--since", required=True, help="UTC start: HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--until", required=True, help="UTC end: HH:MM, HH:MM:SS, or YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--filename", required=True, help="Base output filename; two parquet files are written under output/")
    args = parser.parse_args()

    data = json.loads(Path(args.metrics_json).read_text())
    data_since = ts_to_dt(data["meta"]["window"]["since"])
    data_until = ts_to_dt(data["meta"]["window"]["until"])
    since = parse_time(args.since, data_since)
    until = parse_time(args.until, data_since)
    if since < data_since or until > data_until or since >= until:
        print(f"Data range is {data_since:%Y-%m-%d %H:%M:%S UTC} to {data_until:%Y-%m-%d %H:%M:%S UTC}", file=sys.stderr)
        raise SystemExit("Invalid --since/--until range")

    metrics = data.get("metrics", {})
    cpu_ts = metrics["process"]["timestamps"]
    disk_ts = metrics["disk"]["timestamps"]
    cpu_indices = clipped_indices(cpu_ts, since, until)
    disk_indices = clipped_indices(disk_ts, since, until)

    cpu_rows = rows_for_metric(
        cpu_ts,
        cpu_indices,
        chart_series(metrics, "process", "max-normalized-system-cpu"),
        CPU_SERIES,
        "total_max_normalized_system_cpu",
    )
    disk_rows = rows_for_metric(
        disk_ts,
        disk_indices,
        chart_series(metrics, "disk", "max-disk-data-iops-chart"),
        DISK_IOPS_SERIES,
        "total_max_disk_iops",
    )

    cpu_path, disk_path = output_paths(args.filename)
    write_parquet(cpu_rows, cpu_path)
    write_parquet(disk_rows, disk_path)
    print(f"Saved {cpu_path} ({len(cpu_rows)} rows)")
    print(f"Saved {disk_path} ({len(disk_rows)} rows)")


if __name__ == "__main__":
    main()

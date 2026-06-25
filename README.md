# MongoDB Atlas Metrics Dashboard

Generate interactive dashboards, summary reports, and comparison reports from MongoDB Atlas metrics JSON data.

## Scripts

### `atlas_metrics_dashboard_v6.py`
Interactive Plotly dashboard with all metric charts grouped by category. Includes linked zoom (zoom one chart, all sync), time window clipping, and summary tables (Avg / P95 / P99).

```bash
# full data range
python atlas_metrics_dashboard_v6.py metrics.json

# last N minutes
python atlas_metrics_dashboard_v6.py metrics.json --last 30
python atlas_metrics_dashboard_v6.py metrics.json --last 60 -o last-hour.html

# clip by time (UTC)
python atlas_metrics_dashboard_v6.py metrics.json --since 13:45 --until 14:15
python atlas_metrics_dashboard_v6.py metrics.json --since 13:45:30 --until 14:00:00

# clip with explicit date (when data spans midnight)
python atlas_metrics_dashboard_v6.py metrics.json --since "2026-06-22 13:45" --until "2026-06-22 14:15"

# auto-open in browser
python atlas_metrics_dashboard_v6.py metrics.json --open
```

**Output:** Interactive HTML with Plotly.js charts.

### `atlas_metrics_summary.py`
Compact HTML summary report with health status indicators (ok / warn / critical) for key metrics. Covers sections: System pressure, Memory, Query efficiency, WiredTiger, Disk, Connections, Replication, Errors / throttling, and Workload context.

```bash
python atlas_metrics_summary.py metrics.json --since "2026-06-22 12:00" --until "2026-06-22 12:08" -o summary.html
```

**Output:** Lightweight HTML table report with Avg, P5, P95, P99, Max per metric.

### `atlas_metrics_compare.py` (in `version/`)
Compare 2–3 time windows from a config JSON and produce a side-by-side comparison HTML report. Highlights status changes and metrics with >=10% change.

```bash
python version/atlas_metrics_compare.py compare_config.json
```

**Config** (`compare_config.sample.json`):
```json
{
  "output": "atlas_metrics_compare.html",
  "windows": [
    {
      "name": "Before",
      "metrics_json": "metrics.json",
      "since": "2026-06-22 10:53",
      "until": "2026-06-22 11:06"
    },
    {
      "name": "After",
      "metrics_json": "metrics.json",
      "since": "2026-06-22 11:58",
      "until": "2026-06-22 12:12"
    }
  ]
}
```

**Output:** HTML with summary cards per window, important changes table, and per-section metric tables showing before/after/delta.

## Requirements

```
pip install plotly
```

Python 3.10+ recommended.

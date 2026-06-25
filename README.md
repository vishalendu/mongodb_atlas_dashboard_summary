# last 30 minutes of data
python atlas_metrics_dashboard.py metrics.json --last 30

# last 1 hour
python atlas_metrics_dashboard.py metrics.json --last 60 -o last-hour.html

# specific window by time
python atlas_metrics_dashboard.py metrics.json --since 10:00 --until 11:30

# specific window by full datetime
python atlas_metrics_dashboard.py metrics.json --since "2026-06-22 10:00" --until "2026-06-22 11:00"

# full data
python atlas_metrics_dashboard.py metrics.json

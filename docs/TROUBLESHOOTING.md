# Troubleshooting Guide

This guide covers common issues, warnings, and error messages encountered during setup or operation of the COVID-19 Tracker.

---

## 1. Database Issues

### Error: `sqlite3.OperationalError: database is locked`
- **Why**: SQLite is a single-file database. If multiple threads write to it concurrently, or if an ETL pipeline is running while Gunicorn is processing heavy requests, the database will lock.
- **Fix**:
  1. Increase the timeout in `DATABASE_URL` by appending query parameters:
     `sqlite:///data/covid19.db?timeout=30`
  2. The actual production solution is to migrate to **PostgreSQL**. See [MIGRATION.md](file:///Users/pradeepkumar/PythonProjectTwo/docs/MIGRATION.md).

### Warning: `Foreign Key Constraint Violation`
- **Why**: Occurs if `daily_cases` or `vaccinations` records are inserted for a country that doesn't exist in `country_metadata`.
- **Fix**: The ETL pipeline (`etl/pipeline.py`) guarantees order of execution. It loads `country_metadata` *first*, and dynamically inserts missing countries before writing cases. Ensure you do not load tables out of order if executing manual scripts.

---

## 2. Extraction & Network Failures

### Error: `DataExtractionError: Failed to fetch resource after 3 retries`
- **Why**: The Johns Hopkins GitHub repository or Our World in Data repository could be undergoing maintenance, or your network is blocked/rate-limited by GitHub.
- **Fix**:
  1. Test your network connectivity: `curl -I https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv`.
  2. If rate-limited, wait. The ETL extract function automatically uses exponential backoff (`sleep(2^n)`) up to 3 times before failing.

---

## 3. Web Dashboard Issues

### Error: `RuntimeError: Python is not installed as a framework` (Matplotlib crash)
- **Why**: Matplotlib by default tries to open an interactive GUI window. On server platforms (or Flask), this will crash because there is no display server (X11/Aqua) active.
- **Fix**: In `visualization/static_charts.py`, we explicitly set the non-interactive backend *before* importing `pyplot`:
  ```python
  import matplotlib
  matplotlib.use("Agg")  # Non-interactive backend
  import matplotlib.pyplot as plt
  ```

### Error: `HTTP 429: Too Many Requests`
- **Why**: You have hit the rate limit configuration. By default, API endpoints limit requests, and the `/api/refresh` pipeline route restricts runs to 5 times per minute.
- **Fix**: You can relax or change these parameters in `.env` by adjusting `LIMITER_DEFAULT_LIMITS` or disabling rate limits in testing:
  ```ini
  LIMITER_DEFAULT_LIMITS="500 per day;100 per hour"
  ```

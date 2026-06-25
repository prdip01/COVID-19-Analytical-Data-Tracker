# COVID-19 Analytical Data Tracker

A production-grade, full-stack COVID-19 data tracker built with **Python, Flask, Pandas, SQLite/PostgreSQL, SQLAlchemy, Pandera, and Plotly.js**.

The application extracts raw time-series data from Johns Hopkins CSSE (cases, deaths, recovered) and Our World in Data (vaccinations, populations, continents), performs strict transformations and rolling calculations, validates data against schemas, stores it, and serves a modern, responsive dark-mode dashboard.

---

## Architecture Overview

```
covid19-tracker/
├── .github/workflows/       # GitHub Actions: daily ETL (6 AM UTC) & CI test suite
├── data/                    # Local storage (Git-ignored)
│   ├── raw/                 # Raw downloaded CSV files
│   ├── processed/           # Cached pandas output files
│   └── backups/             # SQLite daily database backups
├── database/                # Schema, models, connection pooling
├── docs/                    # Architecture logs, Postgres migration, troubleshooting
├── etl/                     # Extraction, Pandera transformation, and database loading
├── scripts/                 # Shell scripts: backup and restore
├── static/css/ & js/        # Vanilla CSS and client-side AJAX controllers
├── templates/               # Flask Jinja2 HTML templates
├── tests/                   # Pytest suite (unit and integration tests)
├── app.py                   # Flask server entry point (limiter, cache, security, inputs)
├── config.py                # Environment configuration and logging setup
├── docker-compose.yml       # Docker configuration (Flask, Postgres, Redis)
└── requirements.txt         # Project package requirements
```

---

## Data Source Attribution
1. **COVID-19 Cases, Deaths, Recoveries**: Johns Hopkins University Center for Systems Science and Engineering (JHU CSSE). Note: Dataset is archived and ends on **March 10, 2023**.
2. **Vaccinations Progress**: Our World in Data (OWID) COVID-19 Dataset.
3. **Country Metadata & Demographics**: List of countries geographic metadata.

---

## Local Setup Instructions

### 1. Initialize Virtual Environment & Install Dependencies
Ensure you have Python 3.10+ installed.

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the template `.env.example` into a new `.env` file:

```bash
cp .env.example .env
```

You can customize variables like `PORT`, `DATABASE_URL`, or `LOG_LEVEL` inside `.env`.

### 3. Run the ETL Data Pipeline
To seed the database with JHU and OWID datasets, run:

```bash
python etl/pipeline.py
```
This downloads the CSVs, transforms them, validates schemas via **Pandera**, calculates 7-day rolling averages, and inserts records into your database.

### 4. Run the Web Server
Launch the Flask development server:

```bash
python app.py
```
Open your browser and navigate to `http://localhost:5001`.

---

## Running the Test Suite
The project contains unit and integration tests run via `pytest`.

```bash
# Run all tests
pytest tests/
```

---

## Database Backups & Restorations
The database backup scripts are located in `scripts/` and have error handling and log checks.

```bash
# Perform a safe, transaction-safe hot copy of the database (runs online)
./scripts/backup.sh

# Restore the database from a specific backup file
./scripts/restore.sh data/backups/backup_20260624_233000.db
```

---

## Production Deployment Checklist

Depending on your requirements, deploy using one of the three following tiers:

### Tier 1: Single-User Demo (Default)
- **Database**: SQLite (`sqlite:///data/covid19.db`)
- **Cache**: In-Memory (`SimpleCache`)
- **Process Manager**: Python built-in development server (debugging mode off) or single-worker Gunicorn.
- **Backup**: Run `./scripts/backup.sh` via a daily cron job.

### Tier 2: Multi-User Production (Recommended)
- **Database**: **PostgreSQL** (Uncomment `db` service in `docker-compose.yml`)
- **Cache**: **Redis** (Uncomment `cache` service in `docker-compose.yml`)
- **Web Server**: Gunicorn with Eventlet asynchronous worker class:
  ```bash
  gunicorn -c gunicorn.conf.py app:app
  ```
- **Rate Limiting**: Enforced via Redis backend for persistent IP tracking.
- **Migration Details**: See [MIGRATION.md](file:///Users/pradeepkumar/PythonProjectTwo/docs/MIGRATION.md).

### Tier 3: High Scale (Enterprise)
- **Database**: PostgreSQL with Read Replicas (routing queries to read-only endpoints).
- **Cache**: Redis Cluster (distributed caching of query endpoints).
- **Static Assets**: Serve CSS, JavaScript, and static images from a CDN (Cloudflare / AWS CloudFront).
- **Orchestration**: Deploy to Kubernetes (EKS/GKE) with auto-scaling replicas behind an Application Load Balancer.
- **Shutdown**: Utilize container SIGTERM orchestration hooks to cleanly flush connection pools.

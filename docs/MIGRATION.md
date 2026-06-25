# SQLite to PostgreSQL Migration Guide

This guide describes how to migrate the COVID-19 Tracker database from SQLite to PostgreSQL for multi-user, production-grade deployments.

---

## Step 1: Spin up PostgreSQL and Redis
To deploy in a multi-user environment, we transition from SQLite and in-memory caches to PostgreSQL and Redis.

1. Open `docker-compose.yml` in the root of the project.
2. Uncomment the `db` (PostgreSQL) and `cache` (Redis) services.
3. Uncomment the persistent volumes section at the bottom of the file.
4. Uncomment the environment variables under the `web` service mapping to `db` and `cache`.

Run the containers:
```bash
docker-compose up -d
```

---

## Step 2: Configure Environment Variables
If running outside of Docker Compose, configure your local `.env` file to redirect the database URL and caching parameters:

```ini
# Comment SQLite setup
# DATABASE_URL=sqlite:///data/covid19.db

# Uncomment PostgreSQL setup
DATABASE_URL=postgresql://postgres:postgres_secure_pass@localhost:5432/covid19

# Toggle Caching to Redis
CACHE_TYPE=RedisCache
REDIS_URL=redis://localhost:6379/0
```

---

## Step 3: Run the Schema Initialization
When the database starts, Flask will automatically create the tables. If you want to trigger it manually, run:

```bash
# Activate virtual environment
source .venv/bin/activate

# Execute schema creation
python -c "from database.connection import init_db; init_db()"
```

SQLAlchemy will automatically detect the PostgreSQL connection string and configure the connection pool (`pool_size=10`, `max_overflow=20`, etc.).

---

## Step 4: Run the ETL Pipeline
Trigger the ETL pipeline to pull the historical JHU and OWID datasets directly into your PostgreSQL instance:

```bash
python etl/pipeline.py
```

The database loader (`etl/load.py`) uses a dialect-aware query. It will automatically switch from SQLite's `INSERT OR REPLACE` to PostgreSQL's `ON CONFLICT (country, date) DO UPDATE` command.

---

## Step 5: (Optional) Migrate Historical Data from SQLite
If you already have a populated local `covid19.db` and wish to transfer its contents directly to PostgreSQL, you can use `pgloader` or a simple python script:

1. Install `pgloader`:
   ```bash
   brew install pgloader  # Mac
   # or
   apt-get install pgloader # Ubuntu
   ```
2. Execute migration:
   ```bash
   pgloader data/covid19.db postgresql://postgres:postgres_secure_pass@localhost:5432/covid19
   ```

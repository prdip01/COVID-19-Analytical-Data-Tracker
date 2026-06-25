"""
Flask Web Application entry point for the COVID-19 Data Tracker.

Implements route handlers for the dashboard home, dynamic chart APIs, and health checks.
Ensures production safety with rate limiting, caching, security headers, input sanitization,
and transactional safe signal handling for graceful shutdowns.
"""

import os
import warnings
# Suppress Pandera warnings early before full import
os.environ["DISABLE_PANDERA_IMPORT_WARNING"] = "True"
warnings.filterwarnings("ignore", category=UserWarning, module="pandera")

import atexit
from datetime import datetime, timezone
import logging
import re
import signal
import sys
from typing import Dict, Any, List

from flask import Flask, render_template, request, jsonify, send_file
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import (
    PORT,
    DEBUG,
    DATABASE_URL,
    CACHE_TYPE,
    REDIS_URL,
    LIMITER_DEFAULT_LIMITS,
    SECRET_KEY,
    ADMIN_API_KEY,
    setup_logging
)
from database.connection import get_db, init_db, engine
from etl.pipeline import run_pipeline, ETLLockError
from visualization.interactive_charts import (
    generate_cases_interactive,
    generate_vaccination_progress_interactive
)
from visualization.static_charts import (
    generate_global_trend_chart,
    generate_top_countries_bar,
    generate_cases_heatmap
)

# 1. Setup logging system
setup_logging()
logger = logging.getLogger("flask_app")

# 2. Initialize Flask App
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Global CSRF Protection
csrf = CSRFProtect(app)

# 3. Configure Security Headers (Content Security Policy)
@app.after_request
def add_security_headers(response):
    """
    Applies security headers to every outgoing HTTP response.
    Specifically blocks clickjacking and enforces a strict Content Security Policy.
    """
    # Enforce script and style constraints (Plotly requires unsafe-inline for charts)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.plot.ly; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    # Prevent rendering dashboard in external iframe to defend against clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    # Block MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Force HTTPS (in production, usually managed by Nginx/Proxy but keep as best practice)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# 4. Configure Flask-Limiter for Rate Limiting
limiter_args = {
    "key_func": get_remote_address,
    "app": app,
    "default_limits": LIMITER_DEFAULT_LIMITS.split(";")
}
if REDIS_URL:
    logger.info("REDIS_URL is configured. Routing Flask-Limiter storage to Redis: %s", REDIS_URL)
    limiter_args["storage_uri"] = REDIS_URL
else:
    logger.warning("REDIS_URL is not configured. Falling back to in-memory rate limiting (limitations: rate limits will not be shared across worker processes).")

limiter = Limiter(**limiter_args)

# 5. Configure Flask-Caching
cache_config = {}
if REDIS_URL:
    logger.info("REDIS_URL is configured. Routing Flask-Caching backend to Redis: %s", REDIS_URL)
    cache_config["CACHE_TYPE"] = "RedisCache"
    cache_config["CACHE_REDIS_URL"] = REDIS_URL
else:
    logger.warning("REDIS_URL is not configured. Falling back to in-memory SimpleCache backend.")
    cache_config["CACHE_TYPE"] = "SimpleCache"

logger.info("Initializing Cache with config: %s", cache_config)
cache = Cache(app, config=cache_config)

# 6. Safe Input Sanitization Audits
# Compile simple regex for country name validation (letters, spaces, dashes, commas, apostrophes, parenthesis)
COUNTRY_NAME_REGEX = re.compile(r"^[a-zA-Z\s\-',.()]+$")
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sanitize_country_name(name: str) -> bool:
    """
    Validates country name structure to block characters associated with SQL injection or script injections.
    """
    if not name:
        return False
    return bool(COUNTRY_NAME_REGEX.match(name))


def sanitize_date(date_str: str) -> bool:
    """
    Validates YYYY-MM-DD date format representation.
    """
    if not date_str:
        return False
    if not DATE_REGEX.match(date_str):
        return False
    try:
        # Check if date string represents an actual valid date (e.g. not Feb 31)
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

# --- Route Handlers ---

@app.route('/')
def index():
    """
    Renders the main dashboard page.
    Retrieves and caches summary metrics and baseline data.
    """
    logger.info("Serving home dashboard page.")
    
    with get_db() as db:
        # 1. Fetch available countries for filter dropdown
        countries_query = text("SELECT DISTINCT country FROM country_metadata ORDER BY country")
        countries_list = [row[0] for row in db.execute(countries_query).fetchall()]
        
        # Default starting selection
        default_countries = ["United States", "United Kingdom", "India", "Brazil"]
        
        # 2. Fetch latest data refresh date
        last_updated_query = text("SELECT MAX(ingested_at) FROM daily_cases")
        last_updated_raw = db.execute(last_updated_query).scalar()
        
        last_updated = "No data loaded"
        if last_updated_raw:
            # Parse datetime string or object
            if isinstance(last_updated_raw, str):
                try:
                    last_updated = datetime.strptime(last_updated_raw[:19], "%Y-%m-%d %H:%M:%S").strftime("%b %d, %Y %I:%M %p")
                except ValueError:
                    last_updated = last_updated_raw
            else:
                last_updated = last_updated_raw.strftime("%b %d, %Y %I:%M %p")

        # 3. Retrieve overall summary statistics
        summary_stats = {"cases": 0, "deaths": 0, "recovered": 0, "vaccinations": 0}
        
        try:
            # Cumulative sums of latest records across countries
            cases_sum = db.execute(text("""
                WITH LatestCases AS (
                    SELECT country, cases, deaths, recovered,
                           ROW_NUMBER() OVER (PARTITION BY country ORDER BY date DESC) as rn
                    FROM daily_cases
                )
                SELECT SUM(cases), SUM(deaths), SUM(recovered) 
                FROM LatestCases 
                WHERE rn = 1
            """)).fetchone()
            
            if cases_sum and cases_sum[0] is not None:
                summary_stats["cases"] = cases_sum[0]
                summary_stats["deaths"] = cases_sum[1]
                summary_stats["recovered"] = cases_sum[2]
                
            # Latest vaccinations total sum
            vax_sum = db.execute(text("""
                WITH LatestVax AS (
                    SELECT country, people_fully_vaccinated,
                           ROW_NUMBER() OVER (PARTITION BY country ORDER BY date DESC) as rn
                    FROM vaccinations
                )
                SELECT SUM(people_fully_vaccinated) 
                FROM LatestVax 
                WHERE rn = 1
            """)).scalar()
            
            if vax_sum is not None:
                summary_stats["vaccinations"] = vax_sum
                
        except Exception as e:
            logger.error("Error retrieving global summaries for dashboard card render: %s", e)

        # 4. Generate Interactive Global Vaccination Map JSON
        vax_map_json = generate_vaccination_progress_interactive(db)

    return render_template(
        'index.html',
        countries_list=countries_list,
        default_countries=default_countries,
        summary_stats=summary_stats,
        last_updated=last_updated,
        vax_map_json=vax_map_json
    )


@app.route('/api/charts/cases')
@limiter.limit("60 per minute")
def api_cases_chart():
    """
    Returns Plotly line chart config as JSON based on country and filter selections.
    """
    countries = request.args.getlist('countries')
    metric = request.args.get('metric', 'rolling_avg_7d')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    # --- Parameter Validation & Audit ---
    if not countries:
        return jsonify({"error": "At least one country parameter is required."}), 400
        
    # Standardize empty strings to None
    if start_date == "": start_date = None
    if end_date == "": end_date = None

    # Validate inputs to protect against SQL injections
    for c in countries:
        if not sanitize_country_name(c):
            logger.warning("Suspicious input pattern blocked. Country: '%s'", c)
            return jsonify({"error": f"Invalid country format detected: {c}"}), 400
            
    if start_date and not sanitize_date(start_date):
        logger.warning("Suspicious input pattern blocked. Start Date: '%s'", start_date)
        return jsonify({"error": "Invalid start date format. Must be YYYY-MM-DD"}), 400
        
    if end_date and not sanitize_date(end_date):
        logger.warning("Suspicious input pattern blocked. End Date: '%s'", end_date)
        return jsonify({"error": "Invalid end date format. Must be YYYY-MM-DD"}), 400
        
    if metric not in ["cases", "deaths", "recovered", "rolling_avg_7d"]:
        logger.warning("Suspicious input pattern blocked. Metric: '%s'", metric)
        return jsonify({"error": "Invalid metric selected."}), 400

    # Retrieve interactive Plotly charts
    with get_db() as db:
        chart_json = generate_cases_interactive(
            db, countries, metric, start_date, end_date
        )
        
    return response_json_direct(chart_json)


@app.route('/api/static-charts/<chart_name>.png')
@cache.cached(timeout=3600)  # Cache static charts for an hour (ETL runs daily)
def api_static_charts(chart_name: str):
    """
    Renders and returns high-quality static charts dynamically from the database.
    """
    with get_db() as db:
        if chart_name == "global-trend":
            buf = generate_global_trend_chart(db)
        elif chart_name == "top-countries":
            buf = generate_top_countries_bar(db)
        elif chart_name == "heatmap":
            buf = generate_cases_heatmap(db)
        else:
            return jsonify({"error": "Static chart endpoint not found."}), 404
            
    return send_file(buf, mimetype="image/png")


@app.route('/api/refresh', methods=['POST'])
@csrf.exempt
@limiter.limit("5 per minute")  # ETL execution is highly resource intensive
def api_refresh():
    """
    Manual trigger to run the ETL data refresh pipeline.
    Restricted to prevent concurrency and rate limit abuses.
    """
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    timestamp_str = datetime.now(timezone.utc).isoformat()
    logger.info("Manual refresh attempt from IP: %s at %s", client_ip, timestamp_str)
    
    # 1. Authenticate X-API-Key header
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header or api_key_header != ADMIN_API_KEY:
        logger.warning("Unauthorized refresh attempt from IP: %s. Invalid or missing X-API-Key.", client_ip)
        return jsonify({"error": "Forbidden: Invalid or missing X-API-Key."}), 403

    # 2. Trigger pipeline and handle locking
    try:
        stats = run_pipeline()
        # Reset cache on success
        cache.clear()
        return jsonify(stats), 200
    except ETLLockError as lock_err:
        logger.warning("ETL pipeline refresh request blocked: concurrent run detected. IP: %s", client_ip)
        return jsonify({"error": "Locked: ETL pipeline is already running."}), 423
    except Exception as e:
        logger.exception("Manual ETL pipeline refresh failed.")
        return jsonify({"error": f"ETL Pipeline execution failed: {str(e)}"}), 500


@app.route('/health')
@csrf.exempt
def health_check():
    """
    Liveness and health-check endpoint for Docker or cloud environment setups.
    Verifies database connection.
    """
    try:
        # Check DB connection
        with get_db() as db:
            db.execute(text("SELECT 1")).scalar()
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        logger.error("Health check failed. DB offline: %s", e)
        return jsonify({
            "status": "unhealthy",
            "reason": f"Database connection failed: {str(e)}"
        }), 500


# --- CSRF Test Endpoint ---
@app.route('/api/test-csrf-target', methods=['POST'])
def api_test_csrf_target():
    return jsonify({"status": "ok"}), 200


# --- Helpers ---

def response_json_direct(json_str: str):
    """
    Returns raw JSON string directly to prevent double-encoding by jsonify.
    """
    return app.response_class(json_str, mimetype='application/json')


# --- Graceful Shutdown Setup ---

def handle_shutdown(signum, frame):
    """
    Clean shutdown worker. Stops the server and safely flushes engine connection pools.
    """
    logger.info("Shutdown signal caught (signal %d). Closing connection pool...", signum)
    try:
        engine.dispose()
        logger.info("Database engine connections closed successfully.")
    except Exception as e:
        logger.error("Failed to cleanly dispose database engine: %s", e)
    finally:
        sys.exit(0)


# Bind signals
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Register clean exit when python process closes naturally
atexit.register(engine.dispose)

if __name__ == "__main__":
    # Pre-initialize DB on startup
    init_db()
    
    logger.info("Starting Flask application on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)

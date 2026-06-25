"""
Configuration module for the COVID-19 Data Tracker.

Loads configuration from environment variables (using a .env file if present)
and sets up application-wide settings and structured logging.
"""

import os
os.environ["DISABLE_PANDERA_IMPORT_WARNING"] = "True"
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pandera")

import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
BACKUP_DIR = DATA_DIR / "backups"

# Ensure all standard data folders exist
for folder in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, BACKUP_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# Port to bind Flask app to
PORT = int(os.environ.get("PORT", "5001"))

# Flask Environment setting ('development' or 'production')
FLASK_ENV = os.environ.get("FLASK_ENV", "development")
DEBUG = FLASK_ENV == "development"

# Database connection settings (Fail fast on missing value)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("CRITICAL CONFIGURATION ERROR: DATABASE_URL environment variable is not set.")

# Helper to normalize database urls for SQLite path resolution
if DATABASE_URL.startswith("sqlite:///"):
    # Extract path and make it absolute if it isn't
    db_path_str = DATABASE_URL.replace("sqlite:///", "")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = (BASE_DIR / db_path).resolve()
    DATABASE_URL = f"sqlite:///{db_path}"

# Cache configuration settings
CACHE_TYPE = os.environ.get("CACHE_TYPE", "SimpleCache")
REDIS_URL = os.environ.get("REDIS_URL", "")

# Flask rate limiting
LIMITER_DEFAULT_LIMITS = os.environ.get(
    "LIMITER_DEFAULT_LIMITS", "200 per day;50 per hour"
)

# App Secret Key for signing session cookie (Fail fast on missing value)
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("CRITICAL CONFIGURATION ERROR: SECRET_KEY environment variable is not set.")

# Admin API Key for securing operations (Fail fast on missing value)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")
if not ADMIN_API_KEY:
    raise ValueError("CRITICAL CONFIGURATION ERROR: ADMIN_API_KEY environment variable is not set.")

# Global Logging Level
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# Data endpoints for ETL
JHU_BASE_URL = (
    "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/"
    "csse_covid_19_data/csse_covid_19_time_series"
)

JHU_CONFIRMED_URL = f"{JHU_BASE_URL}/time_series_covid19_confirmed_global.csv"
JHU_DEATHS_URL = f"{JHU_BASE_URL}/time_series_covid19_deaths_global.csv"
JHU_RECOVERED_URL = f"{JHU_BASE_URL}/time_series_covid19_recovered_global.csv"

# OWID Vaccinations URL
OWID_VACCINATIONS_URL = (
    "https://raw.githubusercontent.com/owid/covid-19-data/master/"
    "public/data/vaccinations/vaccinations.csv"
)

# Lorey's Country Metadata URL (Population, Continent, ISO codes)
COUNTRY_METADATA_URL = (
    "https://raw.githubusercontent.com/lorey/list-of-countries/master/"
    "csv/countries.csv"
)


def setup_logging() -> None:
    """
    Sets up the global logging configuration.
    Outputs logs to both console (stdout) and 'data/etl.log'.
    """
    log_file_path = DATA_DIR / "etl.log"
    
    # Configure handlers
    file_handler = logging.FileHandler(log_file_path)
    console_handler = logging.StreamHandler()
    
    # Create clean format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Apply root level configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    
    # Clear existing handlers to prevent duplicate logging
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.info("Logging configured. Writing logs to %s", log_file_path)

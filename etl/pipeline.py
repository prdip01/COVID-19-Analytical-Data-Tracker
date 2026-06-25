"""
ETL Pipeline orchestrator for the COVID-19 Data Tracker.

Executes extract, transform, and load phases inside a single transactional block
and logs execution metrics, including success/failure status and record counts.
"""

import os
import sys
import logging
from typing import Dict, Any
import redis

from config import setup_logging, REDIS_URL, DATA_DIR
from database.connection import init_db, get_db
from etl.extract import extract_all, DataExtractionError
from etl.transform import transform_cases, transform_country_metadata, transform_vaccinations
from etl.load import load_country_metadata, load_cases, load_vaccinations

# Configure logging for standalone script execution
setup_logging()
logger = logging.getLogger("etl_pipeline")


class ETLLockError(Exception):
    """Exception raised when the ETL lock cannot be acquired."""
    pass


class ETLLock:
    def __init__(self):
        self.redis_client = None
        self.lock_file_fd = None
        self.lock_file_path = os.path.join(DATA_DIR, "etl.lock")
        
        if REDIS_URL:
            try:
                self.redis_client = redis.Redis.from_url(REDIS_URL)
                self.redis_client.ping()
            except Exception as e:
                logger.warning("Redis URL is set but connection failed. Falling back to file lock. Error: %s", e)
                self.redis_client = None

    def acquire(self) -> bool:
        if self.redis_client:
            try:
                # ex=1800 (30 minutes expiry) to prevent deadlocks on abrupt failures
                acquired = self.redis_client.set("etl_lock", "running", ex=1800, nx=True)
                if acquired:
                    logger.info("Successfully acquired Redis ETL lock.")
                    return True
                else:
                    logger.warning("Failed to acquire Redis ETL lock. Another process is running.")
                    return False
            except Exception as e:
                logger.error("Redis error acquiring lock: %s. Falling back to file lock.", e)
                self.redis_client = None

        try:
            # File-based atomic lock
            self.lock_file_fd = os.open(self.lock_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.lock_file_fd, str(os.getpid()).encode())
            logger.info("Successfully acquired file-based ETL lock at %s.", self.lock_file_path)
            return True
        except FileExistsError:
            logger.warning("Failed to acquire file-based ETL lock. File %s already exists.", self.lock_file_path)
            return False
        except Exception as e:
            logger.error("Error creating ETL lock file: %s", e)
            return False

    def release(self):
        if self.redis_client:
            try:
                self.redis_client.delete("etl_lock")
                logger.info("Successfully released Redis ETL lock.")
            except Exception as e:
                logger.error("Error releasing Redis ETL lock: %s", e)
        else:
            if self.lock_file_fd is not None:
                try:
                    os.close(self.lock_file_fd)
                except Exception:
                    pass
                self.lock_file_fd = None
            if os.path.exists(self.lock_file_path):
                try:
                    os.remove(self.lock_file_path)
                    logger.info("Successfully released file-based ETL lock.")
                except Exception as e:
                    logger.error("Error removing lock file %s: %s", self.lock_file_path, e)


def run_pipeline() -> Dict[str, Any]:
    """
    Orchestrates the entire ETL pipeline.
    
    1. Downloads raw data files (Extract)
    2. Cleans, aggregates, calculates rolling average, and validates (Transform)
    3. Safely loads all data into SQLite/Postgres inside a single transaction (Load)
    
    Returns:
        A dictionary containing pipeline execution stats.
        
    Raises:
        Exception: Re-raises any error that forces a pipeline rollback.
    """
    logger.info("Starting COVID-19 Data Tracker ETL Pipeline...")
    
    lock = ETLLock()
    if not lock.acquire():
        raise ETLLockError("ETL pipeline is already running.")
        
    try:
        # Ensure database tables exist
        init_db()
        
        # 1. EXTRACT
        try:
            raw_paths = extract_all()
        except DataExtractionError as e:
            logger.critical("Pipeline aborted during EXTRACT phase: %s", e)
            raise
            
        # 2. TRANSFORM
        try:
            logger.info("Executing TRANSFORM phase...")
            cases_df = transform_cases(
                raw_paths["confirmed"],
                raw_paths["deaths"],
                raw_paths["recovered"]
            )
            metadata_df = transform_country_metadata(
                raw_paths["countries"],
                cases_df
            )
            vax_df = transform_vaccinations(
                raw_paths["vaccinations"]
            )
            logger.info("TRANSFORM phase completed successfully.")
        except Exception as e:
            logger.critical("Pipeline aborted during TRANSFORM phase: %s", e)
            raise

        # 3. LOAD (Wrapped in a single database transaction)
        logger.info("Executing LOAD phase inside single transaction block...")
        
        try:
            with get_db() as db_session:
                # We must load country metadata first due to Foreign Key constraints in cases & vaccinations
                meta_count = load_country_metadata(db_session, metadata_df)
                cases_count = load_cases(db_session, cases_df)
                vax_count = load_vaccinations(db_session, vax_df)
                
                # Explicit commit
                db_session.commit()
                
                logger.info("LOAD transaction committed successfully.")
                
                stats = {
                    "status": "success",
                    "countries_inserted_or_updated": meta_count,
                    "case_records_inserted_or_updated": cases_count,
                    "vaccination_records_inserted_or_updated": vax_count
                }
                logger.info("Pipeline execution summary: %s", stats)
                return stats
                
        except Exception as e:
            logger.exception("Pipeline failed during LOAD phase. Transaction rolled back.")
            raise
    finally:
        lock.release()


if __name__ == "__main__":
    try:
        run_pipeline()
        sys.exit(0)
    except Exception as err:
        logger.critical("ETL Pipeline execution failed: %s", err)
        sys.exit(1)

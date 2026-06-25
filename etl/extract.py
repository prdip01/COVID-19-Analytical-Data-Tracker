"""
Data extraction module for the COVID-19 Data Tracker ETL pipeline.

Downloads raw CSV files from Johns Hopkins CSSE and Our World in Data repositories
with robust connection timeouts, retries, exponential backoffs, and data freshness validation.
"""

import logging
import time
from pathlib import Path
from typing import Dict
import requests

from config import (
    RAW_DATA_DIR,
    JHU_CONFIRMED_URL,
    JHU_DEATHS_URL,
    JHU_RECOVERED_URL,
    OWID_VACCINATIONS_URL,
    COUNTRY_METADATA_URL
)

logger = logging.getLogger(__name__)


class DataExtractionError(Exception):
    """Custom exception raised when data extraction fails."""
    pass


def download_file(
    url: str,
    target_path: Path,
    timeout: int = 10,
    max_retries: int = 3,
    backoff_factor: int = 2
) -> None:
    """
    Downloads a file from a URL and saves it to the target path.
    Implements retry logic with exponential backoff and timeout handling.

    Args:
        url: The URL to download from.
        target_path: Absolute path to save the downloaded file.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of download retries.
        backoff_factor: Exponential multiplier for retry sleep intervals.

    Raises:
        DataExtractionError: If the download fails after all retries or validations fail.
    """
    logger.info("Starting download: %s -> %s", url, target_path.name)
    
    # Ensure raw directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    retry_count = 0
    while retry_count <= max_retries:
        try:
            response = requests.get(url, timeout=timeout)
            
            # Raise an HTTPError if the status was 4xx, 5xx
            response.raise_for_status()
            
            content = response.text
            
            # --- Freshness/Sanity Validation ---
            if len(content.strip()) < 100:
                raise DataExtractionError(
                    f"Downloaded content from {url} is too small ({len(content)} bytes), likely corrupted."
                )
                
            # Quick check for header structures
            first_line = content.split('\n')[0]
            if not any(keyword in first_line for keyword in ["Country", "Province", "Lat", "Long", "location", "date", "name"]):
                raise DataExtractionError(
                    f"Invalid CSV structure detected in download. Header line: '{first_line}'"
                )

            # Write out content to destination
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
                
            logger.info("Successfully downloaded and validated %s.", target_path.name)
            return

        except (requests.RequestException, DataExtractionError) as e:
            retry_count += 1
            if retry_count > max_retries:
                logger.error(
                    "Failed to download %s after %d attempts. Last error: %s",
                    url, max_retries, str(e)
                )
                raise DataExtractionError(
                    f"Failed to fetch resource from {url} after {max_retries} retries."
                ) from e
                
            sleep_time = backoff_factor ** retry_count
            logger.warning(
                "Error downloading %s. Attempt %d/%d failed. Retrying in %d seconds... Error: %s",
                url, retry_count, max_retries, sleep_time, str(e)
            )
            time.sleep(sleep_time)


def extract_all() -> Dict[str, Path]:
    """
    Extracts all raw files required by the ETL pipeline.
    
    Returns:
        A dictionary mapping the data type string to its local Path object.
        
    Raises:
        DataExtractionError: If any of the essential downloads fail.
    """
    logger.info("Beginning execution of JHU and OWID extract phase.")
    
    downloads = {
        "confirmed": (JHU_CONFIRMED_URL, RAW_DATA_DIR / "confirmed.csv"),
        "deaths": (JHU_DEATHS_URL, RAW_DATA_DIR / "deaths.csv"),
        "recovered": (JHU_RECOVERED_URL, RAW_DATA_DIR / "recovered.csv"),
        "vaccinations": (OWID_VACCINATIONS_URL, RAW_DATA_DIR / "vaccinations.csv"),
        "countries": (COUNTRY_METADATA_URL, RAW_DATA_DIR / "countries.csv")
    }
    
    paths_dict: Dict[str, Path] = {}
    
    for key, (url, path) in downloads.items():
        try:
            download_file(url, path)
            paths_dict[key] = path
        except DataExtractionError as e:
            logger.error("Extract phase terminated due to failure in extracting key '%s': %s", key, e)
            raise
            
    logger.info("Extract phase completed successfully.")
    return paths_dict

"""
Unit tests for the COVID-19 Data Tracker ETL pipeline.

Tests data transformations, standardization, rolling average computations,
and database idempotency using an in-memory SQLite connection.
"""

from datetime import datetime, date
import os
import unittest.mock as mock
import pytest
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import requests
from database.models import Base, DailyCases, CountryMetadata
from etl.extract import download_file, DataExtractionError
from etl.transform import (
    standardize_country_name,
    transform_cases,
    transform_country_metadata,
    DailyCasesSchema
)
from etl.load import load_country_metadata, load_cases


@pytest.fixture
def mock_db_session():
    """Provides a clean in-memory SQLite session for testing database operations."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_standardize_country_name():
    """Verifies that country names are normalized according to dictionary mappings."""
    assert standardize_country_name("US") == "United States"
    assert standardize_country_name("Korea, South") == "South Korea"
    assert standardize_country_name("Taiwan*") == "Taiwan"
    assert standardize_country_name("Canada") == "Canada"
    assert standardize_country_name("  US  ") == "United States"


@mock.patch("etl.extract.requests.get")
def test_download_file_retry_and_timeout(mock_get, tmp_path):
    """Verifies that download_file handles timeouts and executes retries with backoff."""
    # Mock requests to fail once with timeout, then succeed
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.text = "Province/State,Country/Region,Lat,Long,1/22/20\n,US,37.0902,-95.7129,0" + (",0" * 50)
    
    mock_get.side_effect = [
        requests.RequestException("Timeout"),
        mock_response
    ]
    
    target_path = tmp_path / "confirmed.csv"
    download_file("http://dummy.url", target_path, timeout=5, max_retries=2, backoff_factor=1)
    
    assert target_path.exists()
    assert mock_get.call_count == 2


@mock.patch("etl.extract.requests.get")
def test_download_file_failure(mock_get, tmp_path):
    """Verifies that download_file raises DataExtractionError after exhausting retries."""
    mock_get.side_effect = requests.RequestException("Connection Refused")
    target_path = tmp_path / "failed.csv"
    
    with pytest.raises(DataExtractionError):
        download_file("http://dummy.url", target_path, timeout=5, max_retries=1, backoff_factor=1)


def test_transform_cases(tmp_path):
    """Verifies that transform_cases successfully transforms wide time-series formats."""
    # Generate mock wide JHU cases files
    confirmed_csv = tmp_path / "confirmed.csv"
    deaths_csv = tmp_path / "deaths.csv"
    recovered_csv = tmp_path / "recovered.csv"
    
    header = "Province/State,Country/Region,Lat,Long,1/22/20,1/23/20,1/24/20\n"
    conf_data = header + ",US,37.0,-95.0,1,5,12\n,\"Korea, South\",36.0,127.0,0,1,3\n"
    dead_data = header + ",US,37.0,-95.0,0,0,1\n,\"Korea, South\",36.0,127.0,0,0,0\n"
    recv_data = header + ",US,37.0,-95.0,0,1,2\n,\"Korea, South\",36.0,127.0,0,0,0\n"
    
    confirmed_csv.write_text(conf_data)
    deaths_csv.write_text(dead_data)
    recovered_csv.write_text(recv_data)
    
    df = transform_cases(confirmed_csv, deaths_csv, recovered_csv)
    
    # Assertions
    assert isinstance(df, pd.DataFrame)
    # Check that countries are standardized
    assert "United States" in df["country"].values
    assert "South Korea" in df["country"].values
    
    # Date columns should have melted to rows
    assert len(df) == 6  # 2 countries * 3 days = 6 rows
    
    # Check values for United States on 1/24/20 (2020-01-24)
    us_latest = df[(df["country"] == "United States") & (df["date"] == "2020-01-24")]
    assert len(us_latest) == 1
    assert us_latest.iloc[0]["cases"] == 12
    assert us_latest.iloc[0]["deaths"] == 1
    assert us_latest.iloc[0]["recovered"] == 2
    
    # Verify Pandera validation didn't raise exceptions
    DailyCasesSchema.validate(df)


def test_transform_country_metadata(tmp_path):
    """Verifies that transform_country_metadata compiles metadata and links first case dates."""
    countries_csv = tmp_path / "countries.csv"
    countries_csv.write_text("name;continent;population;alpha_3;capital\nUnited States;NA;331002651;USA;Washington\nSouth Korea;AS;51269185;KOR;Seoul\n")
    
    # Create mock daily cases df
    cases_df = pd.DataFrame([
        {"country": "United States", "date": pd.Timestamp("2020-01-22"), "cases": 0},
        {"country": "United States", "date": pd.Timestamp("2020-01-23"), "cases": 1},
        {"country": "South Korea", "date": pd.Timestamp("2020-01-22"), "cases": 0},
        {"country": "South Korea", "date": pd.Timestamp("2020-01-23"), "cases": 0},
        {"country": "South Korea", "date": pd.Timestamp("2020-01-24"), "cases": 3},
    ])
    
    df_meta = transform_country_metadata(countries_csv, cases_df)
    
    assert len(df_meta) == 2
    us_meta = df_meta[df_meta["country"] == "United States"].iloc[0]
    assert us_meta["continent"] == "North America"
    assert us_meta["population"] == 331002651
    # Check that first case date is derived correctly
    assert us_meta["first_case_date"] == pd.Timestamp("2020-01-23")


def test_database_load_idempotency(mock_db_session):
    """Tests that loading the same daily cases twice updates existing records instead of duplicating them."""
    # 1. Load mock country metadata first (foreign keys require it)
    meta_df = pd.DataFrame([
        {"country": "United States", "population": 331002651.0, "continent": "North America", "first_case_date": pd.Timestamp("2020-01-23")}
    ])
    load_country_metadata(mock_db_session, meta_df)
    mock_db_session.commit()
    
    # 2. Define mock cases data
    cases_df = pd.DataFrame([
        {"country": "United States", "date": pd.Timestamp("2020-01-22"), "cases": 10, "deaths": 1, "recovered": 0, "rolling_avg_7d": 1.4},
        {"country": "United States", "date": pd.Timestamp("2020-01-23"), "cases": 15, "deaths": 2, "recovered": 1, "rolling_avg_7d": 2.1}
    ])
    
    # Load first run
    load_cases(mock_db_session, cases_df)
    mock_db_session.commit()
    
    # Check count
    cnt1 = mock_db_session.query(DailyCases).count()
    assert cnt1 == 2
    
    # 3. Load second run (with updated cases count for 1/23)
    updated_cases_df = pd.DataFrame([
        {"country": "United States", "date": pd.Timestamp("2020-01-22"), "cases": 10, "deaths": 1, "recovered": 0, "rolling_avg_7d": 1.4},
        {"country": "United States", "date": pd.Timestamp("2020-01-23"), "cases": 20, "deaths": 2, "recovered": 1, "rolling_avg_7d": 2.5}  # updated cases & rolling avg
    ])
    
    load_cases(mock_db_session, updated_cases_df)
    mock_db_session.commit()
    
    # Count should STILL be 2, not 4 (idempotent upsert verification)
    cnt2 = mock_db_session.query(DailyCases).count()
    assert cnt2 == 2
    
    # Verify cases count updated
    record_latest = mock_db_session.query(DailyCases).filter(DailyCases.date == date(2020, 1, 23)).first()
    assert record_latest.cases == 20
    assert record_latest.rolling_avg_7d == 2.5

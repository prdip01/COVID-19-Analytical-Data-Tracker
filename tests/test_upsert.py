import pytest
import pandas as pd
from datetime import date
from database.models import DailyCases, Vaccinations
from etl.load import load_country_metadata, load_cases, load_vaccinations

def test_cases_upsert_preserves_id(clean_db, db_session):
    """Verify that re-running load_cases on duplicate country/date updates data while keeping ID stable."""
    # 1. Seed country metadata (foreign key constraint requirement)
    meta_df = pd.DataFrame([
        {"country": "United States", "population": 331002651.0, "continent": "North America", "first_case_date": pd.Timestamp("2020-01-22")}
    ])
    load_country_metadata(db_session, meta_df)
    db_session.commit()
    
    # 2. Load cases initial run
    cases_df = pd.DataFrame([
        {"country": "United States", "date": pd.Timestamp("2020-01-22"), "cases": 10, "deaths": 1, "recovered": 0, "rolling_avg_7d": 1.4}
    ])
    load_cases(db_session, cases_df)
    db_session.commit()
    
    # 3. Retrieve record and remember its primary key ID
    record1 = db_session.query(DailyCases).filter_by(country="United States", date=date(2020, 1, 22)).one()
    original_id = record1.id
    assert record1.cases == 10
    
    # 4. Load updated cases on same country/date
    updated_cases_df = pd.DataFrame([
        {"country": "United States", "date": pd.Timestamp("2020-01-22"), "cases": 15, "deaths": 2, "recovered": 1, "rolling_avg_7d": 1.9}
    ])
    load_cases(db_session, updated_cases_df)
    db_session.commit()
    
    # 5. Retrieve record again and assert ID is identical but data is updated
    db_session.expire_all()  # Force SQLAlchemy to refetch from DB
    record2 = db_session.query(DailyCases).filter_by(country="United States", date=date(2020, 1, 22)).one()
    assert record2.id == original_id
    assert record2.cases == 15
    assert record2.deaths == 2

def test_vaccinations_upsert_preserves_id(clean_db, db_session):
    """Verify that re-running load_vaccinations on duplicate country/date updates data while keeping ID stable."""
    # 1. Seed country metadata
    meta_df = pd.DataFrame([
        {"country": "United States", "population": 331002651.0, "continent": "North America", "first_case_date": pd.Timestamp("2020-01-22")}
    ])
    load_country_metadata(db_session, meta_df)
    db_session.commit()
    
    # 2. Load vaccinations initial run
    vax_df = pd.DataFrame([
        {
            "country": "United States",
            "date": pd.Timestamp("2020-01-22"),
            "total_vaccinations": 1000,
            "people_vaccinated": 800,
            "people_fully_vaccinated": 200,
            "daily_vaccinations": 100
        }
    ])
    load_vaccinations(db_session, vax_df)
    db_session.commit()
    
    # 3. Retrieve record and remember its primary key ID
    record1 = db_session.query(Vaccinations).filter_by(country="United States", date=date(2020, 1, 22)).one()
    original_id = record1.id
    assert record1.total_vaccinations == 1000
    
    # 4. Load updated vaccinations on same country/date
    updated_vax_df = pd.DataFrame([
        {
            "country": "United States",
            "date": pd.Timestamp("2020-01-22"),
            "total_vaccinations": 1500,
            "people_vaccinated": 1100,
            "people_fully_vaccinated": 400,
            "daily_vaccinations": 150
        }
    ])
    load_vaccinations(db_session, updated_vax_df)
    db_session.commit()
    
    # 5. Retrieve record again and assert ID is identical but data is updated
    db_session.expire_all()  # Force SQLAlchemy to refetch from DB
    record2 = db_session.query(Vaccinations).filter_by(country="United States", date=date(2020, 1, 22)).one()
    assert record2.id == original_id
    assert record2.total_vaccinations == 1500
    assert record2.people_vaccinated == 1100
    assert record2.people_fully_vaccinated == 400

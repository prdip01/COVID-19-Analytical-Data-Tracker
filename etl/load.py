"""
Database loading module for the COVID-19 Data Tracker ETL pipeline.

Implements dialect-aware bulk upsert operations to support SQLite and PostgreSQL
databases efficiently without deleting historical data. Logs insertion statistics.
"""

from datetime import datetime, timezone
import logging
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.models import CountryMetadata, DailyCases, Vaccinations

logger = logging.getLogger(__name__)


def load_country_metadata(db_session: Session, df: pd.DataFrame) -> int:
    """
    Inserts or updates country metadata profiles into the database.
    Since this dataset is relatively small (~250 rows), we use SQLAlchemy's
    session.merge to handle updates cleanly.
    
    Args:
        db_session: Active SQLAlchemy DB Session.
        df: Transformed country metadata DataFrame.
        
    Returns:
        The number of records processed.
    """
    logger.info("Loading country metadata records (total: %d)...", len(df))
    
    ingest_time = datetime.now(timezone.utc)
    records_count = 0
    
    try:
        for _, row in df.iterrows():
            # Convert first case date to python date
            first_case = None
            if not pd.isnull(row["first_case_date"]):
                # Handle potential string or Timestamp representation
                if isinstance(row["first_case_date"], str):
                    first_case = datetime.strptime(row["first_case_date"][:10], "%Y-%m-%d").date()
                else:
                    first_case = row["first_case_date"].to_pydatetime().date()
            
            # Construct model object
            country_obj = CountryMetadata(
                country=row["country"],
                population=int(row["population"]) if row["population"] > 0 else None,
                continent=row["continent"],
                first_case_date=first_case,
                ingested_at=ingest_time,
                source_file="countries.csv"
            )
            
            # merge checks if the primary key exists; if yes, updates it; if not, inserts it.
            db_session.merge(country_obj)
            records_count += 1
            
        logger.info("Successfully merged %d country metadata records.", records_count)
        return records_count
        
    except SQLAlchemyError as e:
        logger.error("Failed to load country metadata: %s", e)
        raise


def load_cases(db_session: Session, df: pd.DataFrame) -> int:
    """
    Loads daily cases data using a high-performance, dialect-aware bulk upsert.
    Saves DataFrame to a temporary table and performs a native merge.
    
    Args:
        db_session: Active SQLAlchemy DB Session.
        df: Transformed daily cases DataFrame.
        
    Returns:
        The number of records loaded.
    """
    total_records = len(df)
    logger.info("Initiating bulk load of daily cases (total: %d)...", total_records)
    
    try:
        # Convert date to string format to ensure consistency
        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["date"]).dt.strftime("%Y-%m-%d")
        
        # Write to temporary holding table
        temp_table_name = "temp_daily_cases"
        df_copy.to_sql(
            temp_table_name,
            con=db_session.connection(),
            if_exists="replace",
            index=False
        )
        
        dialect = db_session.bind.dialect.name
        ingest_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        source = "confirmed/deaths/recovered.csv"
        
        if dialect == "sqlite":
            logger.debug("Executing SQLite bulk ON CONFLICT upsert...")
            upsert_query = text(f"""
                INSERT INTO daily_cases (
                    country, date, cases, deaths, recovered, rolling_avg_7d, ingested_at, source_file
                )
                SELECT 
                    country, DATE(date), CAST(cases AS INTEGER), CAST(deaths AS INTEGER), 
                    CAST(recovered AS INTEGER), CAST(rolling_avg_7d AS REAL), :ingested_at, :source
                FROM {temp_table_name}
                WHERE 1
                ON CONFLICT (country, date) DO UPDATE SET
                    cases = EXCLUDED.cases,
                    deaths = EXCLUDED.deaths,
                    recovered = EXCLUDED.recovered,
                    rolling_avg_7d = EXCLUDED.rolling_avg_7d,
                    ingested_at = EXCLUDED.ingested_at,
                    source_file = EXCLUDED.source_file
            """)
        else:
            logger.debug("Executing PostgreSQL bulk ON CONFLICT upsert...")
            upsert_query = text(f"""
                INSERT INTO daily_cases (
                    country, date, cases, deaths, recovered, rolling_avg_7d, ingested_at, source_file
                )
                SELECT 
                    country, DATE(date), CAST(cases AS INTEGER), CAST(deaths AS INTEGER), 
                    CAST(recovered AS INTEGER), CAST(rolling_avg_7d AS DOUBLE PRECISION), :ingested_at, :source
                FROM {temp_table_name}
                WHERE 1
                ON CONFLICT (country, date) DO UPDATE SET
                    cases = EXCLUDED.cases,
                    deaths = EXCLUDED.deaths,
                    recovered = EXCLUDED.recovered,
                    rolling_avg_7d = EXCLUDED.rolling_avg_7d,
                    ingested_at = EXCLUDED.ingested_at,
                    source_file = EXCLUDED.source_file
            """)
            
        db_session.execute(upsert_query, {"ingested_at": ingest_time, "source": source})
        
        # Clean up temporary table
        db_session.execute(text(f"DROP TABLE {temp_table_name}"))
        
        logger.info("Successfully bulk loaded %d daily case records.", total_records)
        return total_records

    except SQLAlchemyError as e:
        logger.error("Failed to bulk load daily cases: %s", e)
        raise


def load_vaccinations(db_session: Session, df: pd.DataFrame) -> int:
    """
    Loads vaccinations data using a high-performance, dialect-aware bulk upsert.
    Saves DataFrame to a temporary table and performs a native merge.
    
    Args:
        db_session: Active SQLAlchemy DB Session.
        df: Transformed vaccinations DataFrame.
        
    Returns:
        The number of records loaded.
    """
    total_records = len(df)
    logger.info("Initiating bulk load of vaccinations (total: %d)...", total_records)
    
    try:
        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["date"]).dt.strftime("%Y-%m-%d")
        
        temp_table_name = "temp_vaccinations"
        df_copy.to_sql(
            temp_table_name,
            con=db_session.connection(),
            if_exists="replace",
            index=False
        )
        
        dialect = db_session.bind.dialect.name
        ingest_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        source = "vaccinations.csv"
        
        if dialect == "sqlite":
            logger.debug("Executing SQLite bulk ON CONFLICT upsert for vaccinations...")
            upsert_query = text(f"""
                INSERT INTO vaccinations (
                    country, date, total_vaccinations, people_vaccinated, 
                    people_fully_vaccinated, daily_vaccinations, ingested_at, source_file
                )
                SELECT 
                    country, DATE(date), CAST(total_vaccinations AS INTEGER), 
                    CAST(people_vaccinated AS INTEGER), CAST(people_fully_vaccinated AS INTEGER), 
                    CAST(daily_vaccinations AS INTEGER), :ingested_at, :source
                FROM {temp_table_name}
                WHERE 1
                ON CONFLICT (country, date) DO UPDATE SET
                    total_vaccinations = EXCLUDED.total_vaccinations,
                    people_vaccinated = EXCLUDED.people_vaccinated,
                    people_fully_vaccinated = EXCLUDED.people_fully_vaccinated,
                    daily_vaccinations = EXCLUDED.daily_vaccinations,
                    ingested_at = EXCLUDED.ingested_at,
                    source_file = EXCLUDED.source_file
            """)
        else:
            logger.debug("Executing PostgreSQL bulk ON CONFLICT upsert for vaccinations...")
            upsert_query = text(f"""
                INSERT INTO vaccinations (
                    country, date, total_vaccinations, people_vaccinated, 
                    people_fully_vaccinated, daily_vaccinations, ingested_at, source_file
                )
                SELECT 
                    country, DATE(date), CAST(total_vaccinations AS BIGINT), 
                    CAST(people_vaccinated AS BIGINT), CAST(people_fully_vaccinated AS BIGINT), 
                    CAST(daily_vaccinations AS BIGINT), :ingested_at, :source
                FROM {temp_table_name}
                WHERE 1
                ON CONFLICT (country, date) DO UPDATE SET
                    total_vaccinations = EXCLUDED.total_vaccinations,
                    people_vaccinated = EXCLUDED.people_vaccinated,
                    people_fully_vaccinated = EXCLUDED.people_fully_vaccinated,
                    daily_vaccinations = EXCLUDED.daily_vaccinations,
                    ingested_at = EXCLUDED.ingested_at,
                    source_file = EXCLUDED.source_file
            """)
            
        db_session.execute(upsert_query, {"ingested_at": ingest_time, "source": source})
        db_session.execute(text(f"DROP TABLE {temp_table_name}"))
        
        logger.info("Successfully bulk loaded %d vaccination records.", total_records)
        return total_records

    except SQLAlchemyError as e:
        logger.error("Failed to bulk load vaccinations: %s", e)
        raise

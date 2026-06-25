"""
SQLAlchemy models for the COVID-19 Data Tracker.

Defines schemas for country metadata, daily cases/deaths/recovery data,
and vaccination progress. Includes data lineage metadata fields.
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Float,
    String,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CountryMetadata(Base):
    """
    Metadata for each country, including continent, population, and first case date.
    Used for filtering, scaling metrics, and mapping.
    """
    __tablename__ = "country_metadata"

    country = Column(String, primary_key=True, index=True)
    population = Column(BigInteger, nullable=True)
    continent = Column(String, nullable=True)
    first_case_date = Column(Date, nullable=True)
    
    # Data lineage tracking
    ingested_at = Column(DateTime, default=func.now(), nullable=False)
    source_file = Column(String, nullable=True)

    # Relationships
    daily_cases = relationship(
        "DailyCases", back_populates="country_meta", cascade="all, delete-orphan"
    )
    vaccinations = relationship(
        "Vaccinations", back_populates="country_meta", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<CountryMetadata(country='{self.country}', continent='{self.continent}', population={self.population})>"


class DailyCases(Base):
    """
    Time-series table storing daily cumulative and daily calculated cases,
    deaths, recovered counts, and 7-day rolling averages.
    """
    __tablename__ = "daily_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String, ForeignKey("country_metadata.country"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Cumulative stats
    cases = Column(Integer, default=0, nullable=False)
    deaths = Column(Integer, default=0, nullable=False)
    recovered = Column(Integer, default=0, nullable=False)
    
    # Analytical stats
    rolling_avg_7d = Column(Float, default=0.0, nullable=False)

    # Data lineage tracking
    ingested_at = Column(DateTime, default=func.now(), nullable=False)
    source_file = Column(String, nullable=True)

    # Composite unique constraint to prevent duplicate country-date entries
    __table_args__ = (
        UniqueConstraint("country", "date", name="uq_country_date_cases"),
    )

    # Relationships
    country_meta = relationship("CountryMetadata", back_populates="daily_cases")

    def __repr__(self) -> str:
        return f"<DailyCases(country='{self.country}', date='{self.date}', cases={self.cases})>"


class Vaccinations(Base):
    """
    Time-series table storing vaccination metrics including first doses,
    fully vaccinated progress, and daily doses administered.
    """
    __tablename__ = "vaccinations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String, ForeignKey("country_metadata.country"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Vaccination stats
    total_vaccinations = Column(BigInteger, nullable=True)
    people_vaccinated = Column(BigInteger, nullable=True)
    people_fully_vaccinated = Column(BigInteger, nullable=True)
    daily_vaccinations = Column(BigInteger, nullable=True)

    # Data lineage tracking
    ingested_at = Column(DateTime, default=func.now(), nullable=False)
    source_file = Column(String, nullable=True)

    # Composite unique constraint
    __table_args__ = (
        UniqueConstraint("country", "date", name="uq_country_date_vaccinations"),
    )

    # Relationships
    country_meta = relationship("CountryMetadata", back_populates="vaccinations")

    def __repr__(self) -> str:
        return f"<Vaccinations(country='{self.country}', date='{self.date}', fully_vaccinated={self.people_fully_vaccinated})>"

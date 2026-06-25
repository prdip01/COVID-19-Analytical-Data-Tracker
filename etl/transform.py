"""
Data transformation module for the COVID-19 Data Tracker ETL pipeline.

Converts JHU wide time-series CSVs into long database formats, aggregates
province data, standardizes country names, calculates daily new cases and 7-day
rolling averages, processes vaccinations, and validates schemas using Pandera.
"""

import logging
from pathlib import Path
from typing import Dict, Tuple
import numpy as np
import pandas as pd
import pandera as pa
from pandera.typing import DataFrame, Series

logger = logging.getLogger(__name__)

# --- Standardization Mappings ---
COUNTRY_NAME_MAPPING = {
    "US": "United States",
    "Korea, South": "South Korea",
    "Taiwan*": "Taiwan",
    "West Bank and Gaza": "Palestine",
    "Burma": "Myanmar",
    "Congo (Kinshasa)": "Democratic Republic of the Congo",
    "Congo (Brazzaville)": "Republic of the Congo",
    "Cote d'Ivoire": "Ivory Coast",
    "Saint Kitts and Nevis": "St. Kitts and Nevis",
    "Saint Vincent and the Grenadines": "St. Vincent and the Grenadines",
    "Sao Tome and Principe": "Sao Tome & Principe",
}

# Regional location exclusions in Our World in Data vaccinations
OWID_REGIONS_EXCLUDE = {
    "World", "Europe", "Asia", "North America", "South America", "Africa",
    "Oceania", "European Union", "High income", "Upper middle income",
    "Lower middle income", "Low income", "North America (OWID)",
    "South America (OWID)", "Europe (OWID)", "Asia (OWID)", "Africa (OWID)"
}

# --- Pandera Validation Schemas ---

class DailyCasesSchema(pa.DataFrameModel):
    """Pandera validation schema for cleaned daily cases DataFrame."""
    country: Series[str] = pa.Field(coerce=True)
    date: Series[pa.DateTime] = pa.Field(coerce=True)
    cases: Series[int] = pa.Field(ge=0, coerce=True)
    deaths: Series[int] = pa.Field(ge=0, coerce=True)
    recovered: Series[int] = pa.Field(ge=0, coerce=True)
    rolling_avg_7d: Series[float] = pa.Field(ge=0.0, coerce=True)

    class Config:
        strict = True
        coerce = True


class CountryMetadataSchema(pa.DataFrameModel):
    """Pandera validation schema for country metadata DataFrame."""
    country: Series[str] = pa.Field(unique=True, coerce=True)
    population: Series[float] = pa.Field(nullable=True, coerce=True)  # Float because of potential NaNs in raw
    continent: Series[str] = pa.Field(coerce=True)
    first_case_date: Series[pa.DateTime] = pa.Field(coerce=True, nullable=True)

    class Config:
        strict = True
        coerce = True


class VaccinationsSchema(pa.DataFrameModel):
    """Pandera validation schema for country vaccinations DataFrame."""
    country: Series[str] = pa.Field(coerce=True)
    date: Series[pa.DateTime] = pa.Field(coerce=True)
    total_vaccinations: Series[float] = pa.Field(nullable=True, coerce=True)
    people_vaccinated: Series[float] = pa.Field(nullable=True, coerce=True)
    people_fully_vaccinated: Series[float] = pa.Field(nullable=True, coerce=True)
    daily_vaccinations: Series[float] = pa.Field(nullable=True, coerce=True)

    class Config:
        strict = True
        coerce = True


def standardize_country_name(name: str) -> str:
    """
    Standardizes country names according to standard vocabulary mapping.
    """
    cleaned = str(name).strip()
    return COUNTRY_NAME_MAPPING.get(cleaned, cleaned)


def detect_cases_anomalies(df: pd.DataFrame) -> None:
    """
    Scans the daily cases dataframe for anomalies (impossible values, negative cumulative sums, spikes).
    Logs warnings for detected anomalies.
    """
    logger.info("Running anomaly detection on cases data...")
    
    # 1. Negative cumulative numbers
    neg_cases = df[df["cases"] < 0]
    if not neg_cases.empty:
        logger.warning(
            "Anomaly detected: %d records found with negative cumulative cases. Example: %s",
            len(neg_cases), neg_cases.iloc[0].to_dict()
        )
        
    neg_deaths = df[df["deaths"] < 0]
    if not neg_deaths.empty:
        logger.warning(
            "Anomaly detected: %d records found with negative cumulative deaths. Example: %s",
            len(neg_deaths), neg_deaths.iloc[0].to_dict()
        )

    # 2. Daily new cases calculation sanity check
    # Let's check for cases where daily cases decrease (negative diff)
    df_sorted = df.sort_values(["country", "date"])
    df_sorted["new_cases"] = df_sorted.groupby("country")["cases"].diff()
    neg_new_cases = df_sorted[df_sorted["new_cases"] < 0]
    if not neg_new_cases.empty:
        logger.debug(
            "Data note: %d instances of daily cases adjustments (cumulative cases decreased). Example: %s",
            len(neg_new_cases), neg_new_cases.iloc[0].to_dict()
        )
        
    # 3. Impossible daily spikes (e.g. single day new cases > 5,000,000)
    huge_spikes = df_sorted[df_sorted["new_cases"] > 5_000_000]
    if not huge_spikes.empty:
        logger.warning(
            "Anomaly detected: %d instances of daily new cases exceeding 5 million. Example: %s",
            len(huge_spikes), huge_spikes.iloc[0].to_dict()
        )


def transform_cases(
    confirmed_path: Path,
    deaths_path: Path,
    recovered_path: Path
) -> pd.DataFrame:
    """
    Melts and combines global confirmed, deaths, and recovered data files.
    Aggregates data to country level and calculates the 7-day rolling average.
    
    Returns:
        Validated cases DataFrame.
    """
    logger.info("Transforming cumulative case files...")
    
    # Read files
    df_conf = pd.read_csv(confirmed_path)
    df_dead = pd.read_csv(deaths_path)
    df_recv = pd.read_csv(recovered_path)
    
    id_vars = ["Province/State", "Country/Region", "Lat", "Long"]
    
    def melt_df(df: pd.DataFrame, value_name: str) -> pd.DataFrame:
        # Melt date columns into rows
        melted = df.melt(id_vars=id_vars, var_name="Date", value_name=value_name)
        melted["Date"] = pd.to_datetime(melted["Date"], format="%m/%d/%y")
        # Standardize country name
        melted["country"] = melted["Country/Region"].apply(standardize_country_name)
        # Group by country and date to sum states/provinces together
        aggregated = (
            melted.groupby(["country", "Date"])[value_name]
            .sum()
            .reset_index()
        )
        return aggregated

    logger.debug("Melting confirmed, deaths, and recovered dataframes...")
    cases_long = melt_df(df_conf, "cases")
    deaths_long = melt_df(df_dead, "deaths")
    recv_long = melt_df(df_recv, "recovered")
    
    # Merge all three time series dataframes
    merged = pd.merge(cases_long, deaths_long, on=["country", "Date"], how="outer")
    merged = pd.merge(merged, recv_long, on=["country", "Date"], how="outer")
    
    # Fill missing values and convert back to integer
    merged = merged.fillna(0)
    for col in ["cases", "deaths", "recovered"]:
        merged[col] = merged[col].astype(int)
        # Convert any negative cumulative values to 0 (e.g. JHU corrections using -1)
        merged.loc[merged[col] < 0, col] = 0
        
    merged = merged.rename(columns={"Date": "date"})
    
    # --- Calculate 7-Day Rolling Average ---
    logger.debug("Calculating 7-day rolling average for daily new cases...")
    # Sort data chronologically per country
    merged = merged.sort_values(["country", "date"])
    
    # Calculate daily new cases (difference between cumulative days)
    merged["new_cases"] = merged.groupby("country")["cases"].diff().fillna(merged["cases"])
    
    # Clean negative new cases (some retrospective corrections happen in dataset)
    merged.loc[merged["new_cases"] < 0, "new_cases"] = 0
    
    # Calculate 7-day rolling average of daily new cases
    merged["rolling_avg_7d"] = (
        merged.groupby("country")["new_cases"]
        .transform(lambda x: x.rolling(window=7, min_periods=1).mean())
    )
    
    # Cleanup intermediate columns
    merged = merged.drop(columns=["new_cases"])
    
    # Perform anomaly audits
    detect_cases_anomalies(merged)
    
    # Validate with Pandera Schema
    logger.info("Validating daily cases data against Pandera schema...")
    validated_df = DailyCasesSchema.validate(merged)
    
    return validated_df


def transform_country_metadata(
    countries_path: Path,
    cases_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Transforms country profiles from raw country list, standardizes names,
    and extracts first case date from the cases DataFrame.
    
    Returns:
        Validated country metadata DataFrame.
    """
    logger.info("Transforming country metadata...")
    
    # Read country list (CSV structure: name, continent, population, alpha_3, capital)
    # The raw file uses a semicolon (;) delimiter.
    # We set keep_default_na=False to prevent "NA" (North America) from being parsed as NaN.
    df_raw = pd.read_csv(countries_path, sep=";", keep_default_na=False)
    
    # Map continent abbreviations to full names
    continent_map = {
        "AF": "Africa",
        "AN": "Antarctica",
        "AS": "Asia",
        "EU": "Europe",
        "NA": "North America",
        "OC": "Oceania",
        "SA": "South America"
    }
    df_raw["continent"] = df_raw["continent"].map(continent_map).fillna("Unknown")
    
    # Select and rename columns
    df_meta = df_raw[["name", "continent", "population"]].copy()
    df_meta["country"] = df_meta["name"].apply(standardize_country_name)
    df_meta["population"] = pd.to_numeric(df_meta["population"], errors="coerce")
    df_meta = df_meta.drop(columns=["name"])
    
    # Keep only the largest entry in case of duplicate mappings
    df_meta = df_meta.drop_duplicates(subset=["country"])
    
    # Extract first case dates from daily cases
    logger.debug("Extracting first case dates per country...")
    cases_active = cases_df[cases_df["cases"] > 0]
    if not cases_active.empty:
        first_case_series = (
            cases_active.groupby("country")["date"]
            .min()
            .reset_index()
            .rename(columns={"date": "first_case_date"})
        )
        df_meta = pd.merge(df_meta, first_case_series, on="country", how="outer")
    else:
        df_meta["first_case_date"] = pd.NaT

    # Complete missing metadata fields
    df_meta["population"] = df_meta["population"].fillna(0.0)
    df_meta["continent"] = df_meta["continent"].fillna("Unknown")
    
    # Make sure all countries appearing in cases_df exist in metadata
    unique_cases_countries = cases_df["country"].unique()
    existing_meta_countries = df_meta["country"].unique()
    
    missing_countries = set(unique_cases_countries) - set(existing_meta_countries)
    if missing_countries:
        logger.warning(
            "Found %d countries in cases data missing from raw metadata list. Adding default entries. Countries: %s",
            len(missing_countries), list(missing_countries)[:10]
        )
        missing_rows = []
        for c in missing_countries:
            missing_rows.append({
                "country": c,
                "population": 0.0,
                "continent": "Unknown",
                "first_case_date": cases_df[(cases_df["country"] == c) & (cases_df["cases"] > 0)]["date"].min()
            })
        df_meta = pd.concat([df_meta, pd.DataFrame(missing_rows)], ignore_index=True)

    # Validate with Pandera
    logger.info("Validating country metadata against Pandera schema...")
    validated_df = CountryMetadataSchema.validate(df_meta)
    
    return validated_df


def transform_vaccinations(vaccinations_path: Path) -> pd.DataFrame:
    """
    Transforms Our World in Data vaccination data.
    Filters regional aggregated categories, standardizes location names,
    fills missing records using forward fill logic.
    
    Returns:
        Validated vaccinations DataFrame.
    """
    logger.info("Transforming vaccination dataset...")
    
    # Read OWID vaccinations file
    # Columns expected: location, date, total_vaccinations, people_vaccinated, people_fully_vaccinated, daily_vaccinations
    df = pd.read_csv(vaccinations_path)
    
    # Filter regional aggregations
    df = df[~df["location"].isin(OWID_REGIONS_EXCLUDE)]
    
    # Standardize country name
    df["country"] = df["location"].apply(standardize_country_name)
    df["date"] = pd.to_datetime(df["date"])
    
    # Select columns
    cols = ["country", "date", "total_vaccinations", "people_vaccinated", "people_fully_vaccinated", "daily_vaccinations"]
    df_filtered = df[[c for c in df.columns if c in cols]].copy()
    
    # Ensure all target columns exist (in case raw names change)
    for col in ["total_vaccinations", "people_vaccinated", "people_fully_vaccinated", "daily_vaccinations"]:
        if col not in df_filtered.columns:
            df_filtered[col] = np.nan
            
    df_filtered = df_filtered[cols]
    
    # Sort chronologically to prepare for forward fill
    df_filtered = df_filtered.sort_values(["country", "date"])
    
    # For missing values, forward fill per country (cumulative stats), then fill remaining with NaN
    # We don't fill daily_vaccinations with forward fill since it is daily, fill with 0 instead
    cumulative_cols = ["total_vaccinations", "people_vaccinated", "people_fully_vaccinated"]
    df_filtered[cumulative_cols] = df_filtered.groupby("country")[cumulative_cols].ffill()
    
    # Fill remaining NaNs with 0
    df_filtered = df_filtered.fillna(0.0)
    
    # Validate with Pandera
    logger.info("Validating vaccinations data against Pandera schema...")
    validated_df = VaccinationsSchema.validate(df_filtered)
    
    return validated_df

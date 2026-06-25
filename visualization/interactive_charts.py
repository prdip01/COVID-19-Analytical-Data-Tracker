"""
Interactive chart generation module for the COVID-19 Data Tracker.

Uses Plotly to construct interactive charts, serialized to JSON for client-side
rendering via Plotly.js. Supported charts include multi-country time series comparisons
and global vaccination coverage choropleth maps.
"""

import json
import logging
from typing import List, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.utils
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --- Design Configuration ---
PLOTLY_TEMPLATE = "plotly_dark"
COLOR_SEQUENCE = ["#6366f1", "#3b82f6", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6"]


def generate_cases_interactive(
    db_session: Session,
    countries: List[str],
    metric: str = "cases",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    Creates an interactive Plotly line chart comparing case data for selected countries.
    
    Args:
        db_session: Active SQLAlchemy Session.
        countries: List of country names to plot.
        metric: Column to plot ('cases', 'deaths', 'recovered', 'rolling_avg_7d').
        start_date: Start filter date (YYYY-MM-DD).
        end_date: End filter date (YYYY-MM-DD).
        
    Returns:
        JSON string representation of the Plotly figure.
    """
    logger.info(
        "Generating interactive case chart. Countries: %s, Metric: %s",
        countries, metric
    )
    
    if not countries:
        # Default fallback
        countries = ["United States"]

    # Build parameterized SQL query based on filters
    # Generate dynamic named placeholders for the IN clause to support lists on SQLite/PostgreSQL
    placeholders = ", ".join(f":c{i}" for i in range(len(countries)))
    query_str = f"""
        SELECT country, date, cases, deaths, recovered, rolling_avg_7d 
        FROM daily_cases 
        WHERE country IN ({placeholders})
    """
    params = {f"c{i}": c for i, c in enumerate(countries)}
    
    if start_date:
        query_str += " AND date >= :start_date"
        params["start_date"] = start_date
    if end_date:
        query_str += " AND date <= :end_date"
        params["end_date"] = end_date
        
    query_str += " ORDER BY country, date"
    
    df = pd.read_sql(text(query_str), con=db_session.connection(), params=params)
    df["date"] = pd.to_datetime(df["date"])
    
    if df.empty:
        # Return empty figure
        fig = go.Figure()
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            title="No data found for the selected filters",
            xaxis_title="Date",
            yaxis_title=metric.capitalize()
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    # If the user selected 'rolling_avg_7d', we are displaying daily new cases rolling average.
    # Otherwise, we might want to calculate daily new cases/deaths dynamically or display cumulative.
    # Standard labels:
    metric_labels = {
        "cases": "Cumulative Confirmed Cases",
        "deaths": "Cumulative Deaths",
        "recovered": "Cumulative Recovered Cases",
        "rolling_avg_7d": "Daily New Cases (7-Day Rolling Average)"
    }
    y_label = metric_labels.get(metric, metric.capitalize())

    fig = px.line(
        df,
        x="date",
        y=metric,
        color="country",
        color_discrete_sequence=COLOR_SEQUENCE,
        labels={"date": "Date", metric: y_label, "country": "Country"},
        template=PLOTLY_TEMPLATE
    )
    
    # Customize layout
    fig.update_layout(
        title={
            "text": f"COVID-19 Trend Comparison: {y_label}",
            "y": 0.95,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
            "font": {"size": 16}
        },
        legend={"orientation": "h", "y": -0.2, "x": 0.5, "xanchor": "center"},
        xaxis={"showgrid": True, "gridcolor": "rgba(255, 255, 255, 0.1)"},
        yaxis={"showgrid": True, "gridcolor": "rgba(255, 255, 255, 0.1)"},
        margin={"t": 50, "b": 100, "l": 50, "r": 50},
        hovermode="x unified"
    )
    
    # Add date range selector buttons
    fig.update_xaxes(
        rangeselector={
            "buttons": list([
                {"count": 1, "label": "1m", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6m", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "1y", "step": "year", "stepmode": "backward"},
                {"step": "all"}
            ]),
            "bgcolor": "#2d2d38",
            "activecolor": "#6366f1",
            "font": {"color": "#e2e8f0"}
        }
    )
    
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def generate_vaccination_progress_interactive(db_session: Session) -> str:
    """
    Creates an interactive global choropleth map showing vaccination progress.
    Plots the latest percentage of the population that is fully vaccinated.
    """
    logger.info("Generating interactive global vaccination choropleth map...")
    
    # Query database to get latest vaccination numbers and population per country
    query = text("""
        WITH LatestVax AS (
            SELECT country, date, people_fully_vaccinated,
                   ROW_NUMBER() OVER (PARTITION BY country ORDER BY date DESC) as rn
            FROM vaccinations
            WHERE people_fully_vaccinated > 0
        )
        SELECT 
            v.country, 
            v.people_fully_vaccinated,
            m.population,
            m.continent
        FROM LatestVax v
        JOIN country_metadata m ON v.country = m.country
        WHERE v.rn = 1 AND m.population > 0
    """)
    df = pd.read_sql(query, con=db_session.bind)
    
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            title="No vaccination data loaded yet"
        )
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
    # Calculate fully vaccinated percentage
    df["fully_vaccinated_pct"] = (df["people_fully_vaccinated"] / df["population"]) * 100
    # Cap at 100% (some reporting overlaps can exceed 100% theoretically)
    df.loc[df["fully_vaccinated_pct"] > 100.0, "fully_vaccinated_pct"] = 100.0
    
    # Add hover text details
    df["hover_text"] = (
        df["country"] + "<br>" +
        "Continent: " + df["continent"] + "<br>" +
        "Fully Vaccinated: " + df["people_fully_vaccinated"].apply(lambda x: f"{x:,.0f}") + "<br>" +
        "Population: " + df["population"].apply(lambda x: f"{x:,.0f}") + "<br>" +
        "Coverage: " + df["fully_vaccinated_pct"].map("{:.2f}%".format)
    )

    # Plot choropleth map using Plotly express
    fig = px.choropleth(
        df,
        locations="country",
        locationmode="country names",
        color="fully_vaccinated_pct",
        hover_name="country",
        hover_data={"fully_vaccinated_pct": False, "country": False, "hover_text": True},
        color_continuous_scale=px.colors.sequential.Plasma,
        range_color=[0, 100],
        labels={"fully_vaccinated_pct": "% Fully Vaccinated"},
        template=PLOTLY_TEMPLATE
    )
    
    # Customize design
    fig.update_layout(
        title={
            "text": "Global COVID-19 Vaccination Coverage (% Fully Vaccinated)",
            "y": 0.95,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
            "font": {"size": 16}
        },
        coloraxis_colorbar={
            "title": "% Coverage",
            "thickness": 15,
            "len": 0.6,
            "x": 0.9
        },
        geo={
            "showframe": False,
            "showcoastlines": True,
            "projection_type": "equirectangular",
            "bgcolor": "#1e1e24",
            "lakecolor": "#1e1e24",
            "landcolor": "#2d2d38",
            "coastlinecolor": "#475569"
        },
        margin={"t": 50, "b": 20, "l": 0, "r": 0}
    )
    
    # Update hover template to only show our custom text
    fig.update_traces(
        hovertemplate="%{customdata[0]}"
    )
    
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

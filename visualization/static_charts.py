"""
Static chart generation module for the COVID-19 Data Tracker.

Uses Matplotlib and Seaborn to generate publication-quality static charts,
including global trend charts, top-10 country bar charts, regional heatmaps,
and grid-based country comparisons. Supports dark mode theme styling.
"""

import io
import logging
from pathlib import Path
from typing import List, Optional
import matplotlib
# Set matplotlib backend to non-interactive Agg to prevent GUI threading errors in Flask
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --- Design Configuration ---
DARK_PALETTE = {
    "background": "#1e1e24",
    "card_bg": "#2d2d38",
    "text": "#e2e8f0",
    "primary": "#6366f1",    # Indigo
    "secondary": "#3b82f6",  # Blue
    "accent": "#f59e0b",     # Amber
    "grid": "#475569"
}

def apply_dark_theme() -> None:
    """
    Applies a clean, modern dark aesthetic style to matplotlib plots.
    """
    sns.set_theme(style="darkgrid", rc={
        "figure.facecolor": DARK_PALETTE["background"],
        "axes.facecolor": DARK_PALETTE["card_bg"],
        "text.color": DARK_PALETTE["text"],
        "axes.labelcolor": DARK_PALETTE["text"],
        "xtick.color": DARK_PALETTE["text"],
        "ytick.color": DARK_PALETTE["text"],
        "grid.color": DARK_PALETTE["grid"],
        "grid.linestyle": "--",
        "grid.alpha": 0.5,
        "axes.edgecolor": DARK_PALETTE["grid"]
    })


def generate_global_trend_chart(db_session: Session, save_path: Optional[Path] = None) -> io.BytesIO:
    """
    Generates a line chart of global daily cases with a 7-day rolling average.
    
    Returns:
        BytesIO buffer containing the PNG image data.
    """
    logger.info("Generating global trend static chart...")
    apply_dark_theme()
    
    # Query database for global cases aggregated by date
    query = text("""
        SELECT date, SUM(cases) as total_cases 
        FROM daily_cases 
        GROUP BY date 
        ORDER BY date
    """)
    df = pd.read_sql(query, con=db_session.bind)
    df["date"] = pd.to_datetime(df["date"])
    
    # Calculate daily new cases (cumulative difference)
    df["new_cases"] = df["total_cases"].diff().fillna(df["total_cases"])
    df.loc[df["new_cases"] < 0, "new_cases"] = 0
    
    # Calculate rolling 7 day average
    df["rolling_avg_7d"] = df["new_cases"].rolling(window=7, min_periods=1).mean()
    
    # Create plot
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    
    # Plot daily new cases as bars and rolling avg as line
    ax.bar(df["date"], df["new_cases"], color=DARK_PALETTE["secondary"], alpha=0.3, label="Daily New Cases")
    ax.plot(df["date"], df["rolling_avg_7d"], color=DARK_PALETTE["primary"], linewidth=2, label="7-Day Rolling Average")
    
    ax.set_title("Global Daily New Cases & 7-Day Rolling Average", fontsize=14, pad=15, color=DARK_PALETTE["text"])
    ax.set_xlabel("Date", fontsize=11, labelpad=10)
    ax.set_ylabel("New Cases Count", fontsize=11, labelpad=10)
    ax.legend(facecolor=DARK_PALETTE["card_bg"], edgecolor=DARK_PALETTE["grid"], labelcolor=DARK_PALETTE["text"])
    
    plt.tight_layout()
    
    # Save to file if path provided
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, facecolor=fig.get_facecolor(), edgecolor="none")
        logger.info("Saved global trend chart to %s", save_path)
        
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_top_countries_bar(db_session: Session, save_path: Optional[Path] = None) -> io.BytesIO:
    """
    Generates a horizontal bar chart of the top 10 countries by total cases.
    """
    logger.info("Generating top countries bar static chart...")
    apply_dark_theme()
    
    # Query for latest total cases per country
    query = text("""
        WITH LatestDate AS (
            SELECT MAX(date) as max_date FROM daily_cases
        )
        SELECT country, cases 
        FROM daily_cases 
        WHERE date = (SELECT max_date FROM LatestDate)
        ORDER BY cases DESC 
        LIMIT 10
    """)
    df = pd.read_sql(query, con=db_session.bind)
    
    # Plot horizontal bar
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    
    # Reverse order so highest is on top
    df_sorted = df.iloc[::-1]
    
    bars = ax.barh(df_sorted["country"], df_sorted["cases"] / 1_000_000, color=DARK_PALETTE["primary"])
    
    # Add values on bar ends
    for bar in bars:
        width = bar.get_width()
        ax.text(
            width + 0.5,
            bar.get_y() + bar.get_height()/2,
            f"{width:.1f}M",
            va="center",
            ha="left",
            fontsize=9,
            color=DARK_PALETTE["text"]
        )
        
    ax.set_title("Top 10 Countries by Total Confirmed Cases", fontsize=14, pad=15, color=DARK_PALETTE["text"])
    ax.set_xlabel("Total Confirmed Cases (Millions)", fontsize=11, labelpad=10)
    ax.set_ylabel("Country", fontsize=11, labelpad=10)
    
    plt.tight_layout()
    
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, facecolor=fig.get_facecolor(), edgecolor="none")
        logger.info("Saved top countries chart to %s", save_path)
        
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_cases_heatmap(db_session: Session, save_path: Optional[Path] = None) -> io.BytesIO:
    """
    Generates a heatmap of cases aggregated by month and continent.
    """
    logger.info("Generating continent/month cases heatmap...")
    apply_dark_theme()
    
    # Query case records joined with country metadata to aggregate by continent and month
    # We will compute monthly cases as the increase in cumulative cases within the month
    query = text("""
        SELECT 
            m.continent,
            strftime('%Y-%m', c.date) as month,
            MAX(c.cases) - MIN(c.cases) as monthly_new_cases
        FROM daily_cases c
        JOIN country_metadata m ON c.country = m.country
        WHERE m.continent != 'Unknown' AND m.continent IS NOT NULL
        GROUP BY m.continent, month
        ORDER BY month, m.continent
    """)
    df = pd.read_sql(query, con=db_session.bind)
    
    # Pivot to shape: index = continent, columns = month
    # We will filter to only include years 2020 to 2023 to keep it readable
    df = df[(df["month"] >= "2020-01") & (df["month"] <= "2023-03")]
    
    # Clean possible negative monthly increases due to retrospective data dumps
    df.loc[df["monthly_new_cases"] < 0, "monthly_new_cases"] = 0
    
    # Pivot
    pivot_df = df.pivot(index="continent", columns="month", values="monthly_new_cases").fillna(0)
    
    # Convert numbers to millions for scaling
    pivot_df_m = pivot_df / 1_000_000
    
    fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
    
    # Custom color map matching primary/accent colors
    cmap = sns.dark_palette(DARK_PALETTE["primary"], as_cmap=True)
    
    sns.heatmap(
        pivot_df_m,
        annot=True,
        fmt=".1f",
        linewidths=0.5,
        cmap=cmap,
        ax=ax,
        cbar_kws={"label": "New Cases in Millions"}
    )
    
    ax.set_title("COVID-19 Monthly New Cases by Continent (Millions)", fontsize=14, pad=15, color=DARK_PALETTE["text"])
    ax.set_xlabel("Month", fontsize=11, labelpad=10)
    ax.set_ylabel("Continent", fontsize=11, labelpad=10)
    
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, facecolor=fig.get_facecolor(), edgecolor="none")
        logger.info("Saved cases heatmap to %s", save_path)
        
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_country_comparison_grid(
    db_session: Session,
    countries: Optional[List[str]] = None,
    save_path: Optional[Path] = None
) -> io.BytesIO:
    """
    Generates a 2x2 comparison grid of daily case trends for 4 countries.
    """
    if countries is None:
        countries = ["United States", "India", "Brazil", "United Kingdom"]
        
    # We must have exactly 4 countries for a 2x2 grid
    countries = list(countries)[:4]
    while len(countries) < 4:
        countries.append("United States")
        
    logger.info("Generating country comparison grid for: %s", countries)
    apply_dark_theme()
    
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=False, dpi=100)
    axes_flat = axes.flatten()
    
    for i, country in enumerate(countries):
        ax = axes_flat[i]
        
        # Query database for that specific country
        query = text("""
            SELECT date, cases, rolling_avg_7d 
            FROM daily_cases 
            WHERE country = :country 
            ORDER BY date
        """)
        df = pd.read_sql(query, con=db_session.bind, params={"country": country})
        df["date"] = pd.to_datetime(df["date"])
        
        # Calculate daily new cases
        df["new_cases"] = df["cases"].diff().fillna(df["cases"])
        df.loc[df["new_cases"] < 0, "new_cases"] = 0
        df["rolling_avg_7d"] = df["new_cases"].rolling(window=7, min_periods=1).mean()
        
        # Plot country specific data
        ax.bar(df["date"], df["new_cases"], color=DARK_PALETTE["secondary"], alpha=0.3)
        ax.plot(df["date"], df["rolling_avg_7d"], color=DARK_PALETTE["accent"], linewidth=1.5, label="7-Day Avg")
        
        # Format axes
        ax.set_title(country, fontsize=12, pad=10, color=DARK_PALETTE["text"])
        ax.xaxis.set_tick_params(labelsize=9)
        ax.yaxis.set_tick_params(labelsize=9)
        if i >= 2:
            ax.set_xlabel("Date", fontsize=9)
        ax.set_ylabel("New Cases", fontsize=9)
        
        # Scale numbers on Y axis for readability (M for millions, K for thousands)
        max_y = df["new_cases"].max()
        if max_y >= 1_000_000:
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, pos: f"{x/1e6:.1f}M"))
        elif max_y >= 1000:
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, pos: f"{x/1e3:.0f}k"))
            
    fig.suptitle("Country Trend Comparison (7-Day Rolling Average)", fontsize=16, color=DARK_PALETTE["text"], y=0.98)
    plt.tight_layout()
    # Adjust spacing to fit suptitle
    plt.subplots_adjust(top=0.9)
    
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, facecolor=fig.get_facecolor(), edgecolor="none")
        logger.info("Saved country comparison grid to %s", save_path)
        
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf

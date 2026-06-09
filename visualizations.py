"""
PaleoData Explorer — Visualizations
====================================
Produces two core scientific visuals from a cleaned occurrence DataFrame:

1. **Paleogeographic Map** (Folium + streamlit-folium)
   Plots fossil localities using paleocoordinates (``paleolat`` /
   ``paleolng``), i.e. where the organism lived accounting for
   tectonic drift.

2. **Deep-Time Timeline** (Plotly)
   A horizontal range chart showing the stratigraphic lifespan of
   each taxon.  The X‑axis (geological time in Ma) is **reversed**
   so that older dates appear on the left and younger dates on the
   right, as is standard in geology.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import folium
from folium.plugins import MarkerCluster
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAP_ZOOM = 3
MAX_MARKERS_MAP = 1500  # cap markers for performance


# ---------------------------------------------------------------------------
# 1. Paleogeographic Map (Folium)
# ---------------------------------------------------------------------------

def build_paleo_map(
    df: pd.DataFrame,
    *,
    height: int = 550,
    zoom: int = DEFAULT_MAP_ZOOM,
) -> folium.Map:
    """Create a Folium map of fossil paleocoordinates.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned occurrence DataFrame.  Must contain at least
        ``paleolat``, ``paleolng``, ``matched_name``.
    height : int
        Height in pixels passed to ``st_folium``.
    zoom : int
        Initial zoom level.

    Returns
    -------
    folium.Map
        The ready-to-render Folium map object.
    """
    if df.empty:
        logger.warning("Empty DataFrame passed to build_paleo_map")
        return folium.Map(location=[0, 0], zoom_start=zoom, tiles="OpenStreetMap")

    # Centre on the median paleocoordinate
    center_lat = float(df["paleolat"].median())
    center_lng = float(df["paleolng"].median())

    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # Sample if too many points (keeps the map snappy)
    work_df = df
    if len(work_df) > MAX_MARKERS_MAP:
        logger.info("Sampling %d points down to %d for map rendering",
                    len(work_df), MAX_MARKERS_MAP)
        work_df = work_df.sample(n=MAX_MARKERS_MAP, random_state=42)

    cluster = MarkerCluster(name="Fossil Occurrences").add_to(m)

    for _, row in work_df.iterrows():
        lat = float(row["paleolat"])
        lng = float(row["paleolng"])
        if not (np.isfinite(lat) and np.isfinite(lng)):
            continue

        name = row.get("matched_name", "Unknown")
        early = row.get("early_interval", "")
        max_ma_val = row.get("max_ma", np.nan)
        min_ma_val = row.get("min_ma", np.nan)

        tooltip_lines = [f"<b>{name}</b>"]
        if early and isinstance(early, str):
            tooltip_lines.append(f"Interval: {early}")
        if np.isfinite(max_ma_val) and np.isfinite(min_ma_val):
            tooltip_lines.append(f"Age: {max_ma_val:.1f}–{min_ma_val:.1f} Ma")

        folium.CircleMarker(
            location=[lat, lng],
            radius=5,
            color="#c0392b",
            fill=True,
            fill_color="#e74c3c",
            fill_opacity=0.7,
            tooltip=folium.Tooltip("<br>".join(tooltip_lines)),
            popup=folium.Popup(name, parse_html=False, max_width=200),
        ).add_to(cluster)

    folium.LayerControl().add_to(m)
    return m


# ---------------------------------------------------------------------------
# 2. Deep-Time Timeline (Plotly)
# ---------------------------------------------------------------------------

def build_timeline(
    df: pd.DataFrame,
    *,
    max_taxa: int = 50,
    height: int = 700,
) -> go.Figure:
    """Build a Plotly horizontal range chart of taxon stratigraphic ranges.

    Geological convention: the X‑axis (Time, Ma) is **reversed** so
    that older dates sit on the left.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned occurrence DataFrame (requires ``matched_name``,
        ``max_ma``, ``min_ma``, ``middle_age``).
    max_taxa : int
        Maximum number of unique taxa to display (top‑N by oldest age).
    height : int
        Figure height in pixels.

    Returns
    -------
    go.Figure
        Plotly figure ready for ``st.plotly_chart``.
    """
    if df.empty:
        logger.warning("Empty DataFrame passed to build_timeline")
        fig = go.Figure()
        fig.update_layout(
            title="No data to display",
            xaxis_title="Time (Ma)",
            yaxis_title="Taxon",
            height=300,
        )
        fig.update_xaxes(autorange="reversed")
        return fig

    # Aggregate to unique taxa: take the overall max_ma / min_ma per name
    agg: pd.DataFrame = (
        df.groupby("matched_name", as_index=False)
        .agg(max_ma=("max_ma", "max"), min_ma=("min_ma", "min"))
        .dropna(subset=["max_ma", "min_ma"])
    )

    if agg.empty:
        logger.warning("No taxa with valid temporal data remain after aggregation")
        fig = go.Figure()
        fig.update_layout(title="No taxa with valid age data", height=300)
        fig.update_xaxes(autorange="reversed")
        return fig

    agg["middle_age"] = (agg["max_ma"] + agg["min_ma"]) / 2.0

    # Keep top-N by oldest age (largest max_ma)
    agg = agg.nlargest(max_taxa, "max_ma")
    agg = agg.sort_values("middle_age", ascending=False)

    fig = go.Figure()

    # Draw horizontal line segments for each taxon
    for _, row in agg.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[row["max_ma"], row["min_ma"]],
                y=[row["matched_name"], row["matched_name"]],
                mode="lines+markers",
                line={"color": "#2c3e50", "width": 6},
                marker={"size": 6, "color": "#e74c3c"},
                name=row["matched_name"],
                hovertemplate=(
                    f"<b>{row['matched_name']}</b><br>"
                    f"Range: {row['max_ma']:.2f}–{row['min_ma']:.2f} Ma<br>"
                    f"<extra></extra>"
                ),
                showlegend=False,
            )
        )

    fig.update_layout(
        title="Fossil Taxon Stratigraphic Ranges",
        xaxis_title="Time (Ma)",
        yaxis_title="",
        height=max(height, 100 + 25 * len(agg)),
        margin={"l": 10, "r": 20, "t": 40, "b": 40},
        hovermode="closest",
    )

    # Reverse X-axis (older → younger = left → right)
    fig.update_xaxes(autorange="reversed")

    return fig

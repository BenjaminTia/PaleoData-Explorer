"""
PaleoData Explorer — Data Processor
====================================
Takes the raw JSON list returned by :mod:`api_client` and transforms it
into a clean, analysis-ready ``pandas.DataFrame``.

Key responsibilities
--------------------
1. Parse PBDB JSON records into a flat DataFrame.
2. Filter out records that lack temporal bounds (``max_ma`` / ``min_ma``)
   or paleocoordinates (``paleolat`` / ``paleolng``).
3. Derive a ``middle_age`` column (``(max_ma + min_ma) / 2``) for point
   plotting on temporal charts.
4. Optionally filter by a user-supplied geological time window.
5. Surface statistics (record counts at each stage) so the UI can show
   the user what was discarded and why.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PBDB raw field → canonical field name mapping.
# The PBDB API returns abbreviated keys; we normalise them here so the
# rest of the pipeline works with descriptive names.
PBDB_COLUMN_MAP: Dict[str, str] = {
    "eag": "max_ma",          # early age  → older bound
    "lag": "min_ma",          # late age   → younger bound
    "tna": "matched_name",    # taxon name
    "oei": "early_interval",
    "oli": "late_interval",
    "pla": "paleolat",
    "pln": "paleolng",
    "phl": "phylum",
    "cll": "class",
    "odl": "order",
    "fml": "family",
    "gnl": "genus",
}

# Canonical field names used after renaming.
FIELDS_TEMPORAL = ("max_ma", "min_ma")
FIELDS_SPATIAL = ("paleolat", "paleolng")
FIELDS_TAXONOMIC = (
    "matched_name",
    "early_interval",
    "late_interval",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def records_to_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert raw PBDB occurrence records into a :class:`pandas.DataFrame`.

    Parameters
    ----------
    records : list[dict]
        The list returned by :func:`api_client.fetch_occurrences`.

    Returns
    -------
    pd.DataFrame
        A DataFrame where each row is one occurrence.  The columns
        include all keys present in the raw JSON, subject to Pandas'
        internal flattening of nested structures when possible.
        Returns an empty DataFrame (0 rows) if the input list is empty.
    """
    if not records:
        logger.warning("records_to_dataframe called with empty list")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    logger.debug("Raw DataFrame shape: %s", df.shape)
    return df


def clean_occurrence_data(
    df: pd.DataFrame,
    *,
    min_ma: Optional[float] = None,
    max_ma: Optional[float] = None,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Clean a raw occurrence DataFrame and optionally subset it to a time window.

    Cleaning steps (in order)
    -------------------------
    1. Remove rows where **both** ``max_ma`` and ``min_ma`` are missing
       (records without any age information are unusable).
    2. Impute missing ``max_ma`` / ``min_ma`` where only one is
       available by taking the available value (conservative estimate).
    3. Remove rows where ``paleolat`` **or** ``paleolng`` is missing
       (cannot plot on a map).
    4. Derive ``middle_age`` = ``(max_ma + min_ma) / 2``.
    5. If ``min_ma`` and/or ``max_ma`` are supplied, filter the
       DataFrame to occurrences whose ``middle_age`` falls within the
       requested window.

    Parameters
    ----------
    df : pd.DataFrame
        Raw DataFrame from :func:`records_to_dataframe`.
    min_ma, max_ma : float or None
        Optional temporal boundaries in Ma.  Only occurrences whose
        ``middle_age`` lies **between** *max_ma* (older bound) and
        *min_ma* (younger bound) are kept.

    Returns
    -------
    df : pd.DataFrame
        Cleaned, filtered DataFrame.  May be empty.
    stats : dict
        Counts at each pipeline stage for transparency:
        ``{"raw": n, "has_temporal": n, "has_spatial": n, "in_window": n}``
    """
    n_raw = len(df)
    stats: Dict[str, int] = {"raw": n_raw}

    if df.empty:
        logger.warning("Input DataFrame is empty; nothing to clean.")
        stats.update(has_temporal=0, has_spatial=0, in_window=0)
        return df, stats

    # ---- Step 0: normalise PBDB abbreviated column names ---------------
    rename_map = {k: v for k, v in PBDB_COLUMN_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_map)
    logger.debug("Renamed %d columns: %s", len(rename_map), list(rename_map.keys()))

    # ---- Step 1: require at least one temporal field -------------------
    temporal_mask = df[list(FIELDS_TEMPORAL)].notna().any(axis=1)
    df = df.loc[temporal_mask].copy()
    stats["has_temporal"] = len(df)
    logger.debug("After temporal filter: %d rows (dropped %d)",
                 stats["has_temporal"], n_raw - stats["has_temporal"])

    # ---- Step 2: impute lone temporal values ---------------------------
    # If max_ma is NaN but min_ma exists, set max_ma = min_ma (point date)
    max_null = df["max_ma"].isna()
    if max_null.any():
        df.loc[max_null, "max_ma"] = df.loc[max_null, "min_ma"]

    # If min_ma is NaN but max_ma exists, set min_ma = max_ma
    min_null = df["min_ma"].isna()
    if min_null.any():
        df.loc[min_null, "min_ma"] = df.loc[min_null, "max_ma"]

    # ---- Step 3: require both paleocoordinates -------------------------
    spatial_mask = df[list(FIELDS_SPATIAL)].notna().all(axis=1)
    df = df.loc[spatial_mask].copy()
    stats["has_spatial"] = len(df)
    logger.debug("After spatial filter: %d rows (dropped %d)",
                 stats["has_spatial"], stats["has_temporal"] - stats["has_spatial"])

    # ---- Step 4: compute middle_age ------------------------------------
    df["middle_age"] = (df["max_ma"].astype(float) + df["min_ma"].astype(float)) / 2.0

    # ---- Step 5: optional time-window filter ---------------------------
    if max_ma is not None or min_ma is not None:
        in_window = pd.Series(True, index=df.index)

        if max_ma is not None:
            in_window &= df["middle_age"] <= float(max_ma)
        if min_ma is not None:
            in_window &= df["middle_age"] >= float(min_ma)

        df = df.loc[in_window].copy()
        stats["in_window"] = len(df)
        logger.debug("After time-window filter: %d rows (dropped %d)",
                     stats["in_window"], stats["has_spatial"] - stats["in_window"])
    else:
        stats["in_window"] = stats["has_spatial"]

    # ---- Ensure consistent float types for critical columns ------------
    for col in ("max_ma", "min_ma", "middle_age", "paleolat", "paleolng"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("Cleaning pipeline done: raw=%d → has_temporal=%d → has_spatial=%d → in_window=%d",
                stats["raw"], stats["has_temporal"], stats["has_spatial"], stats["in_window"])
    return df, stats


def get_dataframe_statistics(df: pd.DataFrame) -> Dict[str, Any]:
    """Return a small summary dict for display in the UI.

    Includes unique taxa counts, time span, and geographic extent.
    """
    if df.empty:
        return {"unique_taxa": 0, "time_span_ma": None}

    stats = {
        "record_count": len(df),
        "unique_taxa": int(df["matched_name"].nunique()),
        "unique_families": int(df["family"].nunique()) if "family" in df.columns else 0,
        "unique_genera": int(df["genus"].nunique()) if "genus" in df.columns else 0,
        "oldest_ma": float(df["middle_age"].max()),
        "youngest_ma": float(df["middle_age"].min()),
        "time_span_ma": float(df["middle_age"].max() - df["middle_age"].min()),
        "lat_extent": float(df["paleolat"].max() - df["paleolat"].min()) if "paleolat" in df.columns else None,
        "lng_extent": float(df["paleolng"].max() - df["paleolng"].min()) if "paleolng" in df.columns else None,
    }
    return stats

"""
PaleoData Explorer — PBDB & Macrostrat API Client
==================================================
Provides robust, cached-friendly wrappers around the Paleobiology Database
(PBDB) occurrence endpoint and (optionally) the Macrostrat interval
endpoint.  Every function handles timeouts, HTTP errors, and empty
responses gracefully.

Domain notes
------------
* Geological time is in "Ma" (Mega-annum, millions of years ago).
* The "show" parameter must include `paleoloc` (paleocoordinates),
  `phylo` (phylogeny / taxonomy) and `time,ident` so the returned JSON
  carries `paleolat`, `paleolng`, taxonomic hierarchies and temporal
  bounds (`max_ma`, `min_ma`).
* The PBDB API returns `records` inside a top-level key; we safely
  unwrap that in `fetch_occurrences`.
"""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PBDB_OCCURRENCE_URL: str = "https://paleobiodb.org/data1.2/occs/list.json"
MACROSTRAT_INTERVALS_URL: str = "https://macrostrat.org/api/v2/defs/intervals"

DEFAULT_LIMIT: int = 1000
DEFAULT_SHOW: str = "paleoloc,phylo,time,ident"
REQUEST_TIMEOUT: int = 30  # seconds


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _safe_get(url: str, params: Dict[str, Any]) -> requests.Response:
    """Perform a GET request with standardised error handling.

    Raises
    ------
    requests.exceptions.Timeout
        When the request hangs past *REQUEST_TIMEOUT*.
    requests.exceptions.HTTPError
        On 4xx / 5xx responses.
    ValueError
        When the response body is not valid JSON.
    """
    logger.debug("GET %s | params=%s", url, params)
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# PBDB Occurrence fetch
# ---------------------------------------------------------------------------

def fetch_occurrences(
    base_name: str,
    *,
    max_ma: Optional[float] = None,
    min_ma: Optional[float] = None,
    limit: int = DEFAULT_LIMIT,
    show: str = DEFAULT_SHOW,
) -> List[Dict[str, Any]]:
    """Fetch fossil occurrence records from the PBDB API.

    Parameters
    ----------
    base_name : str
        Taxonomic clade or genus name, e.g. ``"Ceratopsidae"`` or
        ``"Tyrannosaurus"``.  PBDB resolves this hierarchically so all
        subordinate taxa are included automatically.
    max_ma, min_ma : float or None
        Optional temporal window in Ma.  When supplied the API filters
        occurrences to those whose age range overlaps this window.
    limit : int
        Maximum number of records to return (default 1 000).
    show : str
        Comma-separated list of PBDB "show" fields.  Must include at
        least ``paleoloc,phylo,time,ident`` for the downstream pipeline.

    Returns
    -------
    list[dict]
        List of raw occurrence records.  Returns an empty list when the
        API returns no records or the response is malformed.

    Raises
    ------
    requests.exceptions.Timeout
        If the PBDB API does not respond within *REQUEST_TIMEOUT*.
    requests.exceptions.HTTPError
        If the API returns a non-200 status.
    ValueError
        If the response body cannot be parsed as JSON.
    """
    params: Dict[str, Any] = {
        "base_name": base_name,
        "show": show,
        "limit": limit,
    }
    if max_ma is not None:
        params["max_ma"] = max_ma
    if min_ma is not None:
        params["min_ma"] = min_ma

    logger.info("Querying PBDB with base_name=%r", base_name)

    try:
        resp = _safe_get(PBDB_OCCURRENCE_URL, params)
    except requests.exceptions.Timeout:
        logger.error("PBDB request timed out after %d s", REQUEST_TIMEOUT)
        raise
    except requests.exceptions.HTTPError as exc:
        logger.error("PBDB request failed (HTTP %s)", exc.response.status_code if exc.response is not None else "unknown")
        raise
    except requests.exceptions.RequestException as exc:
        logger.error("PBDB request failed: %s", exc)
        raise

    try:
        data = resp.json()
    except ValueError:
        logger.error("PBDB response body is not valid JSON")
        raise

    records: List[Dict[str, Any]] = data.get("records", [])
    if not records:
        logger.warning("PBDB returned zero records for base_name=%r", base_name)

    logger.info("PBDB returned %d records", len(records))
    return records


# ---------------------------------------------------------------------------
# Wikipedia profile fetch (optional helper)
# ---------------------------------------------------------------------------

WIKIPEDIA_SUMMARY_URL: str = "https://en.wikipedia.org/api/rest_v1/page/summary"


def fetch_wikipedia_profile(taxon_name: str) -> Dict[str, Any]:
    """Fetch a short summary and thumbnail for a taxon from Wikipedia.

    Uses the Wikimedia REST API ``/page/summary/{title}`` endpoint.
    Failures are caught silently and an empty dict (or dict with an
    ``"error"`` key) is returned so callers never crash.

    Parameters
    ----------
    taxon_name : str
        The Wikipedia article title, e.g. ``"Triceratops"`` or
        ``"Tyrannosaurus"``.

    Returns
    -------
    dict
        On success: ``{"extract": str, "image_url": str|None, "page_url": str}``.
        On failure: ``{"error": str}`` or ``{}``.
    """
    import urllib.parse

    safe_title = urllib.parse.quote(taxon_name.strip(), safe="")
    url = f"{WIKIPEDIA_SUMMARY_URL}/{safe_title}"

    logger.info("Fetching Wikipedia summary for %r", taxon_name)

    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "PaleoDataExplorer/1.0 (educational tool; https://github.com/anomalyco/opencode)"},
        )
        if resp.status_code == 404:
            logger.warning("Wikipedia page not found for %r", taxon_name)
            return {"error": f"No Wikipedia article found for '{taxon_name}'."}
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.error("Wikipedia request timed out for %r", taxon_name)
        return {"error": "Wikipedia request timed out."}
    except requests.exceptions.RequestException as exc:
        logger.error("Wikipedia request failed for %r: %s", taxon_name, exc)
        return {"error": f"Wikipedia request failed: {exc}"}

    try:
        data = resp.json()
    except ValueError:
        logger.error("Wikipedia response is not valid JSON for %r", taxon_name)
        return {"error": "Invalid response from Wikipedia."}

    extract = data.get("extract", "")
    thumbnail = data.get("thumbnail", {})
    image_url = thumbnail.get("source") if isinstance(thumbnail, dict) else None
    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

    return {
        "extract": extract,
        "image_url": image_url,
        "page_url": page_url,
    }


# ---------------------------------------------------------------------------
# Macrostrat interval fetch (optional helper)
# ---------------------------------------------------------------------------

def fetch_macrostrat_intervals() -> List[Dict[str, Any]]:
    """Fetch the Macrostrat interval definitions (geological periods).

    Useful for mapping absolute Ma values to named periods.  Returns an
    empty list on failure so callers can fall back gracefully.

    Returns
    -------
    list[dict]
        Each dict contains keys such as ``name``, ``t_age``, ``b_age``,
        ``color``, etc.
    """
    logger.info("Querying Macrostrat interval definitions")
    try:
        resp = _safe_get(MACROSTRAT_INTERVALS_URL, {"all": True, "format": "json"})
        return resp.json()  # type: ignore[no-any-return]
    except Exception:
        logger.exception("Failed to fetch Macrostrat intervals")
        return []

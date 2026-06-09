<h1 align="center">🦴 PaleoData Explorer</h1>

<p align="center">
  <strong>A professional-grade Streamlit dashboard for querying, cleaning, visualising,<br>and exporting fossil occurrence data from the Paleobiology Database.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#usage-guide">Usage Guide</a> •
  <a href="#data-sources">Data Sources</a> •
  <a href="#license">License</a>
</p>

---

## Overview

PaleoData Explorer turns the messy, raw JSON from the [Paleobiology Database (PBDB)](https://paleobiodb.org) API into an interactive dashboard with paleogeographic maps, deep-time timelines, and Wikipedia-powered taxon profiles. It is designed for **paleontologists**, **geology students**, and **science communicators** who need to explore fossil records without writing code.

### What Problem Does It Solve?

The PBDB is the gold-standard repository for fossil occurrence data, but its API returns abbreviated field names, incomplete records, and no visualisation layer. Researchers typically spend hours writing one-off scripts just to see their data on a map.

PaleoData Explorer provides a **zero-code pipeline**:
- Query the PBDB by taxon name and geological time window
- Automatically clean and standardise the data
- Visualise results on paleocoordinate maps and stratigraphic range charts
- Browse Wikipedia summaries and images for any taxon
- Export a clean CSV for further analysis in R, Python, or Excel

---

## Features

### 🔍 Intelligent PBDB Queries
- Search by any taxonomic rank — clade, family, genus, or species
- PBDB resolves parent clades hierarchically (e.g. "Tyrannosauridae" returns all subordinate taxa)
- Filter by geological time window (Ma) with a slider
- Configurable record limit (100–5000)

### 🧹 Automated Data Cleaning
- Drops records missing temporal bounds (`max_ma` / `min_ma`) or paleocoordinates
- Imputes single-bound age estimates
- Computes `middle_age = (max_ma + min_ma) / 2` for point plotting
- Transparent pipeline statistics showing records dropped at each stage

### 🗺️ Paleogeographic Map
- **MarkerCluster** rendering for smooth performance with thousands of points
- Plotted on **paleocoordinates** — showing where organisms lived millions of years ago, accounting for continental drift
- Click any marker to jump to that organism's Wikipedia profile
- Tooltips showing `matched_name`, geological interval, and age range

### 📈 Deep-Time Timeline
- Horizontal stratigraphic range chart (Gantt-style)
- **X-axis reversed** — older on the left, younger on the right (geological convention)
- Top‑50 taxa by oldest age, sorted by midpoint

### 🔍 Taxon Profile Viewer
- Select any taxon from the cleaned dataset via dropdown
- Fetches **Wikipedia summary** and **thumbnail image** via the Wikimedia REST API
- Results cached for 1 hour (no redundant API calls)
- Falls back from genus-level to species-level lookup

### 📥 CSV Export
- One-click download of the fully cleaned DataFrame
- Ready for import into R, Python, Excel, or GIS tools

### 📚 Built-in Taxon Reference
- 130+ pre-listed taxa across 7 categories (Dinosaurs, Marine Reptiles, Mammals, Invertebrates, Plants, etc.)
- **Clickable buttons** auto-fill the search bar — no typing needed
- Always visible below results

---

## Quick Start

### Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/BenjaminTia/PaleoPedia.git
cd PaleoPedia

# Build and start
docker compose up --build -d

# Open in browser
open http://localhost:8501
```

### Local Installation

```bash
# Clone and install
git clone https://github.com/BenjaminTia/PaleoPedia.git
cd PaleoPedia
pip install -r requirements.txt

# Run
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

---

## Architecture

```
PaleoPedia/
├── app.py                 # Streamlit entry point — sidebar, tabs, export, UI
├── api_client.py          # PBDB & Wikipedia API wrappers with error handling
├── data_processor.py      # JSON → DataFrame, cleaning pipeline, statistics
├── visualizations.py      # Folium MarkerCluster map + Plotly timeline chart
├── requirements.txt       # Pinned Python dependencies
├── Dockerfile             # Python 3.11-slim, multi-stage-friendly
├── docker-compose.yml     # Single-service orchestration
└── .dockerignore
```

### Module Responsibilities

| Module | Role |
|---|---|
| `api_client.py` | `fetch_occurrences()` — queries PBDB with `base_name`, `max_ma`/`min_ma`, and `show=paleoloc,phylo,time,ident`. Returns raw JSON list. `fetch_wikipedia_profile()` — fetches page summary and thumbnail from Wikimedia REST API. Handles timeouts, HTTP errors, and empty responses gracefully. |
| `data_processor.py` | `clean_occurrence_data()` — 5-step pipeline: temporal filter → impute lone bounds → spatial filter → compute `middle_age` → time-window filter. Returns `(DataFrame, stats_dict)`. `get_dataframe_statistics()` — summary metrics for the UI. Includes a `PBDB_COLUMN_MAP` that normalises abbreviated field names (`eag` → `max_ma`, `tna` → `matched_name`, etc.). |
| `visualizations.py` | `build_paleo_map()` — Folium map with `MarkerCluster`, `CircleMarker`s, tooltips, and clickable popups. `build_timeline()` — Plotly horizontal range chart with reversed X-axis. |
| `app.py` | Full Streamlit dashboard: sidebar controls (taxon input, Ma slider, record limit), educational guide expander, summary metrics, pipeline stats, 4-tab layout (Map, Timeline, Taxon Profile, Raw Data & CSV export), persistent tab state, map-click-to-profile integration, and 130+ clickable reference buttons. |

### Data Flow

```
User Input (sidebar)
    │
    ▼
api_client.fetch_occurrences()  ──►  PBDB API
    │
    ▼
data_processor.records_to_dataframe()
    │
    ▼
data_processor.clean_occurrence_data()  ──►  Cleaned DataFrame
    │
    ├──► visualizations.build_paleo_map()  ──►  Folium map
    ├──► visualizations.build_timeline()   ──►  Plotly chart
    ├──► api_client.fetch_wikipedia_profile()  ──►  Wikipedia
    └──► CSV export
```

---

## Usage Guide

### 1. Search for Fossils

1. Open the sidebar (☰)
2. Type a taxon name — or click any name in the **Taxon & Clade Reference** at the bottom of the page
3. Adjust the **Geological Time Window** slider (default: 65–250 Ma, the Mesozoic)
4. Click **🚀 Search PBDB**

### 2. Explore the Results

| Tab | What You See |
|---|---|
| 🗺️ Paleogeographic Map | Clustered markers on paleocoordinates. Zoom in to see individual fossils. Click a marker to jump to its Taxon Profile. |
| 📈 Deep-Time Timeline | Horizontal range chart. Older on the left, younger on the right. Hover for details. |
| 🔍 Taxon Profile | Select any taxon from the dropdown. View Wikipedia summary, image, and link to full article. |
| 📋 Raw Data & Export | Full cleaned dataset as a sortable table. Click **Download as CSV** to export. |

### 3. Export for Research

The CSV export contains all cleaned columns: `matched_name`, `max_ma`, `min_ma`, `middle_age`, `paleolat`, `paleolng`, `early_interval`, `family`, `genus`, `phylum`, `class`, `order`, and more. Ready for:

```r
# R
df <- read.csv("paleodata_Ceratopsidae_65_250Ma.csv")
```

```python
# Python
import pandas as pd
df = pd.read_csv("paleodata_Ceratopsidae_65_250Ma.csv")
```

### Example Queries

| Search Term | Expected Records | Notes |
|---|---|---|
| `Tyrannosauridae` | ~50–200 | T. rex family and relatives |
| `Ceratopsidae` | ~100–1000 | Horned dinosaurs |
| `Ammonoidea` | ~1000+ | Ammonites — huge dataset |
| `Trilobita` | ~1000+ | Trilobites — wide temporal range |
| `Homo` | ~100+ | Human lineage |
| `Mammuthus` | ~50–200 | Mammoths |
| `Megalodon` | ~10–50 | Giant extinct shark |

---

## API & Domain Notes

### PBDB Field Mapping

The PBDB API returns abbreviated keys. PaleoData Explorer normalises them:

| PBDB Key | Meaning | Canonical Name |
|---|---|---|
| `eag` | Early age (older bound) | `max_ma` |
| `lag` | Late age (younger bound) | `min_ma` |
| `tna` | Taxon name | `matched_name` |
| `oei` | Early interval name | `early_interval` |
| `pla` | Paleolatitude | `paleolat` |
| `pln` | Paleolongitude | `paleolng` |
| `phl` | Phylum | `phylum` |
| `cll` | Class | `class` |
| `odl` | Order | `order` |
| `fml` | Family | `family` |
| `gnl` | Genus | `genus` |

### Geological Time Convention

- **Ma** = Mega-annum (millions of years ago)
- **Larger numbers** = further back in time
- All temporal charts display with the **X-axis reversed** (older ← left, younger → right)

### Paleocoordinates vs. Modern Coordinates

Modern GPS coordinates tell you where a fossil was *found*. Paleocoordinates tell you where the organism actually *lived*, reconstructed by reversing tectonic plate movements. This app exclusively plots paleocoordinates from the PBDB's GPlates model.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend / UI | [Streamlit](https://streamlit.io) 1.58+ |
| Data Processing | [Pandas](https://pandas.pydata.org) 3.0+, [NumPy](https://numpy.org) 2.4+ |
| API Requests | [Requests](https://requests.readthedocs.io) 2.34+ |
| Map Visualisation | [Folium](https://python-visualization.github.io/folium/) 0.20+ |
| Charts | [Plotly](https://plotly.com/python/) 6.8+ |
| Containerisation | [Docker](https://docker.com), Python 3.11-slim |

---

## Contributing

Contributions are welcome. Areas of interest:

- Adding Macrostrat geological period overlays
- Supporting additional PBDB output formats
- Adding stratigraphic column visualisations
- Improving test coverage
- i18n / translations

Please open an issue or pull request on GitHub.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Acknowledgements

- Fossil occurrence data via the [Paleobiology Database](https://paleobiodb.org) (CC BY 4.0)
- Taxon summaries and images via the [Wikimedia REST API](https://www.mediawiki.org/wiki/API:REST_API) (CC BY-SA 3.0 / various)
- Paleocoordinates reconstructed using the [GPlates](https://www.gplates.org) model
- Built with [Streamlit](https://streamlit.io), [Folium](https://python-visualization.github.io/folium/), and [Plotly](https://plotly.com)

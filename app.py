"""
PaleoData Explorer — Streamlit Application
===========================================
Professional-grade dashboard for querying, cleaning, visualising, and
exporting fossil occurrence data from the Paleobiology Database (PBDB).

Run with::

    streamlit run app.py
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from api_client import fetch_macrostrat_intervals, fetch_occurrences, fetch_wikipedia_profile
from data_processor import (
    clean_occurrence_data,
    get_dataframe_statistics,
    records_to_dataframe,
)
from visualizations import build_paleo_map, build_timeline

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch_wikipedia_profile(taxon_name: str) -> dict:
    """Streamlit-cached wrapper around :func:`fetch_wikipedia_profile`.

    Results are cached for 1 hour so repeated selections of the same
    taxon do not re-hit the Wikipedia API.
    """
    return fetch_wikipedia_profile(taxon_name)


# ---------------------------------------------------------------------------
# Reference-list helper: render clickable taxon buttons
# ---------------------------------------------------------------------------

def _clickable_taxon(taxon: str, desc: str = "") -> None:
    """Render a small clickable button that auto-fills the search bar.

    Uses an intermediary ``_pending_taxon`` session-state key to avoid
    Streamlit's restriction on modifying a widget's key after the widget
    has already been instantiated during the same render pass.
    """
    label = f"{taxon}"
    if desc:
        label += f"  — {desc}"
    if st.button(label, key=f"refbtn_{taxon}", help=f'Search PBDB for "{taxon}"', use_container_width=True):
        st.session_state["_pending_taxon"] = taxon
        st.rerun()


def _clickable_taxa_section(header: str, taxa: list[tuple[str, str]], num_cols: int = 3) -> None:
    """Render a labelled group of :func:`_clickable_taxon` buttons in columns.

    Parameters
    ----------
    header : str
        Bold markdown heading for the group.
    taxa : list[tuple[str, str]]
        Each tuple is ``(taxon_name, short_description)``.
    num_cols : int
        Number of button columns.
    """
    st.markdown(f"**{header}**")
    cols = st.columns(num_cols)
    for i, (taxon, desc) in enumerate(taxa):
        with cols[i % num_cols]:
            _clickable_taxon(taxon, desc)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PaleoData Explorer",
    page_icon="🦴",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Intermediary state: allow downstream buttons to request a taxon change
# or active-tab switch without violating Streamlit's widget-key immutability rule.
# ---------------------------------------------------------------------------
if st.session_state.get("_pending_taxon"):
    st.session_state["taxon_input"] = st.session_state.pop("_pending_taxon")
if st.session_state.get("_pending_active_tab"):
    st.session_state["active_tab"] = st.session_state.pop("_pending_active_tab")

# ---------------------------------------------------------------------------
# Sidebar — Query controls
# ---------------------------------------------------------------------------
st.sidebar.title("🔍 Query Controls")

# Initialise session state for the taxon input if not already set
if "taxon_input" not in st.session_state:
    st.session_state["taxon_input"] = "Ceratopsidae"

taxon_input = st.sidebar.text_input(
    "Taxon / Clade",
    key="taxon_input",
    help="Enter a taxonomic name, e.g. 'Tyrannosauridae', 'Mammalia', or 'Triceratops'.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Geological Time Window (Ma)")

ma_min, ma_max = st.sidebar.slider(
    "Select age range (millions of years ago)",
    min_value=0.0,
    max_value=500.0,
    value=(65.0, 250.0),
    step=5.0,
    help="Older = larger number.  The PBDB will return fossils whose age ranges overlap this window.",
)

max_records = st.sidebar.number_input(
    "Max records",
    min_value=100,
    max_value=5000,
    value=1000,
    step=100,
    help="Maximum number of occurrence records to fetch from the PBDB API.",
)

st.sidebar.markdown("---")

search_clicked = st.sidebar.button(
    "🚀 Search PBDB",
    type="primary",
    use_container_width=True,
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data sourced from the [Paleobiology Database](https://paleobiodb.org) "
    "and [Macrostrat](https://macrostrat.org)."
)

# ---------------------------------------------------------------------------
# App title
# ---------------------------------------------------------------------------
st.title("🦴 PaleoData Explorer")
st.markdown(
    "Query, clean, visualise, and export fossil occurrence records from "
    "the **Paleobiology Database** (PBDB).  Paleocoordinates are mapped "
    "on the paleogeographic globe; timelines follow geological convention "
    "(older → younger = left → right)."
)

# ---------------------------------------------------------------------------
# Educational Guide (collapsed by default)
# ---------------------------------------------------------------------------
with st.expander("📖 Welcome to PaleoData Explorer: Guide & Glossary", expanded=False):
    st.markdown(
        """
### What is PaleoData Explorer?

This is a professional data-wrangling dashboard that connects to the real
**[Paleobiology Database (PBDB)](https://paleobiodb.org)** — the same
database used by working paleontologists worldwide.  Instead of browsing
static tables, you can search, visualise, and download fossil occurrence
records in seconds.

---

### Key Concepts & Glossary

| Term | Meaning |
|---|---|
| **Ma (Mega-annum)** | Millions of years ago.  *Larger numbers = further back in time.*  All timelines in this app flow **backwards** (older on the left, younger on the right), following geological convention. |
| **Paleocoordinates** | The reconstructed latitude/longitude of a fossil **at the time the organism lived**, accounting for millions of years of tectonic plate movement.  This map shows where the animal actually lived — *not* where its bones happen to sit today. |
| **Clade / Taxon** | A group of organisms sharing a common ancestor.  Searching for a family name (e.g. "Tyrannosauridae") automatically includes all subordinate genera and species. |
| **Stratigraphic Range** | The span of geological time during which a taxon is known to have existed, bounded by its oldest (*max_ma*) and youngest (*min_ma*) fossil occurrences. |
| **Middle Age** | The midpoint of a fossil's stratigraphic range: `(max_ma + min_ma) / 2`.  Used as a single-point estimate for temporal plotting. |
| **PBDB** | The Paleobiology Database — a public, community-driven repository of fossil occurrence data curated by hundreds of research scientists. |

---

### How to Use This App

1. **Enter a taxon name** in the sidebar (e.g. *Ceratopsidae*, *Tyrannosaurus*, *Mammalia*).
2. **Adjust the time slider** to narrow the geological window (default: 65–250 Ma, the Mesozoic).
3. Click **Search PBDB** to fetch records.
4. Explore the results across three tabs:
   - 🗺️ **Paleogeographic Map** — clustered markers on paleocoordinates.
   - 📈 **Deep-Time Timeline** — stratigraphic range chart.
   - 🔍 **Taxon Profile** — Wikipedia summary and image for any taxon in the results.
5. 📥 **Download** the cleaned dataset as a CSV for your own analysis.
        """
    )

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "df_clean": pd.DataFrame(),
    "stats_raw": {},
    "query_taxon": "",
    "query_ma_min": None,
    "query_ma_max": None,
    "last_error": "",
    "has_searched": False,
}
for key, default in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------------------------------------------------------
# Fetch & process logic
# ---------------------------------------------------------------------------
def run_query() -> None:
    """Execute the full fetch → clean pipeline and store results in session."""
    st.session_state["last_error"] = ""
    st.session_state["has_searched"] = True
    st.session_state["query_taxon"] = taxon_input.strip()
    st.session_state["query_ma_min"] = ma_min
    st.session_state["query_ma_max"] = ma_max

    with st.spinner(f"Querying PBDB for '{st.session_state['query_taxon']}' …"):
        try:
            raw_records = fetch_occurrences(
                base_name=st.session_state["query_taxon"],
                max_ma=ma_max,
                min_ma=ma_min,
                limit=int(max_records),
            )
        except Exception as exc:
            logger.exception("PBDB query failed")
            st.session_state["last_error"] = f"API error: {exc}"
            st.session_state["df_clean"] = pd.DataFrame()
            st.session_state["stats_raw"] = {}
            return

    if not raw_records:
        st.session_state["last_error"] = (
            f"No records found for '{st.session_state['query_taxon']}' "
            f"within {ma_min:.0f}–{ma_max:.0f} Ma."
        )
        st.session_state["df_clean"] = pd.DataFrame()
        st.session_state["stats_raw"] = {}
        return

    df_raw = records_to_dataframe(raw_records)
    df_clean, pipeline_stats = clean_occurrence_data(df_raw, max_ma=ma_max, min_ma=ma_min)

    st.session_state["df_clean"] = df_clean
    st.session_state["stats_raw"] = pipeline_stats


if search_clicked:
    run_query()

# ---------------------------------------------------------------------------
# Results area
# ---------------------------------------------------------------------------
if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])

if st.session_state.get("has_searched") and not st.session_state.get("last_error"):
    st.success(
        f"Query: **{st.session_state['query_taxon']}**  |  "
        f"Time window: {st.session_state['query_ma_min']:.0f}–{st.session_state['query_ma_max']:.0f} Ma"
    )

    df = st.session_state["df_clean"]

    if df.empty:
        st.warning("No records survived the cleaning pipeline.  Try broadening your search.")
        st.stop()

    # ---- Summary stats --------------------------------------------------
    summary = get_dataframe_statistics(df)
    cols = st.columns(5)
    cols[0].metric("Records", summary.get("record_count", 0))
    cols[1].metric("Unique Taxa", summary.get("unique_taxa", 0))
    cols[2].metric("Oldest (Ma)", f"{summary.get('oldest_ma', 0):.1f}")
    cols[3].metric("Youngest (Ma)", f"{summary.get('youngest_ma', 0):.1f}")
    cols[4].metric("Time Span (Ma)", f"{summary.get('time_span_ma', 0):.1f}")

    # ---- Pipeline stats -------------------------------------------------
    with st.expander("📊 Data Pipeline Details", expanded=False):
        stats = st.session_state.get("stats_raw", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fetched", stats.get("raw", 0))
        c2.metric("Has temporal", stats.get("has_temporal", 0))
        c3.metric("Has spatial", stats.get("has_spatial", 0))
        c4.metric("In time window", stats.get("in_window", 0))

    # ---- Tab selector (radio, so it persists across reruns) -------------
    TAB_OPTIONS = [
        "🗺️ Paleogeographic Map",
        "📈 Deep-Time Timeline",
        "🔍 Taxon Profile",
        "📋 Raw Data & Export",
    ]
    if "active_tab" not in st.session_state:
        st.session_state["active_tab"] = TAB_OPTIONS[0]

    active_tab = st.radio(
        "",
        TAB_OPTIONS,
        horizontal=True,
        key="active_tab",
        label_visibility="collapsed",
    )

    # ------------------------------------------------------------------
    # Tab 1: Paleogeographic Map
    # ------------------------------------------------------------------
    if active_tab == TAB_OPTIONS[0]:
        st.subheader("Fossil Occurrences — Paleocoordinates")
        st.caption(
            "Points are plotted at their **paleocoordinates** — where the "
            "organism lived millions of years ago, accounting for continental drift.  "
            "🖱️ **Click a marker** to jump to its Taxon Profile."
        )
        paleo_map = build_paleo_map(df, height=600)
        map_data = st_folium(paleo_map, height=600, width=700)

        # Detect map-marker click → switch to Taxon Profile tab
        if map_data and map_data.get("last_object_clicked_popup"):
            clicked_taxon = str(map_data["last_object_clicked_popup"]).strip()
            if clicked_taxon:
                st.session_state["profile_taxon"] = clicked_taxon
                st.session_state["_pending_active_tab"] = TAB_OPTIONS[2]
                st.rerun()

    # ------------------------------------------------------------------
    # Tab 2: Deep-Time Timeline
    # ------------------------------------------------------------------
    elif active_tab == TAB_OPTIONS[1]:
        st.subheader("Stratigraphic Range Chart")
        st.caption("X‑axis is **reversed** (older on left, younger on right) — geological convention.")
        fig_timeline = build_timeline(df, max_taxa=50)
        st.plotly_chart(fig_timeline, use_container_width=True)

    # ------------------------------------------------------------------
    # Tab 3: Taxon Profile
    # ------------------------------------------------------------------
    elif active_tab == TAB_OPTIONS[2]:
        st.subheader("Taxon Profile Viewer")
        st.caption(
            "Select a taxon from the dropdown to view a summary and image "
            "sourced from Wikipedia."
        )

        unique_taxa = sorted(df["matched_name"].dropna().unique())
        if len(unique_taxa) == 0:
            st.info("No named taxa available in the current results.")
        else:
            # Honour a map-click pre-selection
            if "profile_taxon" not in st.session_state:
                st.session_state["profile_taxon"] = unique_taxa[0]
            default_index = 0
            if st.session_state["profile_taxon"] in unique_taxa:
                default_index = unique_taxa.index(st.session_state["profile_taxon"])

            selected_taxon = st.selectbox(
                "Choose a taxon",
                options=unique_taxa,
                index=default_index,
                key="profile_selectbox",
                help="Taxa are drawn from the matched_name field in the cleaned dataset.",
            )
            # Sync the pick back to session state
            st.session_state["profile_taxon"] = selected_taxon

            if selected_taxon:
                genus_candidate = df.loc[
                    df["matched_name"] == selected_taxon, "genus"
                ]
                lookup_name = selected_taxon
                if not genus_candidate.empty and genus_candidate.notna().any():
                    genus_val = str(genus_candidate.iloc[0])
                    if genus_val and genus_val != "nan":
                        lookup_name = genus_val

                with st.spinner(f"Fetching Wikipedia summary for '{lookup_name}' …"):
                    profile = cached_fetch_wikipedia_profile(lookup_name)

                if profile.get("error"):
                    if lookup_name != selected_taxon:
                        with st.spinner(f"Trying '{selected_taxon}' …"):
                            profile = cached_fetch_wikipedia_profile(selected_taxon)

                if profile.get("error"):
                    st.warning(profile["error"])
                else:
                    col_img, col_text = st.columns([1, 2])
                    with col_img:
                        image_url = profile.get("image_url")
                        if image_url:
                            st.image(image_url, caption=lookup_name, use_container_width=True)
                        else:
                            st.info("No image available.")
                    with col_text:
                        extract = profile.get("extract", "")
                        if extract:
                            st.markdown(extract)
                        else:
                            st.info("No summary text available.")
                    page_url = profile.get("page_url")
                    if page_url:
                        st.caption(f"[Read more on Wikipedia]({page_url})")

    # ------------------------------------------------------------------
    # Tab 4: Raw Data & Export
    # ------------------------------------------------------------------
    elif active_tab == TAB_OPTIONS[3]:
        st.subheader("Cleaned Occurrence Data")
        st.dataframe(
            df,
            use_container_width=True,
            column_config={
                "paleolat": st.column_config.NumberColumn("Paleolat (°)", format="%.4f"),
                "paleolng": st.column_config.NumberColumn("Paleolng (°)", format="%.4f"),
                "max_ma": st.column_config.NumberColumn("Max Age (Ma)", format="%.2f"),
                "min_ma": st.column_config.NumberColumn("Min Age (Ma)", format="%.2f"),
                "middle_age": st.column_config.NumberColumn("Middle Age (Ma)", format="%.2f"),
            },
            hide_index=True,
        )

        # -- CSV export ---------------------------------------------------
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv_buffer.getvalue(),
            file_name=f"paleodata_{st.session_state['query_taxon']}_{ma_min:.0f}_{ma_max:.0f}Ma.csv",
            mime="text/csv",
            type="primary",
        )

else:
    # Landing state — show instructions
    st.info(
        "Enter a taxon name in the sidebar (e.g. **Ceratopsidae**, "
        "**Tyrannosauridae**, **Mammalia**) and click **Search PBDB** "
        "to begin exploring the fossil record."
    )
    st.markdown(
        """
        ### What this app does
        1. **Queries** the Paleobiology Database for fossil occurrences.
        2. **Cleans** the raw data (drops records missing age or coordinates).
        3. **Visualises** results on a paleogeographic map and a deep-time timeline.
        4. **Exports** the cleaned dataset as a CSV for your own analysis.
        """
    )

# ---------------------------------------------------------------------------
# 📚 Taxon & Clade Reference (always visible)
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("📚 Taxon & Clade Reference")
st.caption(
    "Click any name below to auto-fill the sidebar search box.  "
    "Larger clades (families, orders) return more records; individual genera return more focused results."
)

with st.expander("🦖 Dinosauria — Dinosaurs", expanded=False):
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        _clickable_taxa_section("Theropoda (meat-eaters)", [
            ("Tyrannosauridae", "T. rex family"),
            ("Tyrannosaurus", ""),
            ("Spinosauridae", ""),
            ("Spinosaurus", ""),
            ("Allosauridae", ""),
            ("Allosaurus", ""),
            ("Dromaeosauridae", "raptors"),
            ("Velociraptor", ""),
            ("Troodontidae", ""),
            ("Coelophysoidea", ""),
            ("Abelisauridae", ""),
            ("Carcharodontosauridae", ""),
            ("Giganotosaurus", ""),
            ("Compsognathidae", ""),
            ("Ornithomimidae", ""),
            ("Oviraptoridae", ""),
            ("Therizinosauridae", ""),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Sauropodomorpha (long-necks)", [
            ("Sauropoda", ""),
            ("Titanosauria", ""),
            ("Brachiosauridae", ""),
            ("Brachiosaurus", ""),
            ("Diplodocidae", ""),
            ("Diplodocus", ""),
            ("Apatosaurus", ""),
            ("Camarasauridae", ""),
            ("Dicraeosauridae", ""),
        ], num_cols=1)

        _clickable_taxa_section("Ornithischia (bird-hipped)", [
            ("Stegosauridae", ""),
            ("Stegosaurus", ""),
            ("Ankylosauridae", ""),
            ("Ankylosaurus", ""),
            ("Nodosauridae", ""),
        ], num_cols=1)

    with col_c:
        _clickable_taxa_section("Marginocephalia", [
            ("Ceratopsidae", "horned dinos"),
            ("Triceratops", ""),
            ("Centrosaurus", ""),
            ("Styracosaurus", ""),
            ("Pachycephalosauridae", ""),
            ("Pachycephalosaurus", ""),
        ], num_cols=1)

        _clickable_taxa_section("Ornithopoda", [
            ("Hadrosauridae", "duck-bills"),
            ("Edmontosaurus", ""),
            ("Parasaurolophus", ""),
            ("Iguanodontidae", ""),
            ("Iguanodon", ""),
            ("Hypsilophodontidae", ""),
        ], num_cols=1)

with st.expander("🦕 Other Mesozoic Reptiles", expanded=False):
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        _clickable_taxa_section("Pterosauria (flying reptiles)", [
            ("Pterosauria", ""),
            ("Pterodactylidae", ""),
            ("Pteranodon", ""),
            ("Azhdarchidae", ""),
            ("Quetzalcoatlus", ""),
            ("Rhamphorhynchidae", ""),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Marine Reptiles", [
            ("Ichthyosauria", ""),
            ("Ichthyosaurus", ""),
            ("Plesiosauria", ""),
            ("Plesiosaurus", ""),
            ("Elasmosauridae", ""),
            ("Pliosauridae", ""),
            ("Mosasauridae", ""),
            ("Mosasaurus", ""),
        ], num_cols=1)

        _clickable_taxa_section("Other Diapsids", [
            ("Crocodylomorpha", ""),
            ("Choristodera", ""),
        ], num_cols=1)

    with col_c:
        _clickable_taxa_section("Synapsids (mammal ancestors)", [
            ("Therapsida", ""),
            ("Dicynodontia", ""),
            ("Cynodontia", ""),
            ("Dimetrodon", ""),
            ("Lystrosaurus", ""),
        ], num_cols=1)

with st.expander("🐘 Mammalia — Mammals", expanded=False):
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        _clickable_taxa_section("Primates & Relatives", [
            ("Primates", ""),
            ("Hominidae", ""),
            ("Homo", ""),
            ("Australopithecus", ""),
            ("Plesiadapiformes", ""),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Ungulates & Large Herbivores", [
            ("Proboscidea", "elephants"),
            ("Mammuthus", "mammoths"),
            ("Mammut", "mastodons"),
            ("Perissodactyla", "horses, rhinos"),
            ("Equidae", "horses"),
            ("Equus", ""),
            ("Rhinocerotidae", ""),
            ("Brontotheriidae", ""),
            ("Artiodactyla", "even-toed"),
            ("Camelidae", ""),
            ("Bovidae", ""),
            ("Cervidae", "deer"),
        ], num_cols=1)

    with col_c:
        _clickable_taxa_section("Carnivora & Others", [
            ("Carnivora", "meat-eaters"),
            ("Felidae", "cats"),
            ("Smilodon", "sabre-tooth"),
            ("Canidae", "dogs"),
            ("Ursidae", "bears"),
            ("Cetacea", "whales"),
            ("Basilosauridae", ""),
            ("Chiroptera", "bats"),
            ("Rodentia", "rodents"),
            ("Xenarthra", "sloths, armadillos"),
            ("Megatherium", "giant sloth"),
            ("Marsupialia", ""),
        ], num_cols=1)

with st.expander("🦈 Marine Life & Invertebrates", expanded=False):
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        _clickable_taxa_section("Fish", [
            ("Chondrichthyes", "sharks & rays"),
            ("Carcharodon", "great white"),
            ("Megalodon", ""),
            ("Osteichthyes", "bony fish"),
            ("Actinopterygii", ""),
            ("Sarcopterygii", "lobe-finned"),
            ("Coelacanthiformes", ""),
            ("Placodermi", ""),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Molluscs", [
            ("Ammonoidea", "ammonites"),
            ("Nautiloidea", ""),
            ("Bivalvia", "clams, oysters"),
            ("Gastropoda", "snails"),
            ("Belemnitida", ""),
            ("Coleoidea", "squid, octopus"),
        ], num_cols=1)

        _clickable_taxa_section("Other Invertebrates", [
            ("Trilobita", "trilobites"),
            ("Eurypterida", "sea scorpions"),
        ], num_cols=1)

    with col_c:
        _clickable_taxa_section("Corals, Sponges & More", [
            ("Rugosa", "horn corals"),
            ("Tabulata", ""),
            ("Scleractinia", "stony corals"),
            ("Porifera", "sponges"),
            ("Stromatoporoidea", ""),
            ("Brachiopoda", ""),
            ("Bryozoa", ""),
            ("Echinodermata", ""),
            ("Crinoidea", "sea lilies"),
            ("Echinoidea", "sea urchins"),
            ("Graptolithina", ""),
            ("Foraminifera", ""),
        ], num_cols=1)

with st.expander("🦴 Early Vertebrates & Transitional Forms", expanded=False):
    col_a, col_b = st.columns(2)

    with col_a:
        _clickable_taxa_section("Early Tetrapods & Amphibians", [
            ("Tiktaalik", ""),
            ("Ichthyostega", ""),
            ("Acanthostega", ""),
            ("Temnospondyli", ""),
            ("Lepospondyli", ""),
            ("Lissamphibia", "modern amphibians"),
            ("Anura", "frogs"),
            ("Caudata", "salamanders"),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Reptiles & Birds", [
            ("Testudines", "turtles"),
            ("Squamata", "lizards & snakes"),
            ("Aves", "birds"),
            ("Archaeopteryx", ""),
            ("Enantiornithes", ""),
            ("Ichthyornis", ""),
            ("Sphenisciformes", "penguins"),
            ("Phorusrhacidae", "terror birds"),
            ("Dromornithidae", ""),
        ], num_cols=1)

with st.expander("🌿 Plants", expanded=False):
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        _clickable_taxa_section("Early Plants", [
            ("Lycopodiophyta", "club mosses"),
            ("Sphenopsida", "horsetails"),
            ("Pteridophyta", "ferns"),
            ("Progymnospermopsida", ""),
            ("Ginkgophyta", ""),
            ("Ginkgo", ""),
        ], num_cols=1)

    with col_b:
        _clickable_taxa_section("Seed Plants & Conifers", [
            ("Pinophyta", "conifers"),
            ("Pinaceae", ""),
            ("Cycadophyta", "cycads"),
            ("Bennettitales", ""),
            ("Cordaitales", ""),
            ("Glossopteridaceae", ""),
            ("Corystospermaceae", ""),
        ], num_cols=1)

    with col_c:
        _clickable_taxa_section("Flowering Plants", [
            ("Angiospermae", "flowering plants"),
            ("Magnoliopsida", ""),
            ("Arecaceae", "palms"),
            ("Poaceae", "grasses"),
            ("Nymphaeaceae", "water lilies"),
            ("Proteaceae", ""),
        ], num_cols=1)

st.markdown("---")
st.caption(
    "Tip: Click any button above to auto-fill the search bar, then click **Search PBDB**.  "
    "Higher-level clades (e.g. *Theropoda*, *Ammonoidea*, *Trilobita*) yield large datasets; "
    "individual genera (e.g. *Triceratops*, *Megalodon*, *Archaeopteryx*) give focused results."
)

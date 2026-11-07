# Integrated Multi-Radar Planning Suite & RF Simulation Tool (11+ Radars)

Production-ready, modular RF propagation, terrain line-of-sight (LoS), persistent SQLite radar database, and simultaneous multi-radar network simulation engine in Python for **11 or more heterogeneous fixed and mobile radar sites**.

---

## Master Requirements Verification Matrix

| # | Capability | Status | Module / Implementation |
| :---: | :--- | :---: | :--- |
| **1** | **Python RF Signal Simulation** | **Implemented** | Monostatic radar range equation ($R^4$ two-way path loss), SNR thresholding, Swerling Case 1 & Marcum Q ($P_d$), and Blake atmospheric absorption in `src/radar_site_planning/multi_radar_suite.py`. |
| **2** | **Elevation Ingestion (DTM, DTED 0/1/2)** | **Implemented** | Windowed reading of DTED-0/1/2 (`.dt0`, `.dt1`, `.dt2`) and GeoTIFF (Copernicus GLO-30, SRTM), bilinear interpolation, synthetic DTM generator, and Planetary Computer STAC fetcher in `src/radar_site_planning/terrain_manager.py`. |
| **3** | **Any Geometry Data Ingestion** | **Implemented** | GeoJSON, Well-Known Text (WKT), KML, and Shapefile ingestion via Shapely/GeoPandas (`GeometryIngestionManager`) for candidate deployment polygons, keep-out zones, and flight corridors. |
| **4** | **Project Range & Signal Coverage** | **Implemented** | Vectorized 2D and 3D volumetric coverage grids, 4/3 Earth radar horizon (ITU-R P.834), terrain LoS profiling, and RF power density heatmaps ($\text{dBm/m}^2$). |
| **5** | **Tilt Up / Down (Mechanical vs. Full AESA)** | **Implemented** | 3D rotation matrix (`compute_3d_rotation_matrix`) for legacy mechanical gimbals vs. dynamic phase steering with $\cos^{1.3}\theta$ scan loss, beam broadening ($\theta_{3\text{dB}}/\cos\theta$), and adaptive clutter nulling for Full AESA. |
| **6** | **Simultaneous 11+ Radar Planning** | **Implemented** | Multi-threaded `MultiRadarNetworkManager` evaluating $N \ge 11$ systems concurrently with $k$-coverage redundancy, joint detection probability $P_{d,\text{net}} = 1 - \prod(1 - P_{d,i})$, and mobile gap-filler screening. |
| **7** | **Fixed & Mobile Platform Support** | **Implemented** | Supports `FIXED`, `MOBILE_TACTICAL`, and `MOBILE_MANPADS_CUAS` units with configurable tower/mast heights and sector field-of-regard constraints. |
| **8** | **Radar Database & Dual-Mode Pipeline** | **Implemented** | SQLAlchemy 2.0 ORM (`RadarRecordORM`) + Pydantic v2 (`RadarRecord`) in `src/radar_site_planning/radar_db.py` with **Stage-1 Instant Pre-Check (<5 ms)** on save and **Stage-2 On-Demand Batch Network Simulation**. |
| **9** | **GIS Exports, C2 Dashboards, CLI & FastAPI** | **Implemented** | 3-band GeoTIFF & GeoJSON contour exporters (`exporters.py`), interactive Folium & Plotly C2 dashboards (`c2_dashboard.py`), CLI (`cli.py`), FastAPI service (`api.py`), and GitHub Actions CI (`ci.yml`). |

---

## Quick Start

### 1. Installation

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

python -m pip install -e ".[dev]"
```

### 2. Run End-to-End 11-Radar Database & Batch Simulation

```bash
python simulate_fleet_with_db.py
```

### 3. CLI Workflow (`radar-suite` / `radar-catalog`)

```bash
# Initialize SQLite database and import 11-radar heterogeneous fleet
radar-suite --db radar_catalog.db init
radar-suite --db radar_catalog.db import examples/fleet_11_radars.json
radar-suite --db radar_catalog.db list --active

# Execute Stage-2 Batch Simulation and export GeoTIFF, GeoJSON, Folium & Plotly C2 maps
radar-suite --db radar_catalog.db simulate \
  --bounds 580000 1480000 730000 1630000 \
  --resolution 2000 \
  --altitude 3000 \
  --geotiff outputs/network_coverage.tif \
  --geojson outputs/network_coverage.geojson \
  --folium outputs/c2_map.html \
  --plotly outputs/c2_dashboard.html
```

### 4. Run Automated Verification & Physics Test Suite

```bash
ruff check .
ruff format --check .
pytest -v
```

---

## Architecture Overview

- `radar_db.py` / `src/radar_site_planning/radar_db.py`: SQLAlchemy 2.0 ORM (`RadarRecordORM`) & `RadarDatabaseManager` with Stage-1 (`<5 ms`) analytical physics pre-check and Stage-2 network trigger.
- `multi_radar_suite.py` / `src/radar_site_planning/multi_radar_suite.py`: `RadarPlatform`, `MultiRadarNetworkManager`, Mechanical vs. Full AESA aperture physics, ITU-R P.526 knife-edge diffraction, Swerling/Marcum-Q $P_d$, volumetric 3D slices, and mobile gap-filler screening.
- `terrain_manager.py` / `src/radar_site_planning/terrain_manager.py`: `TerrainManager` (DTED 0/1/2 & GeoTIFF windowed reads, radial LoS profiler, Planetary Computer STAC downloader), `CoordinateTransformer` (WGS84 $\leftrightarrow$ metric UTM), and `GeometryIngestionManager` (GeoJSON, WKT, KML, Shapefile).
- `src/radar_site_planning/exporters.py`: Multi-band GeoTIFF (`export_coverage_geotiff`) and GeoJSON (`export_coverage_geojson`) exporters for QGIS, ATAK, and FalconView.
- `src/radar_site_planning/c2_dashboard.py`: Interactive Folium web maps (`generate_folium_c2_map`) and 4-panel Plotly C2 dashboards (`generate_plotly_c2_dashboard`).
- `src/radar_site_planning/api.py` & `src/radar_site_planning/cli.py`: FastAPI REST endpoints and CLI tools.

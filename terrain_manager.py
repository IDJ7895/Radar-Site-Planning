"""Root-level Terrain, DTED/GeoTIFF & Vector Geometry Ingestion Module."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from radar_site_planning.terrain_manager import (  # noqa: E402
    CoordinateTransformer,
    GeometryIngestionManager,
    TerrainManager,
    determine_utm_epsg,
    fetch_copernicus_dtm_tile,
)

__all__ = [
    "CoordinateTransformer",
    "GeometryIngestionManager",
    "TerrainManager",
    "determine_utm_epsg",
    "fetch_copernicus_dtm_tile",
]

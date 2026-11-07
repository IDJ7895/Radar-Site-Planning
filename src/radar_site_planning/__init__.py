"""Integrated Multi-Radar Planning Suite & RF Simulation Tool (11+ Radars)."""

from .c2_dashboard import generate_folium_c2_map, generate_plotly_c2_dashboard
from .exporters import export_coverage_geojson, export_coverage_geotiff
from .models import AntennaTechnology, Mobility, MobilityType, RadarRecord, StoredRadar
from .multi_radar_suite import (
    MultiRadarNetworkManager,
    RadarPlatform,
    compute_3d_rotation_matrix,
    compute_blake_chart_atmospheric_loss_db,
    compute_knife_edge_diffraction_loss_db,
    compute_marcum_q_pd,
)
from .radar_db import Base, RadarDatabaseManager, RadarRecordORM, Stage1SaveResult
from .terrain_manager import (
    CoordinateTransformer,
    GeometryIngestionManager,
    TerrainManager,
    determine_utm_epsg,
    fetch_copernicus_dtm_tile,
)

__all__ = [
    "AntennaTechnology",
    "Base",
    "CoordinateTransformer",
    "GeometryIngestionManager",
    "Mobility",
    "MobilityType",
    "MultiRadarNetworkManager",
    "RadarDatabaseManager",
    "RadarPlatform",
    "RadarRecord",
    "RadarRecordORM",
    "Stage1SaveResult",
    "StoredRadar",
    "TerrainManager",
    "compute_3d_rotation_matrix",
    "compute_blake_chart_atmospheric_loss_db",
    "compute_knife_edge_diffraction_loss_db",
    "compute_marcum_q_pd",
    "determine_utm_epsg",
    "export_coverage_geojson",
    "export_coverage_geotiff",
    "fetch_copernicus_dtm_tile",
    "generate_folium_c2_map",
    "generate_plotly_c2_dashboard",
]

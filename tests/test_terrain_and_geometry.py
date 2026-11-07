"""Tests for Milestone 1: DTED/GeoTIFF Ingestion, Coordinates & Geometry (GH-03, GH-04)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from radar_site_planning import (
    CoordinateTransformer,
    GeometryIngestionManager,
    TerrainManager,
    determine_utm_epsg,
)


def test_wgs84_utm_coordinate_transforms():
    # Bangkok / Central Thailand is UTM Zone 47N (EPSG:32647)
    epsg = determine_utm_epsg(100.5018, 13.7563)
    assert epsg == 32647

    transformer = CoordinateTransformer(utm_epsg=epsg)
    easting, northing = transformer.wgs84_to_utm(100.5018, 13.7563)
    assert CoordinateTransformer.is_metric_utm(float(northing), float(easting))

    lon_back, lat_back = transformer.utm_to_wgs84(easting, northing)
    assert np.isclose(lon_back, 100.5018, atol=1e-5)
    assert np.isclose(lat_back, 13.7563, atol=1e-5)


def test_geotiff_windowed_read_and_los_profiler(tmp_path: Path):
    bounds = (580000.0, 1480000.0, 680000.0, 1580000.0)
    tm = TerrainManager.create_synthetic_terrain(
        bounds=bounds, resolution_m=2000.0, base_elevation_m=50.0, ridge_height_m=800.0
    )
    tif_path = tm.save_geotiff(tmp_path / "synthetic_dtm.tif")
    assert tif_path.exists()

    # Reload via windowed read
    sub_bounds = (590000.0, 1490000.0, 670000.0, 1570000.0)
    tm_windowed = TerrainManager(raster_path=tif_path, bounds=sub_bounds)
    assert tm_windowed.elevation_grid is not None
    el_center = tm_windowed.sample_elevation(630000.0, 1530000.0)
    assert el_center > 50.0

    # Test LoS profile extraction across the mountain ridge
    profile_low = tm.extract_los_profile(
        radar_x=590000.0,
        radar_y=1570000.0,
        radar_alt_amsl=100.0,
        target_x=670000.0,
        target_y=1490000.0,
        target_alt_amsl=200.0,
    )
    # Low-altitude ray across an 800m ridge is obstructed
    assert bool(profile_low["los_clear"]) is False
    assert float(profile_low["max_obstruction_m"]) > 0.0

    # High-altitude target (6000m) clears the ridge
    profile_high = tm.extract_los_profile(
        radar_x=590000.0,
        radar_y=1570000.0,
        radar_alt_amsl=100.0,
        target_x=670000.0,
        target_y=1490000.0,
        target_alt_amsl=6000.0,
    )
    assert bool(profile_high["los_clear"]) is True


def test_vector_geometry_ingestion_geojson_wkt_kml(tmp_path: Path):
    # 1. WKT Polygon
    poly_wkt = (
        "POLYGON ((600000 1500000, 620000 1500000, 620000 1520000, 600000 1520000, 600000 1500000))"
    )
    geoms_wkt = GeometryIngestionManager.load_geometry(poly_wkt)
    assert len(geoms_wkt) == 1
    assert geoms_wkt[0].geom_type == "Polygon"

    # Candidate point sampling inside deployment polygon
    pts = GeometryIngestionManager.sample_candidate_points_in_polygon(
        geoms_wkt[0], spacing_m=10000.0
    )
    assert len(pts) >= 4

    # 2. GeoJSON FeatureCollection file
    fc = GeometryIngestionManager.to_geojson_feature_collection(
        geoms_wkt, [{"zone": "mobile_deploy_alpha"}]
    )
    geojson_path = tmp_path / "deploy.geojson"
    geojson_path.write_text(json.dumps(fc), encoding="utf-8")
    geoms_gj = GeometryIngestionManager.load_geometry(geojson_path)
    assert len(geoms_gj) == 1

    # 3. KML file
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <LineString>
            <coordinates>600000,1500000,0 650000,1550000,3000</coordinates>
          </LineString>
        </Placemark>
      </Document>
    </kml>"""
    kml_path = tmp_path / "corridor.kml"
    kml_path.write_text(kml_content, encoding="utf-8")
    geoms_kml = GeometryIngestionManager.load_geometry(kml_path)
    assert len(geoms_kml) == 1
    assert geoms_kml[0].geom_type == "LineString"

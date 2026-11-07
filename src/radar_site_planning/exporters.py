"""Layered GeoTIFF & GeoJSON Vector Contour Exporter for GIS/C2 Consoles (GH-11)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import MultiPoint, Point, Polygon, mapping

from .multi_radar_suite import RadarPlatform
from .terrain_manager import CoordinateTransformer


def export_coverage_geotiff(
    coverage_results: dict[str, np.ndarray],
    output_path: str | Path,
    crs_epsg: int = 32647,
) -> Path:
    """Exports a 3-band layered GeoTIFF containing:
    - Band 1: overlap_count (k-coverage)
    - Band 2: joint_pd (Cumulative multi-radar detection probability P_{d,net})
    - Band 3: max_snr_db (Maximum received SNR in dB)
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    x_coords = coverage_results["x_coords"]
    y_coords = coverage_results["y_coords"]
    dx = float(x_coords[1] - x_coords[0]) if len(x_coords) > 1 else 1000.0
    dy = float(y_coords[1] - y_coords[0]) if len(y_coords) > 1 else 1000.0

    min_x = float(x_coords[0])
    max_x = float(x_coords[-1] + dx)
    min_y = float(y_coords[0])
    max_y = float(y_coords[-1] + dy)

    overlap = np.flipud(coverage_results["overlap_count"]).astype(np.float32)
    joint_pd = np.flipud(coverage_results["joint_pd"]).astype(np.float32)
    max_snr = np.flipud(coverage_results["max_snr_db"]).astype(np.float32)

    ny, nx = overlap.shape
    transform = from_bounds(min_x, min_y, max_x, max_y, width=nx, height=ny)

    with rasterio.open(
        out,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=3,
        dtype="float32",
        crs=f"EPSG:{crs_epsg}",
        transform=transform,
    ) as dst:
        dst.write(overlap, 1)
        dst.set_band_description(1, "k_coverage_overlap_count")
        dst.write(joint_pd, 2)
        dst.set_band_description(2, "joint_network_pd")
        dst.write(max_snr, 3)
        dst.set_band_description(3, "max_snr_db")

    return out


def _build_sector_polygon_wgs84(
    radar: RadarPlatform,
    transformer: CoordinateTransformer | None,
    target_rcs_m2: float = 1.0,
    num_Manage_pts: int = 36,
) -> Polygon:
    """Builds a WGS84 polygon representing a radar's effective range and azimuth sector."""
    r_eff_m = radar.calculate_free_space_rmax(target_rcs_m2)
    is_utm = CoordinateTransformer.is_metric_utm(radar.lat, radar.lon)

    if radar.field_of_regard_az_deg >= 360.0:
        angles = np.linspace(0.0, 360.0, num_Manage_pts, endpoint=False)
        pts_xy = [
            (
                radar.lon + r_eff_m * float(np.sin(np.radians(a))),
                radar.lat + r_eff_m * float(np.cos(np.radians(a))),
            )
            for a in angles
        ]
        pts_xy.append(pts_xy[0])
    else:
        half = radar.field_of_regard_az_deg / 2.0
        angles = np.linspace(
            radar.azimuth_boresight_deg - half,
            radar.azimuth_boresight_deg + half,
            num_Manage_pts,
        )
        pts_xy = [(radar.lon, radar.lat)]
        for a in angles:
            pts_xy.append(
                (
                    radar.lon + r_eff_m * float(np.sin(np.radians(a))),
                    radar.lat + r_eff_m * float(np.cos(np.radians(a))),
                )
            )
        pts_xy.append((radar.lon, radar.lat))

    if is_utm and transformer is not None:
        wgs_pts = []
        for x_m, y_m in pts_xy:
            lon_deg, lat_deg = transformer.utm_to_wgs84(x_m, y_m)
            wgs_pts.append((float(lon_deg), float(lat_deg)))
        return Polygon(wgs_pts)

    return Polygon(pts_xy)


def export_coverage_geojson(
    coverage_results: dict[str, np.ndarray],
    radars: list[RadarPlatform] | dict[str, RadarPlatform],
    output_path: str | Path,
    utm_epsg: int = 32647,
    target_rcs_m2: float = 1.0,
) -> Path:
    """Exports radar sites, sector footprints, and k-coverage envelopes as GeoJSON
    for QGIS, ATAK, and FalconView C2 consoles.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    radar_list = list(radars.values()) if isinstance(radars, dict) else list(radars)
    transformer = CoordinateTransformer(utm_epsg=utm_epsg)
    features: list[dict[str, Any]] = []

    for r in radar_list:
        is_utm = CoordinateTransformer.is_metric_utm(r.lat, r.lon)
        if is_utm:
            lon_wgs, lat_wgs = transformer.utm_to_wgs84(r.lon, r.lat)
        else:
            lon_wgs, lat_wgs = r.lon, r.lat

        site_props = {
            "feature_type": "radar_site",
            "site_id": r.site_id,
            "name": r.name,
            "brand": r.brand,
            "model": r.model,
            "radar_category": r.radar_category,
            "mobility": r.mobility.value,
            "tech": r.tech.value,
            "instrumented_max_range_km": r.instrumented_max_range_km,
            "effective_free_space_rmax_km": round(
                r.calculate_free_space_rmax(target_rcs_m2) / 1000.0, 2
            ),
            "peak_power_kw": r.peak_power_kw,
            "frequency_ghz": r.frequency_ghz,
            "is_active": r.is_active,
        }
        features.append(
            {
                "type": "Feature",
                "properties": site_props,
                "geometry": mapping(Point(float(lon_wgs), float(lat_wgs))),
            }
        )

        sector_poly = _build_sector_polygon_wgs84(
            r, transformer if is_utm else None, target_rcs_m2=target_rcs_m2
        )
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "radar_sector_footprint",
                    "site_id": r.site_id,
                    "name": r.name,
                    "mobility": r.mobility.value,
                    "tech": r.tech.value,
                },
                "geometry": mapping(sector_poly),
            }
        )

    # Export k >= 1 and k >= 2 convex hull coverage contours
    overlap = coverage_results["overlap_count"]
    x_coords = coverage_results["x_coords"]
    y_coords = coverage_results["y_coords"]
    xx, yy = np.meshgrid(x_coords, y_coords)
    grid_is_utm = CoordinateTransformer.is_metric_utm(float(y_coords[0]), float(x_coords[0]))

    for k_thresh, label in [(1, "k_ge_1_detected_envelope"), (2, "k_ge_2_redundant_envelope")]:
        mask = overlap >= k_thresh
        if np.any(mask):
            xs_cov = xx[mask]
            ys_cov = yy[mask]
            if grid_is_utm:
                lons_cov, lats_cov = transformer.utm_to_wgs84(xs_cov, ys_cov)
                pts = list(
                    zip(
                        np.asarray(lons_cov, dtype=float),
                        np.asarray(lats_cov, dtype=float),
                        strict=False,
                    )
                )
            else:
                pts = list(zip(xs_cov.astype(float), ys_cov.astype(float), strict=False))
            if len(pts) >= 3:
                hull = MultiPoint(pts).convex_hull
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "feature_type": "coverage_contour",
                            "contour_level": label,
                            "min_k_overlap": k_thresh,
                            "coverage_fraction": round(float(np.mean(mask)), 4),
                        },
                        "geometry": mapping(hull),
                    }
                )

    collection = {
        "type": "FeatureCollection",
        "features": features,
    }
    out.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    return out

"""Geospatial, Terrain (DTED 0/1/2, GeoTIFF, STAC) & Vector Geometry Ingestion (GH-03, GH-04)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.windows import from_bounds as window_from_bounds
from shapely import wkt
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry


def determine_utm_epsg(lon_deg: float, lat_deg: float) -> int:
    """Computes the metric UTM EPSG code (326XX North / 327XX South) for a WGS84 coordinate."""
    zone = int((lon_deg + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 if lat_deg >= 0.0 else 32700) + zone


class CoordinateTransformer:
    """Automatic coordinate transformations between WGS84 (EPSG:4326) and metric UTM grids."""

    def __init__(self, utm_epsg: int = 32647) -> None:
        self.utm_epsg = utm_epsg
        self._to_utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
        self._to_wgs84 = pyproj.Transformer.from_crs(
            f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
        )

    @classmethod
    def from_wgs84_Origin(cls, lon_deg: float, lat_deg: float) -> CoordinateTransformer:
        return cls(utm_epsg=determine_utm_epsg(lon_deg, lat_deg))

    @staticmethod
    def is_metric_utm(lat_or_northing: float, lon_or_easting: float) -> bool:
        """Detects whether coordinates are in metric UTM meters rather than WGS84 degrees."""
        return abs(lat_or_northing) > 90.0 or abs(lon_or_easting) > 180.0

    def wgs84_to_utm(
        self, lon_deg: float | np.ndarray, lat_deg: float | np.ndarray
    ) -> tuple[float | np.ndarray, float | np.ndarray]:
        """Transforms WGS84 (lon, lat) degrees to metric UTM (easting, northing) meters."""
        easting, northing = self._to_utm.transform(lon_deg, lat_deg)
        return easting, northing

    def utm_to_wgs84(
        self, easting_m: float | np.ndarray, northing_m: float | np.ndarray
    ) -> tuple[float | np.ndarray, float | np.ndarray]:
        """Transforms metric UTM (easting, northing) meters to WGS84 (lon, lat) degrees."""
        lon, lat = self._to_wgs84.transform(easting_m, northing_m)
        return lon, lat


def fetch_copernicus_dtm_tile(
    bbox_wgs84: tuple[float, float, float, float], output_path: str | Path
) -> Path:
    """Pulls a 30m Copernicus DEM tile on-demand for a given bounding box
    (min_lon, min_lat, max_lon, max_lat) via Planetary Computer STAC API.
    """
    import planetary_computer
    import pystac_client

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(collections=["cop-dem-glo-30"], bbox=bbox_wgs84)
    items = list(search.items())
    if not items:
        raise FileNotFoundError(f"No elevation tiles found for bbox: {bbox_wgs84}")

    asset_href = items[0].assets["data"].href
    out_file = Path(output_path)
    with rasterio.open(asset_href) as src:
        window = window_from_bounds(*bbox_wgs84, transform=src.transform)
        elevation_data = src.read(1, window=window)
        win_transform = src.window_transform(window)

        profile = src.profile.copy()
        profile.update(
            {
                "height": int(window.height),
                "width": int(window.width),
                "transform": win_transform,
            }
        )
        with rasterio.open(out_file, "w", **profile) as dst:
            dst.write(elevation_data, 1)
    return out_file


class TerrainManager:
    """Ingests DTED Level 0/1/2 (.dt0, .dt1, .dt2) and GeoTIFF DEMs with windowed reads,
    bilinear interpolation, and radial line-of-sight (LoS) profiling.
    """

    def __init__(
        self,
        raster_path: str | Path | None = None,
        bounds: tuple[float, float, float, float] | None = None,
        elevation_grid: np.ndarray | None = None,
        crs_epsg: int = 32647,
    ) -> None:
        self.raster_path = Path(raster_path) if raster_path else None
        self.crs_epsg = crs_epsg
        self.bounds = bounds  # (min_x, min_y, max_x, max_y)
        self.elevation_grid = elevation_grid  # shape (ny, nx), row 0 = min_y, col 0 = min_x

        if self.raster_path is not None and self.raster_path.exists():
            self.load_raster(self.raster_path, window_bounds=bounds)

    def load_raster(
        self,
        raster_path: str | Path,
        window_bounds: tuple[float, float, float, float] | None = None,
    ) -> np.ndarray:
        """Loads a DTED (0/1/2) or GeoTIFF raster using rasterio windowed reading."""
        path = Path(raster_path)
        with rasterio.open(path) as src:
            if window_bounds is not None:
                win = window_from_bounds(*window_bounds, transform=src.transform)
                data = src.read(1, window=win).astype(np.float32)
                self.bounds = window_bounds
            else:
                data = src.read(1).astype(np.float32)
                b = src.bounds
                self.bounds = (float(b.left), float(b.bottom), float(b.right), float(b.top))

            # Standard rasterio row 0 is North (top); flip vertically so row 0 corresponds to min_y
            self.elevation_grid = np.flipud(data)
            if src.crs and src.crs.to_epsg():
                self.crs_epsg = int(src.crs.to_epsg())
        return self.elevation_grid

    @classmethod
    def create_synthetic_terrain(
        cls,
        bounds: tuple[float, float, float, float] = (580000.0, 1480000.0, 730000.0, 1630000.0),
        resolution_m: float = 1000.0,
        base_elevation_m: float = 50.0,
        ridge_height_m: float = 650.0,
        crs_epsg: int = 32647,
    ) -> TerrainManager:
        """Creates a realistic synthetic DTM grid with mountain ridges and valleys."""
        min_x, min_y, max_x, max_y = bounds
        xs = np.arange(min_x, max_x, resolution_m)
        ys = np.arange(min_y, max_y, resolution_m)
        xx, yy = np.meshgrid(xs, ys)

        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)

        # Diagonal mountain ridge + secondary peak + gentle undulating terrain
        ridge_dist = ((xx - cx) * 0.7 - (yy - cy) * 0.7) / (0.12 * span_x)
        ridge = ridge_height_m * np.exp(-(ridge_dist**2))

        peak_dist2 = ((xx - (cx + 0.2 * span_x)) ** 2 + (yy - (cy - 0.15 * span_y)) ** 2) / (
            (0.08 * span_x) ** 2
        )
        secondary_peak = 0.65 * ridge_height_m * np.exp(-peak_dist2)

        undulation = (
            25.0
            * np.sin(2.0 * np.pi * (xx - min_x) / (0.5 * span_x))
            * np.cos(2.0 * np.pi * (yy - min_y) / (0.5 * span_y))
        )
        grid = np.maximum(base_elevation_m + ridge + secondary_peak + undulation, 0.0).astype(
            np.float32
        )
        return cls(bounds=bounds, elevation_grid=grid, crs_epsg=crs_epsg)

    def save_geotiff(self, output_path: str | Path) -> Path:
        """Writes the current elevation grid to a GeoTIFF file."""
        if self.elevation_grid is None or self.bounds is None:
            raise ValueError("No elevation grid loaded to save")
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        ny, nx = self.elevation_grid.shape
        transform = transform_from_bounds(*self.bounds, width=nx, height=ny)
        # Flip vertically so row 0 is top (North) per GeoTIFF convention
        top_down = np.flipud(self.elevation_grid).astype(np.float32)
        with rasterio.open(
            out,
            "w",
            driver="GTiff",
            height=ny,
            width=nx,
            count=1,
            dtype="float32",
            crs=f"EPSG:{self.crs_epsg}",
            transform=transform,
        ) as dst:
            dst.write(top_down, 1)
        return out

    def sample_elevation(self, x: float | np.ndarray, y: float | np.ndarray) -> float | np.ndarray:
        """Bilinearly interpolates terrain elevation (m AMSL) at given coordinates."""
        if self.elevation_grid is None or self.bounds is None:
            if np.ndim(x) == 0 and np.ndim(y) == 0:
                return 0.0
            return np.zeros_like(np.asarray(x, dtype=np.float32))

        min_x, min_y, max_x, max_y = self.bounds
        ny, nx = self.elevation_grid.shape

        x_arr = np.asarray(x, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)

        u = np.clip((x_arr - min_x) / max(max_x - min_x, 1e-9) * (nx - 1), 0.0, max(nx - 1, 0))
        v = np.clip((y_arr - min_y) / max(max_y - min_y, 1e-9) * (ny - 1), 0.0, max(ny - 1, 0))

        u0 = np.floor(u).astype(np.int32)
        v0 = np.floor(v).astype(np.int32)
        u1 = np.minimum(u0 + 1, nx - 1)
        v1 = np.minimum(v0 + 1, ny - 1)

        du = u - u0
        dv = v - v0

        z00 = self.elevation_grid[v0, u0]
        z10 = self.elevation_grid[v0, u1]
        z01 = self.elevation_grid[v1, u0]
        z11 = self.elevation_grid[v1, u1]

        interp = (
            z00 * (1.0 - du) * (1.0 - dv)
            + z10 * du * (1.0 - dv)
            + z01 * (1.0 - du) * dv
            + z11 * du * dv
        )
        if np.ndim(x) == 0 and np.ndim(y) == 0:
            return float(interp)
        return interp.astype(np.float32)

    def extract_los_profile(
        self,
        radar_x: float,
        radar_y: float,
        radar_alt_amsl: float,
        target_x: float | np.ndarray,
        target_y: float | np.ndarray,
        target_alt_amsl: float,
        num_samples: int = 24,
    ) -> dict[str, np.ndarray]:
        """Vectorized radial line-of-sight (LoS) profile and obstacle clearance extraction
        accounting for 4/3 effective Earth curvature (ITU-R P.834).

        Returns:
            - 'max_obstruction_m': Max terrain + Earth bulge protrusion above direct ray (m).
              Positive values mean the direct LoS ray is obstructed by terrain.
            - 'd1_m': Distance from radar to dominant obstructing peak (m).
            - 'd2_m': Distance from dominant obstructing peak to target (m).
            - 'los_clear': Boolean array where True indicates unobstructed optical/RF LoS.
        """
        tx = np.asarray(target_x, dtype=np.float64)
        ty = np.asarray(target_y, dtype=np.float64)
        total_dist = np.hypot(tx - radar_x, ty - radar_y)

        # Sample fractional points along ray (excluding endpoints 0 and 1)
        fractions = np.linspace(0.05, 0.95, num_samples)
        re_eff = 6371000.0 * (4.0 / 3.0)

        max_protrusion = np.full(tx.shape, -1e6, dtype=np.float64)
        best_d1 = np.maximum(0.5 * total_dist, 1.0)
        best_d2 = np.maximum(0.5 * total_dist, 1.0)

        for frac in fractions:
            sx = radar_x + frac * (tx - radar_x)
            sy = radar_y + frac * (ty - radar_y)
            terrain_h = np.asarray(self.sample_elevation(sx, sy), dtype=np.float64)

            d1 = np.maximum(frac * total_dist, 1.0)
            d2 = np.maximum((1.0 - frac) * total_dist, 1.0)

            # Earth curvature bulge at sample point (ITU-R P.834 4/3 Earth)
            earth_bulge = (d1 * d2) / (2.0 * re_eff)

            # Direct ray height at fraction frac
            ray_h = radar_alt_amsl + frac * (target_alt_amsl - radar_alt_amsl)

            # Protrusion of terrain + earth curvature above direct ray
            protrusion = (terrain_h + earth_bulge) - ray_h

            update_mask = protrusion > max_protrusion
            max_protrusion = np.where(update_mask, protrusion, max_protrusion)
            best_d1 = np.where(update_mask, d1, best_d1)
            best_d2 = np.where(update_mask, d2, best_d2)

        los_clear = max_protrusion <= 0.0
        return {
            "max_obstruction_m": max_protrusion,
            "clearance_m": -max_protrusion,
            "d1_m": best_d1,
            "d2_m": best_d2,
            "los_clear": los_clear,
        }


class GeometryIngestionManager:
    """Ingests GeoJSON, WKT, KML, and Shapefile vector geometries for deployment zones,
    keep-out defilades, flight corridors, and target trajectories.
    """

    @staticmethod
    def load_geometry(source: str | Path | dict[str, Any]) -> list[BaseGeometry]:
        """Loads vector geometries from a file path (GeoJSON, WKT, KML, SHP) or raw string/dict."""
        if isinstance(source, dict):
            return GeometryIngestionManager._parse_geojson_dict(source)

        if isinstance(source, str) and not Path(source).exists():
            stripped = source.strip()
            if stripped.startswith("{"):
                return GeometryIngestionManager._parse_geojson_dict(json.loads(stripped))
            return [wkt.loads(stripped)]

        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in {".geojson", ".json"}:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return GeometryIngestionManager._parse_geojson_dict(payload)
        if suffix == ".wkt":
            lines = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return [wkt.loads(line) for line in lines]
        if suffix == ".kml":
            return GeometryIngestionManager._parse_kml(path.read_text(encoding="utf-8"))
        if suffix == ".shp":
            import geopandas as gpd

            gdf = gpd.read_file(path)
            return list(gdf.geometry)

        raise ValueError(f"Unsupported geometry format: {path}")

    @staticmethod
    def _parse_geojson_dict(payload: dict[str, Any]) -> list[BaseGeometry]:
        gtype = payload.get("type")
        if gtype == "FeatureCollection":
            return [
                shape(feat["geometry"])
                for feat in payload.get("features", [])
                if feat.get("geometry")
            ]
        if gtype == "Feature":
            return [shape(payload["geometry"])]
        return [shape(payload)]

    @staticmethod
    def _parse_kml(kml_text: str) -> list[BaseGeometry]:
        root = ET.fromstring(kml_text)
        geometries: list[BaseGeometry] = []
        for elem in root.iter():
            if elem.tag.endswith("coordinates") and elem.text:
                pts = []
                for token in elem.text.strip().split():
                    parts = [float(v) for v in token.split(",")]
                    if len(parts) >= 2:
                        pts.append((parts[0], parts[1]))
                if len(pts) == 1:
                    geometries.append(Point(pts[0]))
                elif len(pts) >= 4 and pts[0] == pts[-1]:
                    geometries.append(Polygon(pts))
                elif len(pts) >= 2:
                    geometries.append(LineString(pts))
        return geometries

    @staticmethod
    def sample_candidate_points_in_polygon(
        polygon: Polygon, spacing_m: float, keep_out_zones: list[Polygon] | None = None
    ) -> list[tuple[float, float]]:
        """Generates candidate mobile radar deployment coordinates inside a polygon,
        excluding any keep-out defilade polygons.
        """
        min_x, min_y, max_x, max_y = polygon.bounds
        xs = np.arange(min_x, max_x + spacing_m * 0.5, spacing_m)
        ys = np.arange(min_y, max_y + spacing_m * 0.5, spacing_m)
        candidates: list[tuple[float, float]] = []
        for y in ys:
            for x in xs:
                pt = Point(float(x), float(y))
                if polygon.contains(pt) or polygon.touches(pt):
                    if keep_out_zones and any(zone.contains(pt) for zone in keep_out_zones):
                        continue
                    candidates.append((float(x), float(y)))
        return candidates

    @staticmethod
    def to_geojson_feature_collection(
        geometries: list[BaseGeometry], properties_list: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        features = []
        for idx, geom in enumerate(geometries):
            props = properties_list[idx] if properties_list and idx < len(properties_list) else {}
            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": mapping(geom),
                }
            )
        return {"type": "FeatureCollection", "features": features}

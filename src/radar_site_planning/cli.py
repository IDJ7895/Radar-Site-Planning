"""CLI for Radar Catalog CRUD, Stage-1 Precheck & Stage-2 Batch Simulation (GH-13)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .c2_dashboard import generate_folium_c2_map, generate_plotly_c2_dashboard
from .exporters import export_coverage_geojson, export_coverage_geotiff
from .multi_radar_suite import MultiRadarNetworkManager
from .radar_db import RadarDatabaseManager


def _read_payload(path: Path) -> Any:
    text_content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text_content)
    return json.loads(text_content)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Integrated Multi-Radar Planning Suite & Catalog CLI"
    )
    parser.add_argument(
        "--db",
        default="radar_catalog.db",
        help="SQLite database path or URL (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize the SQLite radar catalog schema")

    put = sub.add_parser("put", help="Insert or replace one radar record and run Stage-1 Pre-Check")
    put.add_argument("file", type=Path)

    batch = sub.add_parser("import", help="Atomically upsert a JSON/YAML array of radar records")
    batch.add_argument("file", type=Path)

    listing = sub.add_parser("list", help="List radar records as JSON")
    listing.add_argument("--active", action="store_true")

    for name in ("get", "delete", "patch"):
        cmd = sub.add_parser(name)
        cmd.add_argument("site_id")
        if name == "patch":
            cmd.add_argument("file", type=Path, help="JSON/YAML object with changed fields")

    sub.add_parser("export", help="Export re-importable radar records as a JSON array to stdout")

    sim = sub.add_parser(
        "simulate", help="Execute Stage-2 Batch Multi-Radar Network Simulation from DB"
    )
    sim.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        metavar=("MIN_X", "MIN_Y", "MAX_X", "MAX_Y"),
        default=None,
        help="Grid bounds (min_x min_y max_x max_y)",
    )
    sim.add_argument("--resolution", type=float, default=2000.0, help="Grid resolution in meters")
    sim.add_argument("--altitude", type=float, default=3000.0, help="Target altitude (m AMSL)")
    sim.add_argument("--rcs", type=float, default=1.0, help="Target RCS (m^2)")
    sim.add_argument("--geotiff", type=Path, default=None, help="Optional GeoTIFF export path")
    sim.add_argument("--geojson", type=Path, default=None, help="Optional GeoJSON export path")
    sim.add_argument("--folium", type=Path, default=None, help="Optional Folium HTML map path")
    sim.add_argument(
        "--plotly", type=Path, default=None, help="Optional Plotly HTML dashboard path"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _read_payload(args.file) if hasattr(args, "file") else None
        if args.command in {"put", "patch"} and not isinstance(payload, dict):
            raise ValueError("Expected a JSON/YAML object")
        if args.command == "import":
            if isinstance(payload, dict) and "radars" in payload:
                payload = payload["radars"]
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise ValueError("Expected a JSON/YAML array of objects")

        with RadarDatabaseManager(args.db) as catalog:
            match args.command:
                case "init":
                    result: Any = {"status": "initialized", "database": str(args.db)}
                case "put":
                    saved = catalog.add_or_update_radar(payload)
                    result = {
                        **saved.model_dump(mode="json"),
                        "instant_precheck": saved["instant_precheck"],
                    }
                case "import":
                    saved_batch = catalog.import_radars(payload)
                    result = {"status": "saved", "count": len(saved_batch)}
                case "get":
                    result = catalog.get_radar(args.site_id).model_dump(mode="json")
                case "list":
                    result = [
                        row.model_dump(mode="json")
                        for row in catalog.list_radars(active_only=args.active)
                    ]
                case "patch":
                    result = catalog.patch_radar(args.site_id, payload).model_dump(mode="json")
                case "delete":
                    catalog.delete_radar(args.site_id)
                    result = {"status": "deleted", "site_id": args.site_id}
                case "export":
                    result = [
                        row.model_dump(mode="json", exclude={"id", "created_at", "updated_at"})
                        for row in catalog.list_radars()
                    ]
                case "simulate":
                    bounds_tuple = tuple(args.bounds) if args.bounds is not None else None
                    mgr = MultiRadarNetworkManager()
                    loaded = mgr.load_active_fleet_from_db(catalog)
                    if loaded == 0:
                        raise ValueError("No active radars in database")
                    if bounds_tuple is None:
                        lats = [r.lat for r in mgr.radars.values()]
                        lons = [r.lon for r in mgr.radars.values()]
                        pad = 50000.0 if max(map(abs, lats)) > 90.0 else 0.5
                        bounds_tuple = (
                            min(lons) - pad,
                            min(lats) - pad,
                            max(lons) + pad,
                            max(lats) + pad,
                        )
                    sim_res = mgr.compute_network_coverage_grid(
                        grid_bounds=bounds_tuple,  # type: ignore[arg-type]
                        grid_resolution_m=args.resolution,
                        target_altitude_amsl=args.altitude,
                        target_rcs_m2=args.rcs,
                    )
                    if args.geotiff:
                        export_coverage_geotiff(sim_res, args.geotiff)
                    if args.geojson:
                        export_coverage_geojson(sim_res, mgr.radars, args.geojson)
                    if args.folium:
                        generate_folium_c2_map(mgr.radars, sim_res, args.folium)
                    if args.plotly:
                        generate_plotly_c2_dashboard(mgr.radars, sim_res, args.plotly)

                    overlap = sim_res["overlap_count"]
                    joint_pd = sim_res["joint_pd"]
                    result = {
                        "status": "simulated",
                        "active_radars": loaded,
                        "max_overlap": int(np.max(overlap)),
                        "k_ge_1_coverage_pct": round(float(np.mean(overlap >= 1) * 100.0), 2),
                        "k_ge_2_redundant_pct": round(float(np.mean(overlap >= 2) * 100.0), 2),
                        "high_confidence_pd_ge_90_pct": round(
                            float(np.mean(joint_pd >= 0.90) * 100.0), 2
                        ),
                    }

        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except KeyError as error:
        print(f"Site not found: {error.args[0]}", file=sys.stderr)
    except (ValidationError, ValueError, OSError, SQLAlchemyError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
    return 2

"""Tests for Milestones 3 & 4: 11+ Radar Network, GIS Exports, C2 & API (GH-08 to GH-14)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from fastapi.testclient import TestClient

from radar_site_planning import (
    MultiRadarNetworkManager,
    RadarDatabaseManager,
    TerrainManager,
    export_coverage_geojson,
    export_coverage_geotiff,
    generate_folium_c2_map,
    generate_plotly_c2_dashboard,
)
from radar_site_planning.api import create_app
from radar_site_planning.cli import main as cli_main
from simulate_fleet_with_db import run_simulation


def test_end_to_end_11_radar_simulation_script(tmp_path: Path):
    db_file = tmp_path / "rtaf_radar_simulation.db"
    results = run_simulation(f"sqlite:///{db_file.as_posix()}")

    overlap = results["overlap_count"]
    joint_pd = results["joint_pd"]
    max_snr = results["max_snr_db"]

    assert overlap.shape == (75, 75)
    assert int(np.max(overlap)) >= 8
    assert float(np.mean(overlap >= 1)) > 0.90
    assert float(np.mean(overlap >= 2)) > 0.80
    assert float(np.mean(joint_pd >= 0.90)) > 0.80
    assert float(np.max(max_snr)) > 20.0


def test_terrain_masked_network_and_mobile_gap_filler_screening(tmp_path: Path):
    bounds = (580000.0, 1480000.0, 730000.0, 1630000.0)
    tm = TerrainManager.create_synthetic_terrain(
        bounds=bounds, resolution_m=5000.0, base_elevation_m=50.0, ridge_height_m=900.0
    )

    root = Path(__file__).resolve().parent.parent
    db = RadarDatabaseManager(tmp_path / "fleet.db")
    db.load_catalog_file(root / "examples" / "fleet_11_radars.json")

    mgr = MultiRadarNetworkManager(terrain_manager=tm)
    count = mgr.load_active_fleet_from_db(db)
    assert count == 11

    # Volumetric coverage across 2 altitudes
    vol = mgr.compute_volumetric_coverage(
        grid_bounds=bounds,
        grid_resolution_m=15000.0,
        altitudes_amsl=[300.0, 3000.0],
        target_rcs_m2=1.0,
    )
    assert vol["overlap_3d"].shape[0] == 2

    # Mobile gap-filler screening at low altitude (250m AMSL)
    candidates = [(610000.0, 1510000.0), (660000.0, 1560000.0), (700000.0, 1600000.0)]
    rankings = mgr.screen_mobile_gap_filler_sites(
        candidate_coords=candidates,
        grid_bounds=bounds,
        grid_resolution_m=15000.0,
        target_altitude_amsl=250.0,
    )
    assert len(rankings) == 3
    assert rankings[0]["newly_covered_blind_cells"] >= rankings[-1]["newly_covered_blind_cells"]
    db.close()


def test_geotiff_geojson_and_c2_dashboards(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    db = RadarDatabaseManager(tmp_path / "export_test.db")
    db.load_catalog_file(root / "examples" / "fleet_11_radars.json")

    mgr = MultiRadarNetworkManager()
    mgr.load_active_fleet_from_db(db)
    bounds = (580000.0, 1480000.0, 730000.0, 1630000.0)
    res = mgr.compute_network_coverage_grid(
        grid_bounds=bounds,
        grid_resolution_m=10000.0,
        target_altitude_amsl=3000.0,
    )

    tif_out = export_coverage_geotiff(res, tmp_path / "coverage.tif")
    assert tif_out.exists()
    with rasterio.open(tif_out) as src:
        assert src.count == 3

    geojson_out = export_coverage_geojson(res, mgr.radars, tmp_path / "coverage.geojson")
    assert geojson_out.exists()
    gj_data = json.loads(geojson_out.read_text(encoding="utf-8"))
    assert gj_data["type"] == "FeatureCollection"
    assert len(gj_data["features"]) >= 22

    folium_out = generate_folium_c2_map(mgr.radars, res, tmp_path / "c2_map.html")
    assert folium_out.exists()
    assert "RAD-FX-01" in folium_out.read_text(encoding="utf-8")

    plotly_out = tmp_path / "c2_dashboard.html"
    fig = generate_plotly_c2_dashboard(mgr.radars, res, plotly_out)
    assert plotly_out.exists()
    assert len(fig.data) >= 5
    db.close()


def test_cli_and_fastapi_endpoints(tmp_path: Path, sample_radar_dict: dict, capsys):
    root = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "cli.db"
    args = ["--db", str(db_path)]

    assert cli_main([*args, "init"]) == 0
    capsys.readouterr()

    assert cli_main([*args, "import", str(root / "examples" / "fleet_11_radars.json")]) == 0
    imp_out = json.loads(capsys.readouterr().out)
    assert imp_out["count"] == 11

    assert cli_main([*args, "simulate", "--resolution", "15000"]) == 0
    sim_out = json.loads(capsys.readouterr().out)
    assert sim_out["active_radars"] == 11
    assert sim_out["max_overlap"] >= 6

    # FastAPI endpoints test
    app = create_app(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200

    r_post = client.post("/radars", json=sample_radar_dict)
    assert r_post.status_code == 200
    post_payload = r_post.json()
    assert post_payload["status"] == "SAVED"
    assert "instant_precheck" in post_payload

    r_list = client.get("/radars?active_only=true")
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1

    r_sim = client.post(
        "/simulate",
        json={
            "grid_bounds": [580000.0, 1480000.0, 730000.0, 1630000.0],
            "grid_resolution_m": 15000.0,
            "target_altitude_amsl": 3000.0,
            "target_rcs_m2": 1.0,
        },
    )
    assert r_sim.status_code == 200
    assert r_sim.json()["active_radars"] == 1

    app.state.db.close()

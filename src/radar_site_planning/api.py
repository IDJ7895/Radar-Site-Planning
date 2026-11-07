"""FastAPI REST Service for Radar Database CRUD, Stage-1 & Stage-2 Simulation (GH-13)."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .multi_radar_suite import MultiRadarNetworkManager
from .radar_db import RadarDatabaseManager


class SimulationRequest(BaseModel):
    """Payload for triggering Stage-2 On-Demand Batch Network Simulation."""

    grid_bounds: tuple[float, float, float, float] | None = None
    grid_resolution_m: float = Field(default=2000.0, gt=0)
    target_altitude_amsl: float = Field(default=3000.0, ge=0)
    target_rcs_m2: float = Field(default=1.0, gt=0)


class GapFillerScreeningRequest(BaseModel):
    """Payload for screening candidate mobile gap-filler sites."""

    candidate_coords: list[tuple[float, float]]
    grid_bounds: tuple[float, float, float, float]
    grid_resolution_m: float = Field(default=2000.0, gt=0)
    target_altitude_amsl: float = Field(default=500.0, ge=0)
    target_rcs_m2: float = Field(default=0.5, gt=0)


def create_app(db_url: str = "sqlite:///radar_catalog.db") -> FastAPI:
    """Creates and configures the FastAPI application."""
    app = FastAPI(
        title="Integrated Multi-Radar Planning Suite API",
        version="1.0.0",
        description="Stage-1 Instant Pre-Check & Stage-2 Multi-Radar Network Simulation API",
    )
    app.state.db = RadarDatabaseManager(db_url)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/radars")
    def list_radars(active_only: bool = False) -> list[dict[str, Any]]:
        records = app.state.db.list_radars(active_only=active_only)
        return [r.model_dump(mode="json") for r in records]

    @app.get("/radars/{site_id}")
    def get_radar(site_id: str) -> dict[str, Any]:
        try:
            return app.state.db.get_radar(site_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Site not found: {site_id}") from exc

    @app.post("/radars")
    def add_or_update_radar(
        radar_data: dict[str, Any],
        preview_rcs_m2: float = 1.0,
        preview_alt_m: float = 3000.0,
    ) -> dict[str, Any]:
        try:
            res = app.state.db.add_or_update_radar(
                radar_data,
                preview_rcs_m2=preview_rcs_m2,
                preview_alt_m=preview_alt_m,
            )
            return dict(res)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/radars/{site_id}")
    def patch_radar(site_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        try:
            updated = app.state.db.patch_radar(site_id, changes)
            precheck = app.state.db._run_stage1_instant_precheck(updated, 1.0, 3000.0)
            return {
                "status": "UPDATED",
                "site_id": updated.site_id,
                "record": updated.model_dump(mode="json"),
                "instant_precheck": precheck,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Site not found: {site_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/radars/{site_id}")
    def delete_radar(site_id: str) -> dict[str, str]:
        try:
            app.state.db.delete_radar(site_id)
            return {"status": "DELETED", "site_id": site_id}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Site not found: {site_id}") from exc

    @app.post("/simulate")
    def simulate_network(req: SimulationRequest) -> dict[str, Any]:
        try:
            results = app.state.db.simulate_active_network_from_db(
                grid_bounds=req.grid_bounds,
                grid_resolution_m=req.grid_resolution_m,
                target_altitude_amsl=req.target_altitude_amsl,
                target_rcs_m2=req.target_rcs_m2,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        overlap = results["overlap_count"]
        joint_pd = results["joint_pd"]
        max_snr = results["max_snr_db"]
        active_count = len(app.state.db.list_active_radars())

        return {
            "status": "COMPLETED",
            "active_radars": active_count,
            "grid_shape": list(overlap.shape),
            "max_overlap": int(np.max(overlap)),
            "k_ge_1_coverage_pct": round(float(np.mean(overlap >= 1) * 100.0), 2),
            "k_ge_2_redundant_pct": round(float(np.mean(overlap >= 2) * 100.0), 2),
            "high_confidence_pd_ge_90_pct": round(float(np.mean(joint_pd >= 0.90) * 100.0), 2),
            "peak_snr_db": round(float(np.max(max_snr)), 2),
        }

    @app.post("/screen-gap-fillers")
    def screen_gap_fillers(req: GapFillerScreeningRequest) -> dict[str, Any]:
        mgr = MultiRadarNetworkManager()
        count = mgr.load_active_fleet_from_db(app.state.db)
        if count == 0:
            raise HTTPException(status_code=400, detail="No active radars in database")
        rankings = mgr.screen_mobile_gap_filler_sites(
            candidate_coords=req.candidate_coords,
            grid_bounds=req.grid_bounds,
            grid_resolution_m=req.grid_resolution_m,
            target_altitude_amsl=req.target_altitude_amsl,
            target_rcs_m2=req.target_rcs_m2,
        )
        return {"status": "COMPLETED", "rankings": rankings}

    return app


app = create_app()

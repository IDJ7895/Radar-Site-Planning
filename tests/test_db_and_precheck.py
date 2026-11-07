"""Tests for Milestone 1: SQLite ORM, Pydantic & Stage-1 Pre-Check (GH-01, GH-02)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from radar_site_planning import RadarDatabaseManager, RadarRecord


def test_stage1_instant_precheck_on_save(db_manager: RadarDatabaseManager, sample_radar_dict: dict):
    res = db_manager.add_or_update_radar(
        sample_radar_dict, preview_rcs_m2=1.0, preview_alt_m=3000.0
    )
    assert res["status"] == "SAVED"
    assert res["site_id"] == "RAD-FX-01"
    assert res["brand_model"] == "IAI Elta ELM-2084 MMR"

    chk = res["instant_precheck"]
    assert chk["effective_rmax_km"] <= chk["instrumented_limit_km"]
    assert chk["theoretical_rmax_km"] > 100.0
    assert chk["radar_horizon_km_at_target_alt"] > 200.0
    assert chk["aesa_scan_loss_db"] >= 0.0
    # Verify Stage-1 executes well below the 5 ms requirement
    assert chk["execution_time_ms"] < 5.0


def test_crud_and_patch_operations(db_manager: RadarDatabaseManager, sample_radar_dict: dict):
    saved = db_manager.add_or_update_radar(sample_radar_dict)
    loaded = db_manager.get_radar("RAD-FX-01")
    assert loaded == saved
    assert loaded.site_name == "Fixed Sector Site #1"

    patched = db_manager.patch_radar("RAD-FX-01", {"mast_height_agl": 35.0, "is_active": False})
    assert patched.mast_height_agl == 35.0
    assert patched.is_active is False
    assert db_manager.list_active_radars() == []

    db_manager.delete_radar("RAD-FX-01")
    with pytest.raises(KeyError):
        db_manager.get_radar("RAD-FX-01")


def test_catalog_file_import_json_and_yaml(db_manager: RadarDatabaseManager):
    root = Path(__file__).resolve().parent.parent
    json_records = db_manager.load_catalog_file(root / "examples" / "fleet_11_radars.json")
    assert len(json_records) == 11
    assert len(db_manager.list_active_radars()) == 11

    yaml_records = db_manager.load_catalog_file(root / "examples" / "fleet_11_radars.yaml")
    assert len(yaml_records) == 2


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("site_id", "   "),
        ("brand", ""),
        ("frequency_ghz", 0.0),
        ("peak_power_kw", -5.0),
        ("instrumented_max_range_km", -10.0),
        ("mechanical_tilt_deg", 95.0),
        ("electronic_tilt_deg", -95.0),
        ("field_of_regard_az_deg", 0.0),
        ("mobility", "INVALID_MOBILITY"),
        ("tech", "INVALID_TECH"),
        ("latitude", 95.0),
        ("longitude", -190.0),
    ],
)
def test_pydantic_validation_rejects_invalid_inputs(
    sample_radar_dict: dict, field: str, bad_value: object
):
    payload = dict(sample_radar_dict)
    if field in ("latitude", "longitude"):
        payload.pop("lat", None)
        payload.pop("lon", None)
        payload["latitude"] = 13.75
        payload["longitude"] = 100.5
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        RadarRecord.model_validate(payload)

from __future__ import annotations

import pytest

from radar_site_planning import RadarDatabaseManager


@pytest.fixture
def sample_radar_dict() -> dict:
    return {
        "site_id": "RAD-FX-01",
        "site_name": "Fixed Sector Site #1",
        "brand": "IAI Elta",
        "model": "ELM-2084 MMR",
        "radar_category": "Air_Defense",
        "mobility": "FIXED",
        "tech": "FULL_AESA",
        "lat": 1512000.0,
        "lon": 625000.0,
        "ground_elevation_amsl": 120.0,
        "mast_height_agl": 30.0,
        "instrumented_max_range_km": 450.0,
        "frequency_ghz": 3.0,
        "peak_power_kw": 100.0,
        "pulse_width_us": 15.0,
        "antenna_gain_dbi": 40.0,
        "electronic_tilt_deg": 2.0,
        "mechanical_tilt_deg": 0.0,
        "field_of_regard_az_deg": 360.0,
        "is_active": True,
    }


@pytest.fixture
def db_manager(tmp_path):
    with RadarDatabaseManager(tmp_path / "test_radar_catalog.db") as mgr:
        yield mgr

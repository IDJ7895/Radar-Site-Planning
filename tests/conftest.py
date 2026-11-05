import pytest

from radar_site_planning import RadarDatabaseManager


@pytest.fixture
def record():
    return {
        "site_id": "research-01",
        "site_name": "Synthetic laboratory site",
        "brand": "Example Instruments",
        "model": "Research Demo",
        "latitude": 0.0,
        "longitude": 0.0,
        "instrumented_max_range_km": 10.0,
        "peak_power_kw": 0.1,
        "frequency_ghz": 9.4,
        "antenna_gain_dbi": 20.0,
    }


@pytest.fixture
def catalog(tmp_path):
    with RadarDatabaseManager(tmp_path / "catalog.db") as manager:
        yield manager

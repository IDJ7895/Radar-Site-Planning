import pytest
from pydantic import ValidationError

from radar_site_planning import RadarRecord


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("site_id", "  "),
        ("brand", ""),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("latitude", float("nan")),
        ("frequency_ghz", float("inf")),
        ("frequency_ghz", 0),
        ("peak_power_kw", -1),
        ("mast_height_agl", -1),
        ("instrumented_max_range_km", 0),
        ("az_beamwidth_deg", 0),
        ("el_beamwidth_deg", 181),
        ("mechanical_tilt_deg", 91),
        ("electronic_tilt_deg", -91),
        ("azimuth_boresight_deg", 360),
        ("field_of_regard_az_deg", 0),
        ("is_active", "false"),
        ("is_active", 1),
        ("noise_figure_db", -1),
        ("system_loss_db", -1),
        ("mobility_type", "typo"),
        ("antenna_tech", "typo"),
        ("lat", 20),
    ],
)
def test_invalid_records(record, field, value):
    with pytest.raises(ValidationError):
        RadarRecord.model_validate({**record, field: value})


def test_negative_elevation_and_gain_are_valid(record):
    validated = RadarRecord.model_validate(
        {**record, "ground_elevation_amsl": -50, "antenna_gain_dbi": -2}
    )
    assert validated.ground_elevation_amsl == -50


def test_unvalidated_model_cannot_bypass_persistence_validation(catalog, record):
    unsafe = RadarRecord.model_construct(**{**record, "latitude": 200})
    with pytest.raises(ValidationError):
        catalog.add_or_update_radar(unsafe)
    assert catalog.list_radars() == []

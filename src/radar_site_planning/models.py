"""Public catalog schema. Coordinates are WGS84; heights are explicitly named."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class Mobility(StrEnum):
    FIXED = "FIXED"
    MOBILE = "MOBILE"


class AntennaTechnology(StrEnum):
    LEGACY_MECHANICAL = "LEGACY_MECHANICAL"
    PESA = "PESA"
    FULL_AESA = "FULL_AESA"


class RadarRecord(BaseModel):
    """Hardware specifications and one deployment site, identified by site_id.

    This is inventory data, without inferred detection or coverage performance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    site_id: Identifier
    site_name: Name
    brand: Name
    model: Name
    radar_category: Name = "RESEARCH"
    mobility_type: Mobility = Mobility.FIXED
    antenna_tech: AntennaTechnology = AntennaTechnology.LEGACY_MECHANICAL
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    ground_elevation_amsl: Finite = 0.0
    mast_height_agl: Nonnegative = 10.0
    instrumented_max_range_km: Positive
    peak_power_kw: Positive
    frequency_ghz: Positive
    pulse_width_us: Positive = 10.0
    antenna_gain_dbi: Finite
    az_beamwidth_deg: Annotated[float, Field(gt=0, le=360)] = 1.4
    el_beamwidth_deg: Annotated[float, Field(gt=0, le=180)] = 2.0
    mechanical_tilt_deg: Annotated[float, Field(ge=-90, le=90)] = 0.0
    electronic_tilt_deg: Annotated[float, Field(ge=-90, le=90)] = 0.0
    azimuth_boresight_deg: Annotated[float, Field(ge=0, lt=360)] = 0.0
    field_of_regard_az_deg: Annotated[float, Field(gt=0, le=360)] = 360.0
    noise_figure_db: Nonnegative = 3.5
    system_loss_db: Nonnegative = 6.0
    min_snr_db: Finite = 13.0
    is_active: StrictBool = True


class StoredRadar(RadarRecord):
    created_at: datetime
    updated_at: datetime

"""Pydantic v2 data contracts and enums for the Integrated Multi-Radar Planning Suite."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class MobilityType(StrEnum):
    """Supported radar platform mobility classifications."""

    FIXED = "FIXED"
    MOBILE_TACTICAL = "MOBILE_TACTICAL"
    MOBILE_MANPADS_CUAS = "MOBILE_MANPADS_CUAS"
    MOBILE = "MOBILE"


# Alias for backward compatibility
Mobility = MobilityType


class AntennaTechnology(StrEnum):
    """Supported radar antenna steering architectures."""

    LEGACY_MECHANICAL = "LEGACY_MECHANICAL"
    PESA = "PESA"
    FULL_AESA = "FULL_AESA"


class Stage1PrecheckResult(BaseModel):
    """Analytical Stage-1 (<5 ms) physics pre-check summary returned on DB save."""

    model_config = ConfigDict(extra="allow", frozen=True)

    theoretical_rmax_km: float
    free_space_rmax_km: float
    instrumented_limit_km: float
    effective_rmax_km: float
    radar_horizon_km_at_target_alt: float
    earth_4_3_horizon_km: float
    aesa_scan_loss_db: float
    effective_boresight_gain_dbi: float
    execution_time_ms: float


class RadarRecord(BaseModel):
    """Validated hardware specification and deployment site configuration.

    Supports both geographic WGS84 degrees (latitude/longitude) and projected
    metric UTM coordinates (lat/lon Northing/Easting in meters).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    site_id: Identifier
    site_name: Name
    brand: Name
    model: Name
    radar_category: Name = "Early_Warning"
    mobility: MobilityType = MobilityType.FIXED
    tech: AntennaTechnology = AntennaTechnology.LEGACY_MECHANICAL

    # Coordinates: WGS84 degrees or metric UTM Northing (lat) / Easting (lon)
    lat: Finite
    lon: Finite
    ground_elevation_amsl: Finite = 0.0
    mast_height_agl: Nonnegative = 10.0

    # Transmitter / Receiver & Range Specifications
    instrumented_max_range_km: Positive
    peak_power_kw: Positive
    frequency_ghz: Positive
    pulse_width_us: Positive = 10.0
    noise_figure_db: Nonnegative = 3.5
    system_loss_db: Nonnegative = 6.0
    min_snr_db: Finite = 13.0

    # Antenna Pattern & Tilt Configuration
    antenna_gain_dbi: Finite
    az_beamwidth_deg: Annotated[float, Field(gt=0, le=360)] = 1.4
    el_beamwidth_deg: Annotated[float, Field(gt=0, le=180)] = 2.0
    mechanical_tilt_deg: Annotated[float, Field(ge=-90, le=90)] = 0.0
    electronic_tilt_deg: Annotated[float, Field(ge=-90, le=90)] = 0.0
    azimuth_boresight_deg: Annotated[float, Field(ge=0, lt=360)] = 0.0
    field_of_regard_az_deg: Annotated[float, Field(gt=0, le=360)] = 360.0

    is_active: StrictBool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases_and_validate_coords(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)

        # Support radar_id -> site_id alias
        if "radar_id" in normalized and "site_id" not in normalized:
            normalized["site_id"] = normalized.pop("radar_id")

        # Support mobility_type -> mobility alias
        if "mobility_type" in normalized and "mobility" not in normalized:
            normalized["mobility"] = normalized.pop("mobility_type")
        elif "mobility_type" in normalized and "mobility" in normalized:
            normalized.pop("mobility_type")

        # Support antenna_tech -> tech alias
        if "antenna_tech" in normalized and "tech" not in normalized:
            normalized["tech"] = normalized.pop("antenna_tech")
        elif "antenna_tech" in normalized and "tech" in normalized:
            normalized.pop("antenna_tech")

        # Support latitude/longitude -> lat/lon with strict WGS84 bounds when explicit
        has_explicit_latlon = "latitude" in normalized or "longitude" in normalized
        if has_explicit_latlon and ("lat" in normalized or "lon" in normalized):
            raise ValueError("Specify either (latitude, longitude) or (lat, lon), not both")

        if "latitude" in normalized:
            lat_val = normalized.pop("latitude")
            if isinstance(lat_val, (int, float)) and not (-90.0 <= float(lat_val) <= 90.0):
                raise ValueError("latitude must be between -90 and 90 degrees")
            normalized["lat"] = lat_val

        if "longitude" in normalized:
            lon_val = normalized.pop("longitude")
            if isinstance(lon_val, (int, float)) and not (-180.0 <= float(lon_val) <= 180.0):
                raise ValueError("longitude must be between -180 and 180 degrees")
            normalized["lon"] = lon_val

        return normalized

    @property
    def radar_id(self) -> str:
        return self.site_id

    @property
    def latitude(self) -> float:
        return self.lat

    @property
    def longitude(self) -> float:
        return self.lon

    @property
    def mobility_type(self) -> MobilityType:
        return self.mobility

    @property
    def antenna_tech(self) -> AntennaTechnology:
        return self.tech


class StoredRadar(RadarRecord):
    """Persisted radar record with database primary key and UTC timestamps."""

    id: int | None = None
    created_at: datetime
    updated_at: datetime

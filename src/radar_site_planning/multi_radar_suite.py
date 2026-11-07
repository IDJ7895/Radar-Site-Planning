"""Multi-Radar Network Planning Suite, RF Physics & Coverage Fusion (GH-05 to GH-10)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from scipy.special import erfc

from .terrain_manager import TerrainManager


class MobilityType(Enum):
    """Platform mobility classification."""

    FIXED = "FIXED"
    MOBILE_TACTICAL = "MOBILE_TACTICAL"
    MOBILE_MANPADS_CUAS = "MOBILE_MANPADS_CUAS"
    MOBILE = "MOBILE"


class AntennaTechnology(Enum):
    """Antenna steering technology."""

    LEGACY_MECHANICAL = "LEGACY_MECHANICAL"
    PESA = "PESA"
    FULL_AESA = "FULL_AESA"


def compute_3d_rotation_matrix(azimuth_deg: float, mechanical_tilt_deg: float) -> np.ndarray:
    """Computes the 3D coordinate rotation matrix for a mechanically gimbaled radar aperture.

    Rotates from the local East-North-Up (ENU) frame by azimuth (clockwise from North)
    and elevation gimbal tilt up (+) / down (-).
    """
    az_rad = np.radians(azimuth_deg)
    el_rad = np.radians(mechanical_tilt_deg)

    # Rotation about Up (Z) axis for azimuth clockwise from North
    r_az = np.array(
        [
            [np.cos(az_rad), -np.sin(az_rad), 0.0],
            [np.sin(az_rad), np.cos(az_rad), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    # Rotation about local X axis for elevation tilt up/down
    r_el = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, np.cos(el_rad), -np.sin(el_rad)],
            [0.0, np.sin(el_rad), np.cos(el_rad)],
        ],
        dtype=np.float64,
    )
    return r_az @ r_el


def compute_knife_edge_diffraction_loss_db(
    h_obstacle_clearance_m: float | np.ndarray,
    d1_radar_to_peak_m: float | np.ndarray,
    d2_peak_to_target_m: float | np.ndarray,
    frequency_ghz: float,
) -> float | np.ndarray:
    """Computes terrain diffraction loss (dB) using ITU-R P.526 knife-edge approximation.

    Negative clearance means the obstacle obstructs the direct line of sight.
    Supports both scalar floats and vectorized NumPy arrays.
    """
    c = 3e8
    wavelength = c / (frequency_ghz * 1e9)
    h = -np.asarray(h_obstacle_clearance_m, dtype=np.float64)  # Positive when penetrating LoS
    d1 = np.maximum(np.asarray(d1_radar_to_peak_m, dtype=np.float64), 1.0)
    d2 = np.maximum(np.asarray(d2_peak_to_target_m, dtype=np.float64), 1.0)

    # Fresnel-Kirchhoff diffraction parameter v
    v = h * np.sqrt((2.0 / wavelength) * (1.0 / d1 + 1.0 / d2))

    if np.ndim(h_obstacle_clearance_m) == 0:
        v_scalar = float(v)
        if v_scalar <= -0.78:
            return 0.0
        loss_db = 6.9 + 20.0 * np.log10(np.sqrt((v_scalar - 0.1) ** 2 + 1.0) + v_scalar - 0.1)
        return float(max(loss_db, 0.0))

    v_clamped = np.maximum(v, -0.78)
    loss_arr = 6.9 + 20.0 * np.log10(np.sqrt((v_clamped - 0.1) ** 2 + 1.0) + v_clamped - 0.1)
    loss_arr = np.where(v <= -0.78, 0.0, np.maximum(loss_arr, 0.0))
    return loss_arr


def compute_blake_chart_atmospheric_loss_db(
    range_m: float | np.ndarray,
    frequency_ghz: float,
    elevation_deg: float | np.ndarray = 2.0,
) -> float | np.ndarray:
    """Blake radar range equation two-way atmospheric absorption loss (dB)
    as a function of frequency, slant range, and elevation angle.
    """
    r_km = np.asarray(range_m, dtype=np.float64) / 1000.0
    el_clamped = np.maximum(np.asarray(elevation_deg, dtype=np.float64), 0.5)
    # Two-way specific attenuation coefficient (dB/km) at sea level scaled by frequency
    gamma_0 = 0.007 + 0.0015 * (frequency_ghz**1.25)
    # Effective atmospheric path length diminishes with higher elevation angle
    effective_path_km = np.minimum(r_km, 25.0 / np.sin(np.radians(np.minimum(el_clamped, 90.0))))
    loss_db = 2.0 * gamma_0 * effective_path_km
    if np.ndim(range_m) == 0:
        return float(loss_db)
    return loss_db


def compute_marcum_q_pd(
    snr_linear: float | np.ndarray,
    pfa: float = 1e-6,
) -> float | np.ndarray:
    """Computes non-fluctuating (Swerling 0 / Marcum Q) single-pulse Probability of Detection."""
    snr = np.maximum(np.asarray(snr_linear, dtype=np.float64), 0.0)
    # North's approximation for Marcum Q-function: Pd ~ 0.5 * erfc(sqrt(-ln(Pfa)) - sqrt(SNR + 0.5))
    beta = np.sqrt(-np.log(max(pfa, 1e-15)))
    arg = beta - np.sqrt(snr + 0.5)
    pd = 0.5 * erfc(arg / np.sqrt(2.0))
    if np.ndim(snr_linear) == 0:
        return float(np.clip(pd, 0.0, 1.0))
    return np.clip(pd, 0.0, 1.0)


@dataclass
class RadarPlatform:
    """Specification and deployment configuration for an individual radar platform."""

    site_id: str
    name: str
    brand: str
    model: str
    radar_category: str
    mobility: MobilityType
    tech: AntennaTechnology

    # Deployment Coordinates (Metric UTM or Geographical)
    lat: float
    lon: float
    mast_height_agl: float  # Antenna height above ground level (m)
    ground_elevation_amsl: float = 0.0  # Loaded from DTM or DB

    # RF & Radar Link Parameters
    instrumented_max_range_km: float = 250.0  # Manufacturer rated max range (km)
    frequency_ghz: float = 3.0  # Operating frequency (S-band, X-band, etc.)
    peak_power_kw: float = 50.0  # Peak transmitted power
    pulse_width_us: float = 10.0  # Pulse width in microseconds
    noise_figure_db: float = 3.5  # Receiver noise figure
    system_loss_db: float = 6.0  # Plumbing and internal losses
    min_snr_db: float = 13.0  # Minimum SNR for Pd=0.9, Pfa=1e-6

    # Antenna Pattern & Steering Parameters
    antenna_gain_dbi: float = 38.0
    az_beamwidth_deg: float = 1.4
    el_beamwidth_deg: float = 2.0
    mechanical_tilt_deg: float = 0.0  # Mechanical gimbal elevation tilt
    electronic_tilt_deg: float = 0.0  # Electronic phase steering (AESA/PESA)
    azimuth_boresight_deg: float = 0.0  # 0 = North, for sector scan or mobile facing
    field_of_regard_az_deg: float = 360.0  # 360 for rotating, 120 for fixed AESA panel

    # Operational Status
    is_active: bool = True

    @property
    def total_antenna_height_amsl(self) -> float:
        return self.ground_elevation_amsl + self.mast_height_agl

    @property
    def effective_tilt_deg(self) -> float:
        """Net elevation pointing angle relative to local horizon."""
        if self.tech in (AntennaTechnology.FULL_AESA, AntennaTechnology.PESA):
            return self.mechanical_tilt_deg + self.electronic_tilt_deg
        return self.mechanical_tilt_deg

    def get_gimbal_rotation_matrix(self) -> np.ndarray:
        """Returns the 3D mechanical rotation matrix for physical aperture orientation."""
        return compute_3d_rotation_matrix(self.azimuth_boresight_deg, self.mechanical_tilt_deg)

    def compute_aperture_gain(self, target_el_deg: float | np.ndarray) -> float | np.ndarray:
        """Computes directive gain towards target with AESA scan loss & beam broadening."""
        g_peak_linear = 10.0 ** (self.antenna_gain_dbi / 10.0)
        off_boresight_el = np.asarray(target_el_deg, dtype=np.float64) - self.effective_tilt_deg

        if self.tech == AntennaTechnology.FULL_AESA:
            theta_scan_rad = np.radians(abs(self.electronic_tilt_deg))
            # Scan loss factor cos^1.3(theta)
            scan_loss = float(np.cos(theta_scan_rad) ** 1.3)
            # Elevation beam broadening: theta_3dB / cos(theta)
            broadened_el_bw = self.el_beamwidth_deg / max(float(np.cos(theta_scan_rad)), 0.1)
            # Gaussian pattern approximation
            pattern_falloff = np.exp(-2.776 * (off_boresight_el / broadened_el_bw) ** 2)
            effective_gain = g_peak_linear * scan_loss * pattern_falloff
        elif self.tech == AntennaTechnology.PESA:
            theta_scan_rad = np.radians(abs(self.electronic_tilt_deg))
            scan_loss = float(np.cos(theta_scan_rad) ** 1.5)
            broadened_el_bw = self.el_beamwidth_deg / max(float(np.cos(theta_scan_rad)), 0.1)
            pattern_falloff = np.exp(-2.776 * (off_boresight_el / broadened_el_bw) ** 2)
            effective_gain = g_peak_linear * scan_loss * pattern_falloff
        else:
            # Legacy Mechanical: Full dish tilts, no scan loss, symmetric Gaussian mainlobe
            pattern_falloff = np.exp(-2.776 * (off_boresight_el / self.el_beamwidth_deg) ** 2)
            effective_gain = g_peak_linear * pattern_falloff

        if np.ndim(target_el_deg) == 0:
            return float(max(float(effective_gain), 1e-4))
        return np.maximum(effective_gain, 1e-4)

    def compute_clutter_penalty_db(
        self, target_el_deg: float | np.ndarray = 0.0
    ) -> float | np.ndarray:
        """Models low-altitude ground clutter SNR penalty when antenna is tilted downward.

        Legacy mechanical radars illuminating ground terrain suffer heavy sidelobe/mainlobe
        clutter backscatter when tilted down, whereas Full AESA applies adaptive digital nulling.
        """
        tilt = self.effective_tilt_deg
        if tilt >= 0.0:
            return (
                0.0
                if np.ndim(target_el_deg) == 0
                else np.zeros_like(target_el_deg, dtype=np.float64)
            )

        down_tilt_mag = abs(tilt)
        if self.tech == AntennaTechnology.FULL_AESA:
            # Digital nulling suppresses terrain clutter notch
            penalty = min(0.4 * down_tilt_mag, 2.0)
        else:
            # Mechanical dish tilted down illuminates ground strongly
            penalty = min(2.5 * down_tilt_mag, 12.0)

        if np.ndim(target_el_deg) == 0:
            return float(penalty)
        return np.full_like(np.asarray(target_el_deg, dtype=np.float64), penalty)

    def calculate_free_space_rmax(self, target_rcs_m2: float) -> float:
        """Calculates free-space maximum detection range (meters) via radar range equation,
        bounded by the radar's instrumented maximum range.
        """
        c = 3e8
        wavelength = c / (self.frequency_ghz * 1e9)
        pt = self.peak_power_kw * 1e3
        g_linear = 10.0 ** (self.antenna_gain_dbi / 10.0)
        kb = 1.380649e-23
        t0 = 290.0
        b_rx = 1.0 / (self.pulse_width_us * 1e-6)
        noise_power = kb * t0 * b_rx * (10.0 ** (self.noise_figure_db / 10.0))
        snr_threshold = 10.0 ** (self.min_snr_db / 10.0)
        sys_loss = 10.0 ** (self.system_loss_db / 10.0)

        # Apply scan loss if AESA is electronically steered off-boresight
        if self.tech == AntennaTechnology.FULL_AESA and abs(self.electronic_tilt_deg) > 0.0:
            scan_loss = float(np.cos(np.radians(self.electronic_tilt_deg)) ** 1.3)
            g_linear *= scan_loss

        numerator = pt * (g_linear**2) * (wavelength**2) * target_rcs_m2
        denominator = ((4.0 * np.pi) ** 3) * noise_power * snr_threshold * sys_loss
        r_max_physics_m = float((numerator / denominator) ** 0.25)

        return min(r_max_physics_m, self.instrumented_max_range_km * 1000.0)


class MultiRadarNetworkManager:
    """Simultaneously coordinates and simulates 11 or more fixed and mobile radar sites.
    Supports loading directly from the SQLite RadarDatabaseManager or YAML/JSON catalogs.
    """

    def __init__(self, terrain_manager: TerrainManager | None = None) -> None:
        self.radars: dict[str, RadarPlatform] = {}
        self.terrain_manager = terrain_manager

    def add_radar(self, radar: RadarPlatform) -> None:
        self.radars[radar.site_id] = radar

    def load_active_fleet_from_db(self, db_manager: Any) -> int:
        """Loads all active radar records from SQLite into the simulation manager."""
        self.radars.clear()
        records = db_manager.list_active_radars()
        for r in records:
            mobility_val = getattr(r, "mobility", getattr(r, "mobility_type", "FIXED"))
            tech_val = getattr(r, "tech", getattr(r, "antenna_tech", "LEGACY_MECHANICAL"))
            ground_el = float(r.ground_elevation_amsl)
            if self.terrain_manager is not None and ground_el == 0.0:
                ground_el = float(self.terrain_manager.sample_elevation(float(r.lon), float(r.lat)))

            platform = RadarPlatform(
                site_id=r.site_id,
                name=r.site_name,
                brand=r.brand,
                model=r.model,
                radar_category=r.radar_category,
                mobility=MobilityType(str(mobility_val)),
                tech=AntennaTechnology(str(tech_val)),
                lat=float(r.lat),
                lon=float(r.lon),
                mast_height_agl=float(r.mast_height_agl),
                ground_elevation_amsl=ground_el,
                instrumented_max_range_km=float(r.instrumented_max_range_km),
                frequency_ghz=float(r.frequency_ghz),
                peak_power_kw=float(r.peak_power_kw),
                pulse_width_us=float(r.pulse_width_us),
                noise_figure_db=float(r.noise_figure_db),
                system_loss_db=float(r.system_loss_db),
                min_snr_db=float(r.min_snr_db),
                antenna_gain_dbi=float(r.antenna_gain_dbi),
                az_beamwidth_deg=float(r.az_beamwidth_deg),
                el_beamwidth_deg=float(r.el_beamwidth_deg),
                mechanical_tilt_deg=float(r.mechanical_tilt_deg),
                electronic_tilt_deg=float(r.electronic_tilt_deg),
                azimuth_boresight_deg=float(r.azimuth_boresight_deg),
                field_of_regard_az_deg=float(r.field_of_regard_az_deg),
                is_active=bool(r.is_active),
            )
            self.add_radar(platform)
        return len(self.radars)

    def _evaluate_single_radar_on_grid(
        self,
        radar: RadarPlatform,
        x_coords: np.ndarray,
        y_coords: np.ndarray,
        target_altitude_amsl: float,
        target_rcs_m2: float,
        include_terrain_diffraction: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Evaluates coverage, single-station Pd, SNR (dB), and power density for one radar."""
        r_max_free = radar.calculate_free_space_rmax(target_rcs_m2)

        # Vectorized range and bearing calculation
        dx = x_coords[np.newaxis, :] - radar.lon
        dy = y_coords[:, np.newaxis] - radar.lat
        dist_matrix = np.sqrt(dx**2 + dy**2)
        az_matrix = np.degrees(np.arctan2(dx, dy)) % 360.0

        # Elevation angle to target point
        delta_h = target_altitude_amsl - radar.total_antenna_height_amsl
        _el_matrix = np.degrees(np.arctan2(delta_h, np.maximum(dist_matrix, 1.0)))

        # 1. Free space & instrumented range mask
        in_range = dist_matrix <= r_max_free

        # 2. Field of Regard (Azimuth Sector) Mask
        if radar.field_of_regard_az_deg < 360.0:
            half_for = radar.field_of_regard_az_deg / 2.0
            az_diff = np.abs((az_matrix - radar.azimuth_boresight_deg + 180.0) % 360.0 - 180.0)
            in_sector = az_diff <= half_for
        else:
            in_sector = np.ones_like(dist_matrix, dtype=bool)

        # 3. 4/3 Earth Curvature Radar Horizon Mask (ITU-R P.834)
        re_eff = 6371000.0 * (4.0 / 3.0)
        h_radar = max(radar.total_antenna_height_amsl, 1.0)
        h_tgt = max(target_altitude_amsl, 1.0)
        radar_horizon = np.sqrt(2.0 * re_eff * h_radar) + np.sqrt(2.0 * re_eff * h_tgt)
        los_horizon = dist_matrix <= radar_horizon

        # 4. Optional Terrain Masking & ITU-R P.526 Knife-Edge Diffraction
        diffraction_loss_db = np.zeros_like(dist_matrix, dtype=np.float64)
        terrain_los_mask = np.ones_like(dist_matrix, dtype=bool)
        if self.terrain_manager is not None and include_terrain_diffraction:
            xx, yy = np.meshgrid(x_coords, y_coords)
            los_info = self.terrain_manager.extract_los_profile(
                radar_x=radar.lon,
                radar_y=radar.lat,
                radar_alt_amsl=radar.total_antenna_height_amsl,
                target_x=xx,
                target_y=yy,
                target_alt_amsl=target_altitude_amsl,
                num_samples=16,
            )
            diffraction_loss_db = np.asarray(
                compute_knife_edge_diffraction_loss_db(
                    h_obstacle_clearance_m=los_info["clearance_m"],
                    d1_radar_to_peak_m=los_info["d1_m"],
                    d2_peak_to_target_m=los_info["d2_m"],
                    frequency_ghz=radar.frequency_ghz,
                ),
                dtype=np.float64,
            )
            # Severe terrain blockage (> 25 dB diffraction loss) masks detection
            terrain_los_mask = diffraction_loss_db <= 25.0

        # Compute SNR per pixel considering 2-way range attenuation and any diffraction loss
        with np.errstate(divide="ignore"):
            snr_linear_free = ((r_max_free / np.maximum(dist_matrix, 1.0)) ** 4) * (
                10.0 ** (radar.min_snr_db / 10.0)
            )
            diffraction_factor = 10.0 ** (-diffraction_loss_db / 10.0)
            snr_linear = snr_linear_free * diffraction_factor
            snr_db = (10.0 * np.log10(np.maximum(snr_linear, 1e-6))).astype(np.float32)

        snr_thresh = 10.0 ** (radar.min_snr_db / 10.0)
        above_snr = snr_linear >= snr_thresh if self.terrain_manager is not None else True

        # Combined detection mask
        detected = in_range & in_sector & los_horizon & terrain_los_mask & above_snr

        # Swerling Case 1 single-scan Pd model: Pd = exp(-threshold / (1 + SNR))
        pd_single = np.where(detected, np.exp(-snr_thresh / (1.0 + snr_linear)), 0.0)

        # Signal Power Density (dBm/m^2) at target location: S = Pt * G / (4 * pi * R^2)
        pt_mw = radar.peak_power_kw * 1e6  # kW -> mW
        g_lin = 10.0 ** (radar.antenna_gain_dbi / 10.0)
        flux_mw_m2 = (pt_mw * g_lin) / (4.0 * np.pi * np.maximum(dist_matrix, 1.0) ** 2)
        power_density_dbm_m2 = (10.0 * np.log10(np.maximum(flux_mw_m2, 1e-12))).astype(np.float32)

        return detected, pd_single, snr_db, power_density_dbm_m2

    def compute_network_coverage_grid(
        self,
        grid_bounds: tuple[float, float, float, float],
        grid_resolution_m: float,
        target_altitude_amsl: float,
        target_rcs_m2: float = 1.0,
        use_parallel: bool = True,
        include_terrain_diffraction: bool = True,
    ) -> dict[str, np.ndarray]:
        """Simultaneously computes LoS and radar equation detection across a common metric grid.

        Returns:
            - 'overlap_count': Number of radars detecting target at each pixel (k-coverage)
            - 'joint_pd': Multi-station joint detection probability P_{d,net} = 1 - prod(1 - Pd_i)
            - 'max_snr_db': Strongest SNR across all observing radars
            - 'power_density_dbm_m2': Peak RF power density heatmap (dBm/m^2)
            - 'blind_spot_mask': Boolean grid where k == 0
            - 'single_radar_mask': Boolean grid where k == 1
            - 'redundant_handover_mask': Boolean grid where k >= 2
            - 'x_coords': 1D Easting/Longitude coordinate array
            - 'y_coords': 1D Northing/Latitude coordinate array
        """
        min_x, min_y, max_x, max_y = grid_bounds
        x_coords = np.arange(min_x, max_x, grid_resolution_m)
        y_coords = np.arange(min_y, max_y, grid_resolution_m)
        nx, ny = len(x_coords), len(y_coords)

        overlap_count = np.zeros((ny, nx), dtype=np.int32)
        joint_miss_probability = np.ones((ny, nx), dtype=np.float64)
        max_snr_grid = np.full((ny, nx), -99.0, dtype=np.float32)
        max_power_density_grid = np.full((ny, nx), -120.0, dtype=np.float32)

        active_radars = [r for r in self.radars.values() if r.is_active]
        if not active_radars:
            return {
                "overlap_count": overlap_count,
                "joint_pd": 1.0 - joint_miss_probability,
                "max_snr_db": max_snr_grid,
                "power_density_dbm_m2": max_power_density_grid,
                "blind_spot_mask": overlap_count == 0,
                "single_radar_mask": overlap_count == 1,
                "redundant_handover_mask": overlap_count >= 2,
                "x_coords": x_coords,
                "y_coords": y_coords,
            }

        def _worker(r: RadarPlatform) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            return self._evaluate_single_radar_on_grid(
                r,
                x_coords,
                y_coords,
                target_altitude_amsl,
                target_rcs_m2,
                include_terrain_diffraction=include_terrain_diffraction,
            )

        if use_parallel and len(active_radars) > 1:
            with ThreadPoolExecutor(max_workers=min(len(active_radars), 16)) as pool:
                per_radar_outputs = list(pool.map(_worker, active_radars))
        else:
            per_radar_outputs = [_worker(r) for r in active_radars]

        for detected, pd_single, snr_db, pwr_dens in per_radar_outputs:
            overlap_count += detected.astype(np.int32)
            joint_miss_probability *= 1.0 - pd_single
            max_snr_grid = np.maximum(max_snr_grid, np.where(detected, snr_db, -99.0))
            max_power_density_grid = np.maximum(max_power_density_grid, pwr_dens)

        joint_pd = 1.0 - joint_miss_probability

        return {
            "overlap_count": overlap_count,
            "joint_pd": joint_pd,
            "max_snr_db": max_snr_grid,
            "power_density_dbm_m2": max_power_density_grid,
            "blind_spot_mask": overlap_count == 0,
            "single_radar_mask": overlap_count == 1,
            "redundant_handover_mask": overlap_count >= 2,
            "x_coords": x_coords,
            "y_coords": y_coords,
        }

    def compute_volumetric_coverage(
        self,
        grid_bounds: tuple[float, float, float, float],
        grid_resolution_m: float,
        altitudes_amsl: list[float],
        target_rcs_m2: float = 1.0,
    ) -> dict[str, Any]:
        """Computes 3D volumetric multi-altitude coverage slices across the AOR."""
        slices: dict[float, dict[str, np.ndarray]] = {}
        for alt in altitudes_amsl:
            slices[float(alt)] = self.compute_network_coverage_grid(
                grid_bounds=grid_bounds,
                grid_resolution_m=grid_resolution_m,
                target_altitude_amsl=float(alt),
                target_rcs_m2=target_rcs_m2,
            )
        overlap_3d = np.stack([slices[float(a)]["overlap_count"] for a in altitudes_amsl], axis=0)
        joint_pd_3d = np.stack([slices[float(a)]["joint_pd"] for a in altitudes_amsl], axis=0)
        return {
            "altitudes_amsl": [float(a) for a in altitudes_amsl],
            "overlap_3d": overlap_3d,
            "joint_pd_3d": joint_pd_3d,
            "slices": slices,
        }

    def screen_mobile_gap_filler_sites(
        self,
        candidate_coords: list[tuple[float, float]],
        grid_bounds: tuple[float, float, float, float],
        grid_resolution_m: float,
        target_altitude_amsl: float = 500.0,
        target_rcs_m2: float = 0.5,
        template_radar: RadarPlatform | None = None,
    ) -> list[dict[str, Any]]:
        """Screens candidate tactical mobile deployment coordinates (lon/easting, lat/northing)
        to rank which candidate best fills low-altitude blind spots (k=0).
        """
        baseline = self.compute_network_coverage_grid(
            grid_bounds=grid_bounds,
            grid_resolution_m=grid_resolution_m,
            target_altitude_amsl=target_altitude_amsl,
            target_rcs_m2=target_rcs_m2,
        )
        baseline_blind = baseline["overlap_count"] == 0
        x_coords = baseline["x_coords"]
        y_coords = baseline["y_coords"]
        baseline_cov_pct = float(np.mean(~baseline_blind) * 100.0)

        rankings: list[dict[str, Any]] = []
        for idx, (cand_lon, cand_lat) in enumerate(candidate_coords):
            ground_el = (
                float(self.terrain_manager.sample_elevation(cand_lon, cand_lat))
                if self.terrain_manager is not None
                else 50.0
            )
            if template_radar is not None:
                cand_radar = RadarPlatform(
                    site_id=f"CAND-GAP-{idx + 1:02d}",
                    name=f"Candidate Mobile Gap-Filler #{idx + 1}",
                    brand=template_radar.brand,
                    model=template_radar.model,
                    radar_category=template_radar.radar_category,
                    mobility=MobilityType.MOBILE_TACTICAL,
                    tech=template_radar.tech,
                    lat=float(cand_lat),
                    lon=float(cand_lon),
                    mast_height_agl=template_radar.mast_height_agl,
                    ground_elevation_amsl=ground_el,
                    instrumented_max_range_km=template_radar.instrumented_max_range_km,
                    frequency_ghz=template_radar.frequency_ghz,
                    peak_power_kw=template_radar.peak_power_kw,
                    pulse_width_us=template_radar.pulse_width_us,
                    antenna_gain_dbi=template_radar.antenna_gain_dbi,
                )
            else:
                cand_radar = RadarPlatform(
                    site_id=f"CAND-GAP-{idx + 1:02d}",
                    name=f"Candidate Mobile Gap-Filler #{idx + 1}",
                    brand="Saab",
                    model="Giraffe AMB",
                    radar_category="Short_Range_AD",
                    mobility=MobilityType.MOBILE_TACTICAL,
                    tech=AntennaTechnology.FULL_AESA,
                    lat=float(cand_lat),
                    lon=float(cand_lon),
                    mast_height_agl=12.0,
                    ground_elevation_amsl=ground_el,
                    instrumented_max_range_km=120.0,
                    frequency_ghz=5.6,
                    peak_power_kw=35.0,
                    pulse_width_us=10.0,
                    antenna_gain_dbi=35.0,
                )

            detected, _, _, _ = self._evaluate_single_radar_on_grid(
                cand_radar,
                x_coords,
                y_coords,
                target_altitude_amsl=target_altitude_amsl,
                target_rcs_m2=target_rcs_m2,
            )
            newly_covered_cells = int(np.sum(detected & baseline_blind))
            new_cov_pct = float(np.mean((~baseline_blind) | detected) * 100.0)
            rankings.append(
                {
                    "candidate_id": cand_radar.site_id,
                    "lon": float(cand_lon),
                    "lat": float(cand_lat),
                    "ground_elevation_amsl": round(ground_el, 2),
                    "newly_covered_blind_cells": newly_covered_cells,
                    "blind_spot_reduction_pct": round(
                        (newly_covered_cells / max(int(np.sum(baseline_blind)), 1)) * 100.0, 2
                    ),
                    "baseline_coverage_pct": round(baseline_cov_pct, 2),
                    "augmented_coverage_pct": round(new_cov_pct, 2),
                    "coverage_gain_pct": round(new_cov_pct - baseline_cov_pct, 2),
                }
            )

        rankings.sort(key=lambda item: item["newly_covered_blind_cells"], reverse=True)
        return rankings

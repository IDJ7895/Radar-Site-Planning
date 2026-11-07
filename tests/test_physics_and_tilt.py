"""Tests for Milestone 2: Radar Equation, Mechanical/AESA Tilt & Diffraction (GH-05 to GH-07)."""

from __future__ import annotations

import numpy as np

from multi_radar_suite import (
    AntennaTechnology,
    MobilityType,
    RadarPlatform,
    compute_3d_rotation_matrix,
    compute_blake_chart_atmospheric_loss_db,
    compute_knife_edge_diffraction_loss_db,
    compute_marcum_q_pd,
)


def test_mechanical_vs_aesa_tilt_physics():
    # Legacy Mechanical Radar tilted up +30 deg retains full peak gain at +30 deg
    mech_radar = RadarPlatform(
        site_id="MECH-01",
        name="Mechanical EW",
        brand="Lockheed",
        model="TPS-70",
        radar_category="Early_Warning",
        mobility=MobilityType.FIXED,
        tech=AntennaTechnology.LEGACY_MECHANICAL,
        lat=1500000.0,
        lon=600000.0,
        mast_height_agl=25.0,
        antenna_gain_dbi=40.0,
        mechanical_tilt_deg=30.0,
        electronic_tilt_deg=0.0,
    )
    # Full AESA Radar electronically steered to +30 deg experiences cos^1.3(30 deg) scan loss
    aesa_radar = RadarPlatform(
        site_id="AESA-01",
        name="AESA MMR",
        brand="IAI Elta",
        model="ELM-2084",
        radar_category="Air_Defense",
        mobility=MobilityType.FIXED,
        tech=AntennaTechnology.FULL_AESA,
        lat=1500000.0,
        lon=600000.0,
        mast_height_agl=25.0,
        antenna_gain_dbi=40.0,
        mechanical_tilt_deg=0.0,
        electronic_tilt_deg=30.0,
    )

    g_mech_on_beam = mech_radar.compute_aperture_gain(30.0)
    g_aesa_on_beam = aesa_radar.compute_aperture_gain(30.0)

    # Mechanical preserves 10^(40/10) = 10000 linear gain on boresight
    assert np.isclose(g_mech_on_beam, 10000.0, rtol=1e-4)
    # AESA degrades by cos(30 deg)^1.3
    expected_aesa = 10000.0 * (np.cos(np.radians(30.0)) ** 1.3)
    assert np.isclose(g_aesa_on_beam, expected_aesa, rtol=1e-4)
    assert g_aesa_on_beam < g_mech_on_beam

    # Free-space R_max also reflects AESA scan loss
    assert aesa_radar.calculate_free_space_rmax(1.0) < mech_radar.calculate_free_space_rmax(1.0)

    # Downward tilt clutter penalty: Mechanical suffers much higher ground clutter than AESA nulling
    mech_down = RadarPlatform(
        site_id="MECH-DN",
        name="Mech Down",
        brand="Brand",
        model="Model",
        radar_category="AD",
        mobility=MobilityType.FIXED,
        tech=AntennaTechnology.LEGACY_MECHANICAL,
        lat=0.0,
        lon=0.0,
        mast_height_agl=15.0,
        mechanical_tilt_deg=-2.0,
    )
    aesa_down = RadarPlatform(
        site_id="AESA-DN",
        name="AESA Down",
        brand="Brand",
        model="Model",
        radar_category="AD",
        mobility=MobilityType.FIXED,
        tech=AntennaTechnology.FULL_AESA,
        lat=0.0,
        lon=0.0,
        mast_height_agl=15.0,
        electronic_tilt_deg=-2.0,
    )
    assert mech_down.compute_clutter_penalty_db(0.0) > aesa_down.compute_clutter_penalty_db(0.0)

    # Verify 3D gimbal rotation matrix is orthonormal (det == 1, R.T @ R == I)
    rot = compute_3d_rotation_matrix(45.0, 15.0)
    assert np.allclose(rot.T @ rot, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(rot), 1.0, atol=1e-9)


def test_itu_p526_knife_edge_diffraction_and_blake_marcum():
    # Clear LoS with wide Fresnel clearance -> 0 dB diffraction loss
    loss_clear = compute_knife_edge_diffraction_loss_db(
        h_obstacle_clearance_m=200.0,
        d1_radar_to_peak_m=20000.0,
        d2_peak_to_target_m=20000.0,
        frequency_ghz=3.0,
    )
    assert loss_clear == 0.0

    # Grazing incidence (clearance = 0 -> v = 0 -> ~6.0 dB knife-edge diffraction loss)
    loss_grazing = compute_knife_edge_diffraction_loss_db(
        h_obstacle_clearance_m=0.0,
        d1_radar_to_peak_m=20000.0,
        d2_peak_to_target_m=20000.0,
        frequency_ghz=3.0,
    )
    assert 5.8 <= loss_grazing <= 6.2

    # Deep terrain shadow (clearance = -100m, ridge blocks ray by 100m) -> > 20 dB loss
    loss_shadow = compute_knife_edge_diffraction_loss_db(
        h_obstacle_clearance_m=-100.0,
        d1_radar_to_peak_m=20000.0,
        d2_peak_to_target_m=20000.0,
        frequency_ghz=3.0,
    )
    assert loss_shadow > 20.0

    # Blake atmospheric loss and Marcum Q Pd
    atm_loss = compute_blake_chart_atmospheric_loss_db(
        100000.0, frequency_ghz=3.0, elevation_deg=2.0
    )
    assert atm_loss > 0.0

    pd_low = compute_marcum_q_pd(snr_linear=1.0, pfa=1e-6)
    pd_high = compute_marcum_q_pd(snr_linear=25.0, pfa=1e-6)
    assert pd_low < 0.05
    assert pd_high > 0.90

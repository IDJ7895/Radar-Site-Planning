"""End-to-End Database Add + 11-Radar Batch Execution Script."""

from __future__ import annotations

import numpy as np

from multi_radar_suite import MultiRadarNetworkManager
from radar_db import RadarDatabaseManager


def run_simulation(db_url: str = "sqlite:///rtaf_radar_simulation.db") -> dict[str, np.ndarray]:
    # 1. Initialize SQLite Database Manager
    db = RadarDatabaseManager(db_url)

    # 2. Populate Database with 11 Radars (6 Fixed Strategic, 5 Mobile Tactical/cUAS)
    print("=== STAGE 1: POPULATING RADAR DATABASE & RUNNING INSTANT PRE-CHECKS ===")
    sample_brands = [
        ("IAI Elta", "ELM-2084 MMR", "Air_Defense", 450.0),
        ("Lockheed Martin", "AN/TPS-77", "Early_Warning", 470.0),
        ("Saab", "Giraffe AMB", "Short_Range_AD", 120.0),
        ("Thales", "Ground Master 400", "Early_Warning", 400.0),
        ("IAI Elta", "ELM-2138M Green Rock", "cUAS_Tactical", 40.0),
    ]

    for i in range(1, 12):
        is_mobile = i > 6
        is_aesa = i % 2 == 1
        brand, model, category, inst_range_km = sample_brands[i % len(sample_brands)]

        radar_entry = {
            "site_id": f"RAD-{'MB' if is_mobile else 'FX'}-{i:02d}",
            "site_name": f"{'Tactical Mobile' if is_mobile else 'Fixed Sector'} Site #{i}",
            "brand": brand,
            "model": model,
            "radar_category": category,
            "mobility": "MOBILE_TACTICAL" if is_mobile else "FIXED",
            "tech": "FULL_AESA" if is_aesa else "LEGACY_MECHANICAL",
            "lat": 1500000.0 + (i * 12000.0),  # Metric UTM Northing (m)
            "lon": 600000.0 + ((i % 4) * 25000.0),  # Metric UTM Easting (m)
            "ground_elevation_amsl": 120.0 if not is_mobile else 45.0,
            "mast_height_agl": 10.0 if is_mobile else 30.0,
            "instrumented_max_range_km": inst_range_km,
            "frequency_ghz": 3.0,
            "peak_power_kw": 40.0 if is_mobile else 100.0,
            "pulse_width_us": 15.0,
            "antenna_gain_dbi": 36.0 if is_mobile else 40.0,
            "electronic_tilt_deg": 2.0 if is_aesa else 0.0,
            "mechanical_tilt_deg": 0.0 if is_aesa else -0.5,
            "field_of_regard_az_deg": 360.0,
            "is_active": True,
        }

        # Add to DB -> Immediately triggers Stage 1 Instant Pre-Check
        res = db.add_or_update_radar(radar_entry, preview_rcs_m2=1.0, preview_alt_m=3000.0)
        chk = res["instant_precheck"]
        print(
            f"[{res['site_id']}] {res['brand_model']} -> "
            f"Effective R_max: {chk['effective_rmax_km']} km | "
            f"Horizon: {chk['radar_horizon_km_at_target_alt']} km"
        )

    # 3. Stage 2: Load Active Fleet from DB into Multi-Radar Network Manager
    print("\n=== STAGE 2: EXECUTING ON-DEMAND 11-RADAR BATCH SIMULATION ===")
    network_mgr = MultiRadarNetworkManager()
    loaded_count = network_mgr.load_active_fleet_from_db(db)
    print(f"Loaded {loaded_count} active radars from SQLite database.")

    # 4. Run Simultaneous Multi-Radar Coverage Grid (150 km x 150 km AOR)
    bounds = (580000.0, 1480000.0, 730000.0, 1630000.0)
    results = network_mgr.compute_network_coverage_grid(
        grid_bounds=bounds,
        grid_resolution_m=2000.0,
        target_altitude_amsl=3000.0,
        target_rcs_m2=1.0,
    )

    overlap = results["overlap_count"]
    joint_pd = results["joint_pd"]

    print("\n--- BATCH NETWORK SIMULATION SUMMARY ---")
    print(f"Max Multi-Radar Overlap: {np.max(overlap)} radars illuminating same cell")
    print(f"Coverage with k >= 1 (Detected Area): {np.mean(overlap >= 1) * 100:.1f}%")
    print(f"Coverage with k >= 2 (Handover / Redundant): {np.mean(overlap >= 2) * 100:.1f}%")
    print(f"High Confidence Network Pd (Pd >= 0.90): {np.mean(joint_pd >= 0.90) * 100:.1f}%")
    db.close()
    return results


if __name__ == "__main__":
    run_simulation()

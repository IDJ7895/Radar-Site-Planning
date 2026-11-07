"""Root-level Multi-Radar Network Planning Suite & RF Physics Engine."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from radar_site_planning.multi_radar_suite import (  # noqa: E402
    AntennaTechnology,
    MobilityType,
    MultiRadarNetworkManager,
    RadarPlatform,
    compute_3d_rotation_matrix,
    compute_blake_chart_atmospheric_loss_db,
    compute_knife_edge_diffraction_loss_db,
    compute_marcum_q_pd,
)

__all__ = [
    "AntennaTechnology",
    "MobilityType",
    "MultiRadarNetworkManager",
    "RadarPlatform",
    "compute_3d_rotation_matrix",
    "compute_blake_chart_atmospheric_loss_db",
    "compute_knife_edge_diffraction_loss_db",
    "compute_marcum_q_pd",
]

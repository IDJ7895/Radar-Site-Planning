"""Root-level SQLAlchemy Database Module for the Integrated Multi-Radar Planning Suite."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from radar_site_planning.radar_db import (  # noqa: E402
    Base,
    RadarDatabaseManager,
    RadarRecordORM,
    Stage1SaveResult,
)

__all__ = ["Base", "RadarDatabaseManager", "RadarRecordORM", "Stage1SaveResult"]

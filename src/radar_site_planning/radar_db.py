"""SQLAlchemy 2.0 Database Module & Dual-Mode Pipeline (GH-01, GH-02, GH-08)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    event,
    select,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .models import RadarRecord, StoredRadar


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base."""


class RadarRecordORM(Base):
    """Relational Database Table storing Radar Hardware Specs, Site Location & Tilt Settings."""

    __tablename__ = "radar_systems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(50), unique=True, nullable=False, index=True)
    site_name = Column(String(120), nullable=False)

    # Hardware Brand, Model & Classification
    brand = Column(String(120), nullable=False)
    model = Column(String(120), nullable=False)
    radar_category = Column(String(120), nullable=False, default="Early_Warning")
    mobility = Column(String(30), nullable=False, default="FIXED")
    tech = Column(String(30), nullable=False, default="LEGACY_MECHANICAL")

    # Geolocation & Installation Parameters
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    ground_elevation_amsl = Column(Float, nullable=False, default=0.0)
    mast_height_agl = Column(Float, nullable=False, default=10.0)

    # Transmitter / Receiver & Range Specifications
    instrumented_max_range_km = Column(Float, nullable=False)
    frequency_ghz = Column(Float, nullable=False)
    peak_power_kw = Column(Float, nullable=False)
    pulse_width_us = Column(Float, nullable=False, default=10.0)
    noise_figure_db = Column(Float, nullable=False, default=3.5)
    system_loss_db = Column(Float, nullable=False, default=6.0)
    min_snr_db = Column(Float, nullable=False, default=13.0)

    # Antenna Pattern & Tilt Configuration
    antenna_gain_dbi = Column(Float, nullable=False)
    az_beamwidth_deg = Column(Float, nullable=False, default=1.4)
    el_beamwidth_deg = Column(Float, nullable=False, default=2.0)
    mechanical_tilt_deg = Column(Float, nullable=False, default=0.0)
    electronic_tilt_deg = Column(Float, nullable=False, default=0.0)
    azimuth_boresight_deg = Column(Float, nullable=False, default=0.0)
    field_of_regard_az_deg = Column(Float, nullable=False, default=360.0)

    # Operational Status & Metadata
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    @property
    def latitude(self) -> float:
        return float(self.lat)

    @property
    def longitude(self) -> float:
        return float(self.lon)

    @property
    def mobility_type(self) -> str:
        return str(self.mobility)

    @property
    def antenna_tech(self) -> str:
        return str(self.tech)


class Stage1SaveResult(dict):
    """Hybrid dictionary and StoredRadar proxy returned by add_or_update_radar().

    Supports dict-key access (`res["instant_precheck"]`, `res["site_id"]`, `res["status"]`)
    as well as attribute/model access (`res.site_id`, `res.mast_height_agl`, `res.model_dump()`)
    and equality comparison with `StoredRadar`.
    """

    def __init__(self, payload: dict[str, Any], stored_radar: StoredRadar) -> None:
        super().__init__(payload)
        self._stored = stored_radar

    @property
    def record(self) -> StoredRadar:
        return self._stored

    def __getattr__(self, name: str) -> Any:
        try:
            return getattr(self._stored, name)
        except AttributeError as exc:
            raise AttributeError(name) from exc

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return self._stored.model_dump(**kwargs)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, StoredRadar):
            return self._stored == other
        if isinstance(other, Stage1SaveResult):
            return self._stored == other._stored
        return super().__eq__(other)


_RECORD_COLUMNS = tuple(RadarRecord.model_fields.keys())


def _serialize_row(row: RadarRecordORM) -> StoredRadar:
    created = row.created_at or datetime.now(UTC).replace(tzinfo=None)
    updated = row.updated_at or created
    return StoredRadar.model_validate(
        {
            "id": row.id,
            **{key: getattr(row, key) for key in _RECORD_COLUMNS},
            "created_at": created.replace(tzinfo=UTC),
            "updated_at": updated.replace(tzinfo=UTC),
        }
    )


def _normalize_db_url(db_url_or_path: str | Path) -> str | URL:
    if isinstance(db_url_or_path, Path):
        return URL.create("sqlite+pysqlite", database=str(db_url_or_path))
    text_val = str(db_url_or_path)
    if text_val.startswith("sqlite:"):
        return text_val
    return URL.create("sqlite+pysqlite", database=text_val)


class RadarDatabaseManager:
    """Manages CRUD operations for the Radar Catalog Database and provides
    Stage-1 Instant Pre-Checks (<5 ms) and Stage-2 Batch Simulation conversion.
    """

    def __init__(self, db_url: str | Path = "sqlite:///radar_catalog.db") -> None:
        target = _normalize_db_url(db_url)
        self.engine = create_engine(
            target,
            echo=False,
            connect_args={"timeout": 10},
        )

        @event.listens_for(self.engine, "connect")
        def _configure(connection: Any, _record: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def __enter__(self) -> RadarDatabaseManager:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _upsert_row(session: Session, record: RadarRecord) -> tuple[RadarRecordORM, StoredRadar]:
        data = record.model_dump(mode="json")
        attributes = {key: data[key] for key in _RECORD_COLUMNS}
        now = datetime.now(UTC).replace(tzinfo=None)
        row = session.scalar(select(RadarRecordORM).where(RadarRecordORM.site_id == record.site_id))
        if row is None:
            row = RadarRecordORM(**attributes, created_at=now, updated_at=now)
            session.add(row)
        else:
            for key, value in attributes.items():
                setattr(row, key, value)
            row.updated_at = now
        session.flush()
        return row, _serialize_row(row)

    def add_or_update_radar(
        self,
        radar_data: Mapping[str, Any] | RadarRecord,
        preview_rcs_m2: float = 1.0,
        preview_alt_m: float = 3000.0,
    ) -> Stage1SaveResult:
        """Inserts or updates a radar record in the database and immediately executes
        Stage-1 Instant Pre-Check (<5 ms) to verify physics performance.
        """
        raw = radar_data.model_dump() if isinstance(radar_data, RadarRecord) else dict(radar_data)
        validated = RadarRecord.model_validate(raw)

        with self.SessionLocal() as session, session.begin():
            row, stored = self._upsert_row(session, validated)
            precheck = self._run_stage1_instant_precheck(row, preview_rcs_m2, preview_alt_m)

        payload = {
            "status": "SAVED",
            "site_id": stored.site_id,
            "brand_model": f"{stored.brand} {stored.model}",
            "instant_precheck": precheck,
        }
        return Stage1SaveResult(payload, stored)

    def _run_stage1_instant_precheck(
        self,
        rec: RadarRecordORM | RadarRecord,
        rcs_m2: float = 1.0,
        target_alt_m: float = 3000.0,
    ) -> dict[str, float]:
        """Fast (<5 ms) analytical calculation triggered immediately upon saving a radar."""
        t_start = time.perf_counter()

        c = 3e8
        wavelength = c / (float(rec.frequency_ghz) * 1e9)
        pt = float(rec.peak_power_kw) * 1e3
        g_lin = 10.0 ** (float(rec.antenna_gain_dbi) / 10.0)

        scan_loss_db = 0.0
        tech_str = str(rec.tech)
        el_tilt = float(rec.electronic_tilt_deg)
        if tech_str == "FULL_AESA" and abs(el_tilt) > 0.0:
            scan_factor = float(np.cos(np.radians(el_tilt)) ** 1.3)
            g_lin *= scan_factor
            scan_loss_db = float(-10.0 * np.log10(max(scan_factor, 1e-4)))

        effective_boresight_gain_dbi = float(10.0 * np.log10(max(g_lin, 1e-12)))

        kb = 1.380649e-23
        t0 = 290.0
        b_rx = 1.0 / (float(rec.pulse_width_us) * 1e-6)
        p_noise = kb * t0 * b_rx * (10.0 ** (float(rec.noise_figure_db) / 10.0))
        snr_min = 10.0 ** (float(rec.min_snr_db) / 10.0)
        l_sys = 10.0 ** (float(rec.system_loss_db) / 10.0)

        r_max_calc_m = (
            (pt * (g_lin**2) * (wavelength**2) * float(rcs_m2))
            / (((4.0 * np.pi) ** 3) * p_noise * snr_min * l_sys)
        ) ** 0.25
        r_max_calc_km = float(r_max_calc_m / 1000.0)

        inst_limit_km = float(rec.instrumented_max_range_km)
        effective_rmax_km = min(r_max_calc_km, inst_limit_km)

        # 4/3 Earth Radar Horizon (ITU-R P.834)
        re_eff = 6371000.0 * (4.0 / 3.0)
        h_ant = max(float(rec.ground_elevation_amsl) + float(rec.mast_height_agl), 1.0)
        horizon_km = float(
            (np.sqrt(2.0 * re_eff * h_ant) + np.sqrt(2.0 * re_eff * max(float(target_alt_m), 1.0)))
            / 1000.0
        )

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        return {
            "theoretical_rmax_km": round(r_max_calc_km, 2),
            "free_space_rmax_km": round(r_max_calc_km, 2),
            "instrumented_limit_km": round(inst_limit_km, 2),
            "effective_rmax_km": round(effective_rmax_km, 2),
            "radar_horizon_km_at_target_alt": round(horizon_km, 2),
            "4_3_earth_horizon_km": round(horizon_km, 2),
            "aesa_scan_loss_db": round(scan_loss_db, 2),
            "effective_boresight_gain_dbi": round(effective_boresight_gain_dbi, 2),
            "execution_time_ms": round(elapsed_ms, 4),
        }

    def import_radars(self, records: Iterable[Mapping[str, Any]]) -> list[StoredRadar]:
        """Atomically validates and imports a batch of radar records."""
        validated = [RadarRecord.model_validate(dict(data)) for data in records]
        ids = [record.site_id for record in validated]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate site_id in import; no records were saved")
        with self.SessionLocal() as session, session.begin():
            results = [self._upsert_row(session, record)[1] for record in validated]
        return results

    def load_catalog_file(self, path: str | Path) -> list[StoredRadar]:
        """Imports radar records from a YAML or JSON catalog file."""
        file_path = Path(path)
        text_content = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text_content)
        else:
            data = json.loads(text_content)
        if isinstance(data, dict) and "radars" in data:
            records = data["radars"]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError("Catalog file must contain a list of radar objects or a 'radars' key")
        return self.import_radars(records)

    def get_radar(self, site_id: str) -> StoredRadar:
        with self.SessionLocal() as session:
            row = session.scalar(select(RadarRecordORM).where(RadarRecordORM.site_id == site_id))
            if row is None:
                raise KeyError(site_id)
            return _serialize_row(row)

    def list_radars(self, *, active_only: bool = False) -> list[StoredRadar]:
        query = select(RadarRecordORM).order_by(RadarRecordORM.site_id)
        if active_only:
            query = query.where(RadarRecordORM.is_active.is_(True))
        with self.SessionLocal() as session:
            return [_serialize_row(row) for row in session.scalars(query).all()]

    def list_active_radars(self) -> list[StoredRadar]:
        """Returns all active radars from the database for Stage-2 Batch Network Simulation."""
        return self.list_radars(active_only=True)

    def patch_radar(self, site_id: str, changes: Mapping[str, Any]) -> StoredRadar:
        if "site_id" in changes or "radar_id" in changes:
            raise ValueError("site_id cannot be changed; create a new record instead")
        with self.SessionLocal() as session, session.begin():
            row = session.scalar(select(RadarRecordORM).where(RadarRecordORM.site_id == site_id))
            if row is None:
                raise KeyError(site_id)
            data = _serialize_row(row).model_dump(exclude={"id", "created_at", "updated_at"})
            record = RadarRecord.model_validate({**data, **changes})
            _, stored = self._upsert_row(session, record)
        return stored

    def delete_radar(self, site_id: str) -> None:
        with self.SessionLocal() as session, session.begin():
            row = session.scalar(select(RadarRecordORM).where(RadarRecordORM.site_id == site_id))
            if row is None:
                raise KeyError(site_id)
            session.delete(row)

    def simulate_active_network_from_db(
        self,
        grid_bounds: tuple[float, float, float, float] | None = None,
        grid_resolution_m: float = 2000.0,
        target_altitude_amsl: float = 3000.0,
        target_rcs_m2: float = 1.0,
        terrain_manager: Any | None = None,
    ) -> dict[str, Any]:
        """Stage-2 Trigger: Queries all active radars from DB and runs network simulation."""
        from .multi_radar_suite import MultiRadarNetworkManager

        mgr = MultiRadarNetworkManager(terrain_manager=terrain_manager)
        count = mgr.load_active_fleet_from_db(self)
        if count == 0:
            raise ValueError("No active radars found in database for Stage-2 simulation")

        if grid_bounds is None:
            lats = [r.lat for r in mgr.radars.values()]
            lons = [r.lon for r in mgr.radars.values()]
            pad = 50000.0 if max(map(abs, lats)) > 90.0 else 0.5
            grid_bounds = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)

        return mgr.compute_network_coverage_grid(
            grid_bounds=grid_bounds,
            grid_resolution_m=grid_resolution_m,
            target_altitude_amsl=target_altitude_amsl,
            target_rcs_m2=target_rcs_m2,
        )

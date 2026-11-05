"""SQLAlchemy 2 catalog. Every mutation validates before committing."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, String, create_engine, event, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import RadarRecord, StoredRadar


class Base(DeclarativeBase):
    pass


class RadarRecordORM(Base):
    __tablename__ = "radar_systems"

    site_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    site_name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, index=True)
    radar_category: Mapped[str] = mapped_column(String(120))
    mobility_type: Mapped[str] = mapped_column(String(30))
    antenna_tech: Mapped[str] = mapped_column(String(30))
    ground_elevation_amsl: Mapped[float] = mapped_column(Float)
    mast_height_agl: Mapped[float] = mapped_column(Float)
    instrumented_max_range_km: Mapped[float] = mapped_column(Float)
    peak_power_kw: Mapped[float] = mapped_column(Float)
    frequency_ghz: Mapped[float] = mapped_column(Float)
    pulse_width_us: Mapped[float] = mapped_column(Float)
    antenna_gain_dbi: Mapped[float] = mapped_column(Float)
    az_beamwidth_deg: Mapped[float] = mapped_column(Float)
    el_beamwidth_deg: Mapped[float] = mapped_column(Float)
    mechanical_tilt_deg: Mapped[float] = mapped_column(Float)
    electronic_tilt_deg: Mapped[float] = mapped_column(Float)
    azimuth_boresight_deg: Mapped[float] = mapped_column(Float)
    field_of_regard_az_deg: Mapped[float] = mapped_column(Float)
    noise_figure_db: Mapped[float] = mapped_column(Float)
    system_loss_db: Mapped[float] = mapped_column(Float)
    min_snr_db: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


_COLUMNS = set(RadarRecord.model_fields)


def _serialize(row: RadarRecordORM) -> StoredRadar:
    return StoredRadar.model_validate(
        {
            **{key: getattr(row, key) for key in _COLUMNS},
            # SQLite does not preserve tzinfo; stored timestamps are always UTC.
            "created_at": row.created_at.replace(tzinfo=UTC),
            "updated_at": row.updated_at.replace(tzinfo=UTC),
        }
    )


class RadarDatabaseManager:
    """Owns one SQLite engine. Use as a context manager or call close().

    add_or_update_radar replaces the complete record; patch_radar merges only the
    supplied fields. import_radars validates the entire batch before any writes.
    Parent directories must exist. ':memory:' creates a temporary catalog.
    """

    def __init__(self, database: str | Path = "radar_catalog.db") -> None:
        self.engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(database)),
            connect_args={"timeout": 10},
        )

        @event.listens_for(self.engine, "connect")
        def _configure(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)

    def __enter__(self) -> "RadarDatabaseManager":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _save(session: Session, record: RadarRecord) -> StoredRadar:
        data = record.model_dump(mode="json")
        attributes = {key: data[key] for key in _COLUMNS}
        now = datetime.now(UTC).replace(tzinfo=None)
        row = session.get(RadarRecordORM, record.site_id)
        if row is None:
            row = RadarRecordORM(**attributes, created_at=now, updated_at=now)
            session.add(row)
        else:
            for key, value in attributes.items():
                setattr(row, key, value)
            row.updated_at = now
        session.flush()
        return _serialize(row)

    def add_or_update_radar(self, data: Mapping[str, Any] | RadarRecord) -> StoredRadar:
        # Revalidate even model instances (including ones made with model_construct).
        raw = data.model_dump() if isinstance(data, RadarRecord) else dict(data)
        record = RadarRecord.model_validate(raw)
        with Session(self.engine) as session, session.begin():
            result = self._save(session, record)
        return result

    def import_radars(self, records: Iterable[Mapping[str, Any]]) -> list[StoredRadar]:
        validated = [RadarRecord.model_validate(dict(data)) for data in records]
        ids = [record.site_id for record in validated]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate site_id in import; no records were saved")
        with Session(self.engine) as session, session.begin():
            results = [self._save(session, record) for record in validated]
        return results

    def get_radar(self, site_id: str) -> StoredRadar:
        with Session(self.engine) as session:
            row = session.get(RadarRecordORM, site_id)
            if row is None:
                raise KeyError(site_id)
            return _serialize(row)

    def list_radars(self, *, active_only: bool = False) -> list[StoredRadar]:
        query = select(RadarRecordORM).order_by(RadarRecordORM.site_id)
        if active_only:
            query = query.where(RadarRecordORM.is_active.is_(True))
        with Session(self.engine) as session:
            return [_serialize(row) for row in session.scalars(query)]

    def list_active_radars(self) -> list[StoredRadar]:
        return self.list_radars(active_only=True)

    def patch_radar(self, site_id: str, changes: Mapping[str, Any]) -> StoredRadar:
        if "site_id" in changes:
            raise ValueError("site_id cannot be changed; create a new record instead")
        with Session(self.engine) as session, session.begin():
            row = session.get(RadarRecordORM, site_id)
            if row is None:
                raise KeyError(site_id)
            data = _serialize(row).model_dump(exclude={"created_at", "updated_at"})
            record = RadarRecord.model_validate({**data, **changes})
            result = self._save(session, record)
        return result

    def delete_radar(self, site_id: str) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(RadarRecordORM, site_id)
            if row is None:
                raise KeyError(site_id)
            session.delete(row)

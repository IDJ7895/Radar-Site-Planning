from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from radar_site_planning import RadarDatabaseManager


def test_records_persist_across_reopen(tmp_path, record):
    path = tmp_path / "catalog with spaces.db"
    with RadarDatabaseManager(path) as manager:
        saved = manager.add_or_update_radar(record)
    with RadarDatabaseManager(path) as manager:
        loaded = manager.get_radar(record["site_id"])
        assert loaded == saved
        assert loaded.created_at.utcoffset() == timedelta(0)


def test_replace_and_patch_semantics(catalog, record):
    original = catalog.add_or_update_radar({**record, "mast_height_agl": 25})
    patched = catalog.patch_radar(record["site_id"], {"site_name": "Renamed"})
    assert patched.mast_height_agl == 25
    assert patched.site_name == "Renamed"
    assert patched.created_at == original.created_at
    assert patched.updated_at >= original.updated_at
    replaced = catalog.add_or_update_radar(record)
    assert replaced.mast_height_agl == 10
    assert len(catalog.list_radars()) == 1


@pytest.mark.parametrize("changes", [{"frequency_ghz": 0}, {"unknown": 1}, {"site_id": "new"}])
def test_invalid_patch_does_not_change_database(catalog, record, changes):
    before = catalog.add_or_update_radar(record)
    with pytest.raises(ValueError):
        catalog.patch_radar(record["site_id"], changes)
    assert catalog.get_radar(record["site_id"]) == before


def test_invalid_batch_does_not_partially_update_existing_records(catalog, record):
    before = catalog.add_or_update_radar(record)
    with pytest.raises(ValidationError):
        catalog.import_radars(
            [
                {**record, "site_name": "Should not save"},
                {**record, "site_id": "bad", "latitude": 100},
            ]
        )
    assert catalog.list_radars() == [before]


def test_database_failure_rolls_back_entire_batch(catalog, record):
    before = catalog.add_or_update_radar(record)
    # Force a storage error after the first write, exercising the DB transaction.
    with catalog.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER reject_test BEFORE INSERT ON radar_systems "
                "WHEN NEW.site_id = 'reject' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        )
    with pytest.raises(IntegrityError):
        catalog.import_radars(
            [
                {**record, "site_name": "Should roll back"},
                {**record, "site_id": "reject"},
            ]
        )
    assert catalog.list_radars() == [before]


def test_duplicate_import_rejected_after_id_normalization(catalog, record):
    with pytest.raises(ValueError, match="Duplicate"):
        catalog.import_radars([record, {**record, "site_id": " research-01 "}])
    assert catalog.list_radars() == []


def test_eleven_sites_active_filter_and_delete(catalog, record):
    batch = [{**record, "site_id": f"research-{i:02}", "is_active": i % 2 == 0} for i in range(11)]
    assert len(catalog.import_radars(batch)) == 11
    assert len(catalog.list_radars()) == 11
    assert len(catalog.list_active_radars()) == 6
    assert [row.site_id for row in catalog.list_radars()] == sorted(r["site_id"] for r in batch)
    catalog.delete_radar("research-00")
    assert len(catalog.list_active_radars()) == 5
    with pytest.raises(KeyError):
        catalog.get_radar("research-00")


@pytest.mark.parametrize("operation", ["get_radar", "delete_radar", "patch_radar"])
def test_missing_site(catalog, operation):
    args = ("missing", {}) if operation == "patch_radar" else ("missing",)
    with pytest.raises(KeyError):
        getattr(catalog, operation)(*args)

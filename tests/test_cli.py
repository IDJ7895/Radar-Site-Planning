import json
import subprocess
import sys

import pytest

from radar_site_planning.cli import main


def test_cli_import_patch_export_round_trip(tmp_path, record, capsys):
    source = tmp_path / "sites.json"
    source.write_text(json.dumps([record]), encoding="utf-8")
    args = ["--db", str(tmp_path / "first.db")]
    assert main([*args, "import", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
    changes = tmp_path / "changes.json"
    changes.write_text('{"is_active": false}', encoding="utf-8")
    assert main([*args, "patch", record["site_id"], str(changes)]) == 0
    assert json.loads(capsys.readouterr().out)["is_active"] is False
    assert main([*args, "list", "--active"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main([*args, "export"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert "updated_at" not in exported[0]
    source.write_text(json.dumps(exported), encoding="utf-8")
    second = ["--db", str(tmp_path / "second.db")]
    assert main([*second, "import", str(source)]) == 0
    capsys.readouterr()
    assert main([*second, "get", record["site_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["is_active"] is False
    assert main([*second, "delete", record["site_id"]]) == 0
    capsys.readouterr()
    assert main([*second, "get", record["site_id"]]) == 2
    assert "Site not found" in capsys.readouterr().err


@pytest.mark.parametrize("contents", ["{broken", "[1]", "{}", "null"])
def test_cli_bad_import_has_no_traceback_or_catalog(tmp_path, capsys, contents):
    source = tmp_path / "bad.json"
    source.write_text(contents, encoding="utf-8")
    database = tmp_path / "bad.db"
    assert main(["--db", str(database), "import", str(source)]) == 2
    output = capsys.readouterr()
    assert "Error:" in output.err
    assert "Traceback" not in output.err
    assert not database.exists()


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "radar_site_planning", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "import" in result.stdout

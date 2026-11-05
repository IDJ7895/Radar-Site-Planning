# Radar Site Planning

A Python catalog for civilian radar research and site inventory. This first
increment provides validated equipment records, transactional SQLite persistence,
and a JSON command-line workflow.

**Status:** catalog foundation, version 0.1.0. RF propagation, terrain ingestion,
coverage calculations, and a web dashboard are not implemented. Eleven catalog
records demonstrate inventory handling; they do not demonstrate a network simulation.

## Quick start

Requires Python 3.11 or later.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
radar-catalog --db radar_catalog.db init
radar-catalog --db radar_catalog.db import examples/research_sites.json
radar-catalog --db radar_catalog.db list --active
radar-catalog --db radar_catalog.db get research-01
```

The example contains eleven fictional research sites and invented equipment
specifications. It contains no surveyed sites or manufacturer performance data.

## Manage records

```bash
# Insert or fully replace a record. Missing optional values reset to defaults.
radar-catalog --db radar_catalog.db put examples/single_site.json

# Modify selected fields, preserving the rest of the record.
radar-catalog --db radar_catalog.db patch research-01 examples/deactivate.json

# Export a JSON array that can be imported into another catalog.
radar-catalog --db radar_catalog.db export > exported_sites.json
radar-catalog --db another_catalog.db import exported_sites.json

# Delete a record by its identifier.
radar-catalog --db another_catalog.db delete research-01
```

Use `radar-catalog --help` or `python -m radar_site_planning --help` for commands.
Place the global `--db` option before the command. Successful commands write JSON
to stdout and return 0; input, lookup, and storage errors go to stderr and return 2.
Commands open or create the SQLite schema. The parent directory must already exist.
An import replaces records with matching IDs; duplicate IDs within one import fail.

## Python API

```python
import json
from pathlib import Path
from radar_site_planning import RadarDatabaseManager

records = json.loads(Path("examples/research_sites.json").read_text())
with RadarDatabaseManager("radar_catalog.db") as catalog:
    catalog.import_radars(records)
    active = catalog.list_active_radars()
    catalog.patch_radar("research-01", {"mast_height_agl": 12.0})
    print(len(active))
```

Records are validated before writing, and each batch is one transaction. Invalid
updates and storage failures leave existing records unchanged. Returned Pydantic
objects do not require an open database session. Timestamps are in UTC. Use
`export` for a re-importable payload without timestamps.

## Data contract

See [the schema and architecture notes](docs/architecture.md) for field names,
units, naming decisions, and storage limitations, and [the implementation
status](docs/implementation-status.md) for the bounded roadmap.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
python -m build
```

GitHub Actions runs these checks on Python 3.11, 3.12, and 3.13. Tests cover
validation, persistence, rollback on storage errors, replacement versus patching,
eleven-record inventory handling, and CLI import/export.

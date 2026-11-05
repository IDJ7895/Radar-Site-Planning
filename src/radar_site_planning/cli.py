"""JSON-oriented catalog CLI with consistent error status codes."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .catalog import RadarDatabaseManager


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a civilian radar site catalog")
    parser.add_argument(
        "--db", default="radar_catalog.db", help="SQLite path (default: %(default)s)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create the catalog schema")
    put = sub.add_parser("put", help="Insert or fully replace one JSON record")
    put.add_argument("file", type=Path)
    batch = sub.add_parser("import", help="Atomically upsert a JSON array of records")
    batch.add_argument("file", type=Path)
    listing = sub.add_parser("list", help="List records as JSON")
    listing.add_argument("--active", action="store_true")
    for name in ("get", "delete", "patch"):
        command = sub.add_parser(name)
        command.add_argument("site_id")
        if name == "patch":
            command.add_argument("file", type=Path, help="JSON object containing changed fields")
    sub.add_parser("export", help="Export re-importable records as a JSON array to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _read_json(args.file) if hasattr(args, "file") else None
        # Reject malformed input before opening or creating a catalog.
        if args.command in {"put", "patch"} and not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        if args.command == "import" and (
            not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload)
        ):
            raise ValueError("Expected a JSON array of objects")
        with RadarDatabaseManager(args.db) as catalog:
            match args.command:
                case "init":
                    result = {"status": "initialized", "database": args.db}
                case "put":
                    result = catalog.add_or_update_radar(payload).model_dump(mode="json")
                case "import":
                    saved = catalog.import_radars(payload)
                    result = {"status": "saved", "count": len(saved)}
                case "get":
                    result = catalog.get_radar(args.site_id).model_dump(mode="json")
                case "list":
                    result = [
                        row.model_dump(mode="json")
                        for row in catalog.list_radars(active_only=args.active)
                    ]
                case "patch":
                    result = catalog.patch_radar(args.site_id, payload).model_dump(mode="json")
                case "delete":
                    catalog.delete_radar(args.site_id)
                    result = {"status": "deleted", "site_id": args.site_id}
                case "export":
                    result = [
                        row.model_dump(mode="json", exclude={"created_at", "updated_at"})
                        for row in catalog.list_radars()
                    ]
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except KeyError as error:
        print(f"Site not found: {error.args[0]}", file=sys.stderr)
    except (ValidationError, ValueError, OSError, SQLAlchemyError) as error:
        print(f"Error: {error}", file=sys.stderr)
    return 2

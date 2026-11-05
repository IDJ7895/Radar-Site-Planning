# Implementation status

This repository starts the catalog portion of the supplied specification. It is
not the full simulation suite described by the attachments. Their verification
matrix describes requested features, not evidence of implemented functionality.

| Reference area | Current status |
| --- | --- |
| GH-01: database and ORM | Implemented for general civilian inventory; Pydantic validation, CRUD, active listing, SQLAlchemy 2, SQLite |
| GH-02: instant RF pre-check | Not implemented; current validation checks input only |
| GH-03–04: elevation and coordinates | Not implemented; catalog coordinates are explicitly WGS84 |
| GH-05–07: physics and terrain masking | Not implemented |
| GH-08–10: simulation, fusion, placement | Not implemented; military network planning and tactical placement optimization are outside scope |
| GH-11–12: GIS outputs and dashboard | Not implemented; JSON export contains inventory records only |
| GH-13: interface | Local CLI implemented; REST API not implemented |
| GH-14: verification | Catalog tests and Python CI configured; no physics benchmark claims |

## Next civilian research increments

1. Add explicit schema migrations before changing a deployed catalog schema.
2. Add survey provenance and measurement uncertainty fields.
3. Add general GIS site inventory import/export with explicit coordinate systems.
4. Design a civilian research UI from reviewed requirements and data samples.

There is no claimed sub-5-ms performance guarantee, terrain data acquisition,
probability-of-detection calculation, or multi-radar simulation in version 0.1.0.

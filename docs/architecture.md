# Catalog architecture and data contract

The supplied PDF and pasted specification are reference requirements. Their
embedded assistant prompts and sample code are not executed. The initial
implementation selects the general inventory work and uses civilian research
examples. No source attachments or actual equipment catalogs are published.

## Public schema

`RadarRecord` uses Pydantic 2. Unknown fields, non-finite numbers, empty names,
and invalid coordinates are rejected. Boolean status must be a JSON boolean.
Positive quantities exclude zero. All timestamps returned by `StoredRadar` use UTC.

| Field | Meaning / constraint | Default |
| --- | --- | --- |
| `site_id` | Unique, case-sensitive string, 1–50 characters | Required |
| `site_name`, `brand`, `model` | Non-empty strings, up to 120 characters | Required |
| `radar_category` | Inventory category label | `RESEARCH` |
| `mobility_type` | `FIXED` or `MOBILE` | `FIXED` |
| `antenna_tech` | `LEGACY_MECHANICAL`, `PESA`, or `FULL_AESA` | `LEGACY_MECHANICAL` |
| `latitude`, `longitude` | Degrees, WGS84; [-90, 90], [-180, 180] | Required |
| `ground_elevation_amsl` | Metres above mean sea level; negative values allowed | 0 |
| `mast_height_agl` | Metres above ground, nonnegative | 10 |
| `instrumented_max_range_km` | Positive manufacturer inventory value, not a prediction | Required |
| `peak_power_kw`, `frequency_ghz` | Positive hardware specification values | Required |
| `pulse_width_us` | Positive pulse duration in microseconds | 10 |
| `antenna_gain_dbi` | Finite gain in dBi | Required |
| `az_beamwidth_deg`, `el_beamwidth_deg` | Positive widths, at most 360 / 180 degrees | 1.4 / 2 |
| `mechanical_tilt_deg`, `electronic_tilt_deg` | Recorded orientation, [-90, 90] degrees | 0 |
| `azimuth_boresight_deg` | Degrees clockwise from north, [0, 360) | 0 |
| `field_of_regard_az_deg` | Degrees, (0, 360] | 360 |
| `noise_figure_db`, `system_loss_db` | Nonnegative hardware specification values | 3.5 / 6 |
| `min_snr_db` | Finite stored threshold, dB | 13 |
| `is_active` | Boolean inventory flag | true |

String identifiers and names have surrounding whitespace removed. JSON numbers
and numeric strings are accepted by Pydantic for numeric fields. Enum values use
the exact spelling above. Measured and manufacturer values are stored without
inferring antenna performance, range, or terrain visibility.

The reference alternates between `radar_id` and `site_id`, `lat` and `latitude`,
and `tech` and `antenna_tech`. This project uses the names in the table; ambiguous
aliases are rejected. Coordinates always use WGS84 degrees, never UTM metres.
`MOBILE` is a general inventory value; the reference's tactical enum values are
not part of this schema.

## Persistence

SQLAlchemy 2 maps each field to an explicit column in `radar_systems`. `site_id`
is the primary key and `is_active` is indexed. `created_at` and `updated_at` are
managed by the repository. SQLite stores UTC timestamps without timezone markers;
the public model restores the UTC offset.

All writes go through Pydantic before persistence. Full replacement resets omitted
optional fields; a patch validates a merged record and cannot rename `site_id`.
Batch import validates all inputs and normalized IDs before starting any writes.
The database transaction rolls back the entire batch if any database write fails.

This is an initial schema with no migration framework. Existing, incompatible
tables are not automatically upgraded. The validation contract applies to writes
through this API; direct SQL can bypass it. SQLite suits local inventory work;
concurrent collaborative editing and optimistic version checks are future work.
The CLI is a local tool and exposes no HTTP service or authentication layer.

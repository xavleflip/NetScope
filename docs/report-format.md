# Report format and imports

New NetScope reports include `schema_version: 1` alongside the existing report
fields. The dashboard can import either version 1 or the current unversioned
legacy shape, such as the two files under `examples/`. Other versions are rejected.

## Import a report

Start the dashboard and use **Import a saved report → Choose a NetScope JSON
report**. Valid data appears under **Imported report**, separate from **Latest
scan**, with independent filtering and a **Download imported JSON report** button.
Removing the upload removes its display. A failed upload leaves the live report
intact and does not keep an older imported file looking like the new upload.

Uploads are limited to **1 MiB (1,048,576 bytes)** and **1,024 result rows**.
The app reads only the limit plus one byte to detect overflow. Files must be
UTF-8 JSON; a UTF-8 BOM is accepted. Malformed JSON, duplicate object keys,
non-finite numbers, excessive nesting, and unsupported fields are rejected.

Importing does not scan, resolve DNS, execute report content, select filesystem
paths, or automatically save a file. Downloading is a separate user action.
Validation checks structure and consistency, not the authenticity of observations:
someone can edit a structurally valid report.

## Version-1 fields

| Field | Required value |
| --- | --- |
| `schema_version` | Integer `1`; absence denotes the current legacy shape. |
| `target` | Exactly `127.0.0.1` or `localhost`. |
| `timestamp` | UTC scan-start timestamp, describing the same instant as `started_at`. |
| `started_at` | UTC scan-start timestamp. |
| `finished_at` | UTC timestamp at or after `started_at`. |
| `duration_seconds` | Finite, non-negative number, excluding booleans. |
| `timeout_seconds` | Number within 0.05–2 seconds, excluding booleans. |
| `summary` | Exact integer counts: `total`, `open`, `closed`, `timeout`, and `error`. |
| `results` | List of at most 1,024 result objects, with unique integer ports 1–65535. |
| `open_ports` | Port/service objects agreeing exactly with the successful results. |

UTC timestamps use `YYYY-MM-DDTHH:MM:SS`, an optional 1–6 digit fractional second,
and either `Z` or `+00:00`. Calendar dates and times must be valid. Normalization
uses the `+00:00` representation. Monotonic duration is not required to equal the
wall-clock timestamp difference exactly.

Every result contains `port`, non-empty UTF-8 `service` text, and one `status`:
`open`, `closed`, `timeout`, or `error`. Error rows must also include an `error`
text field; other rows must not include it. All text must be valid Unicode.

Counts must agree with detailed results. `open_ports` must contain each successful
port once with the same service label, and no other port. Its normalized order
follows `results`. Empty reports are accepted only with empty result/open-port
lists and zero counts. Inconsistent evidence is rejected rather than repaired.

The older prototype containing only `target`, `timestamp`, and `open_ports` lacks
the detailed results needed for this validation and is not the supported legacy
shape. Unknown future fields require an explicitly supported schema version.

## Implementation boundary

- `validation.py` owns the shared target, port, and timeout policy.
- `scanner.py` creates reports and adds the current version while preserving
  its entry points and existing report fields.
- `reports.py` owns `load_report(bytes)` and `validate_report(dict)`. The loader
  enforces the byte limit before parsing; the validator returns an independent
  normalized dictionary without mutating the input. Neither API opens files or sockets.
- `app.py` reads the bounded upload and displays values using ordinary Streamlit
  components, with fixed download filenames and independent live/import controls.

The historical example files are kept unchanged. Normalized downloads add the
version field and canonical UTC timestamps without rewriting the original file.
Service labels remain conventional assignments, and timeouts remain uncertain.

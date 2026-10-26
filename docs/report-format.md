# Report format and imports

New NetScope reports use `schema_version: 2`, adding cancellation status and the
requested port list while preserving existing report fields. The dashboard also
accepts version 1 and the supported unversioned legacy shape, such as the two
files under `examples/`. Other versions are rejected.

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
Use **Save report** to explicitly add validated evidence to
[local history](local-history.md); importing alone never adds a history entry.
Validation checks structure and consistency, not the authenticity of observations:
someone can edit a structurally valid report.

## Shared fields

| Field | Required value |
| --- | --- |
| `schema_version` | Integer `1` or `2`; absence denotes the supported version-1 legacy shape. |
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

## Version-2 cancellation fields

Version 2 also requires `scan_status` (`completed` or `cancelled`) and
`requested_ports`, a list of at most 1,024 unique integer ports within 1–65535.
Every result port must appear in that list. For a completed scan, the requested
and observed port sets must match. Cancelled scans may have zero, some, or all
requested results; their counts still describe only completed probes.

Requested ports without results are **not scanned**, never implicitly closed.
Invalid statuses, missing fields, duplicates, booleans/floats used as ports,
unrequested results, and incomplete scans labelled completed are rejected.
Version-1/unversioned reports cannot include the new fields: they are treated
as completed legacy evidence over their recorded results and retain version 1.
This preserves existing saved payloads and their duplicate identities.

Live/imported/history views visibly label cancelled evidence. Cancelled downloads
include the label in their filename and control; saving uses **Save cancelled
report**. See [progress and cancellation](progress-and-cancellation.md).

## Implementation boundary

- `validation.py` owns the shared target, port, and timeout policy.
- `scanner.py` creates reports and adds the current version while preserving
  its entry points and existing report fields.
- `jobs.py` coordinates finite background scans through run-tagged queues and
  cancellation events; it contains no Streamlit calls.
- `reports.py` owns `load_report(bytes)` and `validate_report(dict)`. The loader
  enforces the byte limit before parsing; the validator returns an independent
  normalized dictionary without mutating the input. Neither API opens files or sockets.
  `scan_details` describes completion status/requested ports uniformly for both versions.
- `app.py` reads the bounded upload and displays values using ordinary Streamlit
  components, with fixed download filenames and independent live/import/history controls.
- `history.py` validates reports before storing them and revalidates on reopen.
  Persistence occurs only through an explicit save; storage adds no scan behavior.
- `comparison.py` reuses report validation to compare two observations without IO.
  Its [comparison download](scan-comparison.md) has a separate format and is not
  an importable scan report.
- `exports.py` reuses validation for JSON and CSV serialization. CSV protects
  spreadsheet text and explicitly labels unscanned ports; JSON retains the
  underlying text. See [CLI and CSV export](cli-and-csv.md).

The historical example files are kept unchanged. Normalized downloads add the
version field and canonical UTC timestamps without rewriting the original file.
Service labels remain conventional assignments, and timeouts remain uncertain.

# Command-line controls and CSV export

Use PowerShell from the project folder. The CLI uses the same scanner, validation,
timeouts, and report construction as the dashboard; no new dependency is required.

```powershell
cd D:\Project\NetScope
.\.venv\Scripts\python.exe scanner.py --help
.\.venv\Scripts\python.exe scanner.py --target localhost --start-port 8000 --end-port 8080 --timeout 0.5
```

Only the exact targets `127.0.0.1` and `localhost` are accepted, both pinned to
IPv4 loopback without DNS. Ports must be within 1–65535, with at most 1,024 ports,
32 concurrent probes, and a 0.05–2 second timeout per connection. Supply both
range endpoints together, or omit both to use the original eight common ports.

## Options and files

| Option | Meaning |
| --- | --- |
| `--target` | `127.0.0.1` by default; `localhost` is also accepted. |
| `--start-port`, `--end-port` | Inclusive port range; both are required together. |
| `--timeout` | Seconds per connection; default `0.5`. |
| `--format` | `json` by default, or `csv`. |
| `--output` | Optional destination file in an existing parent folder. |
| `--overwrite` | Permit replacing the explicit destination; requires `--output`. |
| `--help` | Show limits, examples, and exit codes without scanning. |

Save JSON or CSV with a chosen filename:

```powershell
.\.venv\Scripts\python.exe scanner.py --start-port 8080 --end-port 8080 --output scan-local.json
.\.venv\Scripts\python.exe scanner.py --start-port 8080 --end-port 8080 --format csv --output scan-local.csv
```

An existing destination is refused with exit code 1. Add `--overwrite` only when
you intend to replace it. The extension does not choose the format; `--format`
does. Relative paths are relative to the terminal's current working directory.
The output path comes only from the CLI argument, never from a report field.

With any options, the selected report format is written to stdout and only
`--output` saves a file. Progress and diagnostics go to stderr, so JSON stdout
remains machine-readable. Output is UTF-8, and CSV uses CRLF record separators
without Windows newline doubling. The saved file and stdout contain the same
serialized data. If publishing a file fails, stdout is left empty and diagnostics
describe the failure. A failed stdout pipe can still occur after a file is saved.

For compatibility, running **without any options** scans ports **21, 22, 25, 53,
80, 443, 3306, 8080**, prints JSON, creates `reports/` if needed, and **overwrites
`reports/scan.json`**. That legacy overwrite is intentional. Use explicit options
and `--output` for the new refusal-by-default behavior. Shell redirection is
controlled by your shell and does not use NetScope's file collision protection.

## Cancellation and exit codes

Press **Ctrl+C** to request cooperative cancellation. The handler signals the
same cancellation event used by the scanner; new scheduling stops and active
connections finish within their configured timeout plus coordination overhead.
The scanner joins its workers before the CLI serializes or publishes the result.
Repeated interruption requests do not deliberately kill workers.

Partial JSON uses report schema version 2 with `scan_status: "cancelled"` and
the complete `requested_ports` list. Completed outcomes remain intact; skipped
ports have no fabricated JSON results. CSV explicitly labels those ports
`not scanned`. An interruption before probes begin still yields identifiable
cancelled evidence. A very late Ctrl+C can arrive after a completed report was
finalized; its data can remain completed while the process reports interruption.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed execution, including scans whose outcomes are refused, timeout, or connection errors. |
| `1` | Operational failure, such as a scanner failure, file collision, inaccessible destination, or failed output. |
| `2` | Invalid arguments; validation occurs before sockets are opened. |
| `130` | User interruption after cooperative cleanup, provided output did not fail. |

A write failure takes precedence over the interruption code. JSON partial reports
can be imported and explicitly saved through the dashboard; CLI runs never add
history automatically. See [cancellation semantics](progress-and-cancellation.md).

## Dashboard CSV downloads

Latest scans, imported reports, and selected history entries each have independent
JSON and CSV download controls. Both formats export the full evidence even when
**Show only open ports** filters the table. Cancelled reports keep their visible
warning and `cancelled` labels/filenames in both formats. Comparison downloads
remain JSON in their separate comparison format.

CSV columns have this stable order:

```text
target,started_at,scan_status,requested_count,completed_count,port,service,status,error
```

There is one row per requested port in request order. Completed probes retain
their four possible statuses. Unfinished requested ports have `status=not scanned`
and empty service/error cells. Counts and completion status repeat on every row.
For a report with no requested ports, a single metadata-only row has blank port,
service, status, and error cells so its completion status is still identifiable.
Legacy version-1 reports are treated as completed over their recorded ports.

The standard-library CSV writer quotes commas, quotes, and embedded newlines.
Free-text service/error cells are prefixed with an apostrophe if their first
non-whitespace/control character is `=`, `+`, `-`, or `@`, or if they contain a
leading control/format character. This prevents those exported fields from being
interpreted as spreadsheet formulas. The apostrophe may be visible in some tools.
Underlying JSON evidence and saved history are not changed.

CSV is a presentation export, not the complete JSON archive: it omits some report
metadata and cannot be imported as a NetScope JSON report. Keep JSON for exact
text, complete settings, timestamps, and later import/comparison.

## Atomic writes and privacy

`exports.write_report` writes a temporary file in the destination's directory,
flushes and fsyncs it, closes the handle, then publishes the complete file.
Refusal-by-default uses an atomic hard link: if another writer wins the same
destination, the losing writer gets an error and does not overwrite it. Explicit
overwrite uses `os.replace`. Temporary files are removed in a `finally` block
after ordinary write or publication failures. No existing file is truncated first.

Atomic create requires a filesystem supporting hard links. Unsupported filesystems
fail clearly rather than falling back to a partial or unsafe copy. Overwrite
depends on the filesystem's same-directory atomic replacement support. This
protects visibility and collisions; it is not a backup or a guarantee against
power loss or forced process termination.

Local reports can reveal ports, service labels, timestamps, and error details.
Review them before sharing. Default `reports/`, project-root `scan*.json`, and
`scan*.csv` outputs are ignored by Git; other explicit filenames need your review.
Neither export nor CLI operation deploys anything or sends reports elsewhere.

`cli.py` owns argparse, signal handling, diagnostics, and exit codes. `scanner.py`
remains the entry point and owns probes. `exports.py` owns validated serialization
and atomic writes; UI downloads and CLI output reuse it. See
[test coverage](../tests/README.md) for subprocess, signal, collision, failure,
CSV escaping, and dashboard evidence checks.

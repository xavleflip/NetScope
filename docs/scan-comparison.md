# Compare scan reports

NetScope compares two validated reports by TCP port. `localhost` and `127.0.0.1`
match the same IPv4 loopback address without DNS. Comparing is a transformation
of existing evidence: it does not probe ports, inspect processes, modify source
reports, or save history.

## Use the dashboard

1. Start NetScope as described in the [README](../README.md).
2. Under **Compare reports**, choose **Saved history** or **JSON files**.
3. Select two saved entries, or upload two NetScope report files. Each upload
   has the usual 1 MiB / 1,024-result limit and passes the shared
   [report validator](report-format.md). Saving uploads to history is optional.
4. Choose the report with the earlier UTC scan start as **Earlier baseline** and
   the other as **Later observation**. Reversed dates show an error asking you to
   swap the reports; the app does not silently exchange your selections.
5. Review the input settings, coverage, summary, and complete port table. Use
   **Download comparison JSON** for a portable copy of the comparison.

You can compare an entry with itself. Equal start times are explicitly noted;
they do not establish an earlier/later order. Overlapping scan windows also
produce a note because individual port probes may have occurred in a different
order. Imported timestamps and observations are not authenticated.

Missing, invalid, or removed inputs hide the comparison and its download. A
storage failure shows an error while keeping saved data intact. The latest scan
and ordinary report import remain independent of comparison controls.

## Interpret the evidence

The table includes the union of ports, sorted numerically. It shows before/after
statuses, conventional service labels, error details, and an interpretation.

| Before → after | Meaning |
| --- | --- |
| `closed → open` | An earlier connection was refused; the later connection succeeded. |
| `open → closed` | A connection succeeded before; the later connection was explicitly refused. |
| `open → timeout` | Uncertain. A timeout does not prove that the service stopped. |
| Any transition involving `timeout` or `error` | Uncertain; no conclusion that a service started or stopped. |
| The same status in both reports | Status unchanged; timeouts and errors remain uncertain. |
| A port absent from either report | **not scanned** on that side; no comparable status transition. |

These are observations of connection attempts, not continuous service monitoring.
An explicit refusal does not establish why a service is unavailable. Service
labels are conventional port assignments. A changed label is shown separately
and does not identify a change of software or a vulnerability.

The input table preserves each target spelling, start/end times, duration,
timeout setting, total ports, and outcome counts. Coverage shows shared ports
and ports checked in only one report. Different coverage and timeout settings
produce warnings; NetScope does not silently discard unmatched ports or adjust
measurements to make them agree.

The summary counts mean:

- **Status changed**: a shared port has different statuses.
- **Status unchanged**: a shared port has the same status, even if its service
  label or error detail changed.
- **Missing coverage**: a port is absent from one report.
- **Uncertain outcomes**: at least one recorded status is `timeout` or `error`.
  This count overlaps the other categories; it is not an additional partition.

Changed, unchanged, and missing-coverage counts sum to the total union of ports.
Service-label changes have a separate count and flag. Missing coverage does not
count as a status change, including when the only observed result is open.

## Example and download format

Upload `examples/localhost-open.json` as the baseline and
`examples/localhost-stopped.json` as the later observation. Port **8080** shows
**open → timeout**, with `change: "changed"` and `uncertain: true`. The example's
filename is not evidence that a timeout proves a server stopped.

The fixed download filename is `comparison.json`. Its top-level fields are:

| Field | Contents |
| --- | --- |
| `comparison_version` | Integer `1`, independent of the scan-report schema version. |
| `target` | Canonical matching address, `127.0.0.1`. |
| `baseline`, `observation` | Each input's target, start/end times, duration, timeout, and summary. |
| `coverage` | Sorted `shared`, `baseline_only`, and `observation_only` port lists. |
| `timeouts_differ` | Whether connection timeout settings differ. |
| `notes` | Equal/overlapping time, coverage, or timeout-setting explanations. |
| `summary` | Total, status-change, unchanged, missing, uncertain, and label-change counts. |
| `results` | Every union port with before/after statuses, labels, errors, flags, and interpretation. |

Missing statuses use the literal string `not scanned`; missing service/error
values use JSON `null`. A row's `change` is `changed`, `unchanged`, or `not scanned`.
The summary's missing-coverage key is `not_scanned`. A comparison may contain up
to 2,048 rows when two maximum-size reports have disjoint coverage.

The download contains the complete comparison displayed by the dashboard.
Comparison downloads are a separate format and cannot be imported as scan
reports or saved to report history. Retain the original report JSON files if
you want to compare other observations later. Like reports, comparison exports
can reveal local service details; review them before sharing.

## Implementation and checks

`comparison.py` owns the pure `compare_reports(baseline, observation)` function.
It reuses `reports.validate_report` at its public boundary, returns independent
JSON-compatible data, and leaves inputs untouched. The app owns source selection,
bounded upload reads, display, and downloads. No new dependency was added.

Tests cover all 16 status transitions, the supplied examples, explicit refusal,
disjoint and partial coverage, empty/identical reports, target aliases, differing
settings, label/error-detail changes, chronology, purity, and dashboard exports.
See [the test guide](../tests/README.md).

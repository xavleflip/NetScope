# Scan progress and cancellation

NetScope runs one active scan per dashboard session. Its progress bar shows
completed probes out of requested ports. A probe counts as completed whether its
outcome is open, an explicit refusal, a timeout, or another connection error.

## Use the dashboard

1. Choose the localhost target, ports, and timeout, then click **Start Scan**.
2. Watch **Scanning: completed/total probes completed**. A very quick scan may
   finish before the progress bar or cancel button is visible.
3. To stop, click **Cancel scan**. The display changes to **Cancelling scan**;
   new work stops, and existing connection attempts finish with their configured
   timeout. Cancellation does not forcibly terminate threads or close sockets
   from a different thread.
4. Wait for cleanup. **Start Scan** stays disabled until the session's job and
   all its probe workers have finished. Active probes normally finish within
   their per-connection timeout, plus coordination and operating-system overhead.
5. Review the **cancelled** result and its completed/requested counts. Download
   the cancelled JSON, or use **Save cancelled report** to retain it in history.

The active request is fixed at submission. Form edits do not change that job;
review the form before starting the next scan. Other sessions have independent
jobs and cancellation controls. Imports, history, and comparisons remain usable.

A cancellation observed before the report is finalized keeps the `cancelled`
label, even if every requested probe has already completed. A cancellation that
arrives after completion cannot retroactively change a completed report. Progress
reaching 100% does not by itself establish which side of this race won.

Closing the browser does not leave a permanent monitoring job. The finite scan
finishes and joins its workers without waiting for UI messages to be consumed.
It does not save automatically, and its session result may be lost when the
session is discarded. Stop the dashboard normally with **Ctrl+C** when finished.

## Version-2 reports

New scans preserve the original report fields and add:

| Field | Meaning |
| --- | --- |
| `schema_version: 2` | Cancellation-aware report format. |
| `scan_status` | `completed` or `cancelled`; running jobs are not exported as finished reports. |
| `requested_ports` | Ordered list of unique requested ports, up to 1,024. |

`results`, `summary`, and `open_ports` describe only completed probes. Ports in
`requested_ports` without a result are **not scanned**. No synthetic closed,
timeout, or error result is created for skipped work. A completed report must
have a result for every requested port. A cancelled report can have none, some,
or all of them, while retaining its cancelled status.

Cancelled live, imported, and saved reports show a visible warning. Their download
labels and filenames include `cancelled`, and their save button says **Save
cancelled report**. Filtering affects only the displayed table; exports retain
all completed outcomes and the full requested-port list.

Version-1 and supported unversioned reports remain readable and retain their
version-1 payload shape. They are treated as completed legacy scans over their
recorded ports; an older file cannot establish an unrecorded intended range.
`reports.scan_details` supplies uniform status/coverage metadata to presentation
and comparison without rewriting legacy reports. See
[the report format](report-format.md) for validation rules.

History stores both versions using its existing SQLite schema version 1, with no
database migration or payload rewrite. Reopening revalidates the report and
preserves its cancellation status. Comparisons include the union of requested
ports, label missing results **not scanned**, and warn about cancelled inputs.
See [local history](local-history.md) and [comparisons](scan-comparison.md).

## Scanner and job ownership

`scanner.scan_target` remains synchronous for direct callers. It also accepts a
standard-library cancellation event and an optional progress callback:

```python
from threading import Event
from scanner import scan_target

cancel = Event()  # Another control thread may call cancel.set().
report = scan_target(
    "127.0.0.1", start_port=1, end_port=128, timeout=0.5,
    cancel_event=cancel,
    on_progress=lambda completed, total: print(f"{completed}/{total}"),
)
```

The scanner keeps at most 32 futures in flight, stops refilling after cancellation,
cancels queued futures, and skips probes whose workers have not started. Active
socket attempts finish using their normal timeout. Results retain requested-port
order, even when probes finish out of order. Success, cancellation, and unexpected
failures all join the executor before returning or raising.

Progress callbacks run on the scanner caller's thread, starting at `(0, total)`
and increasing once per completed probe. A callback failure also cleans up the
workers before propagating. Keep callbacks quick and avoid Streamlit calls there.

`jobs.ScanJob` validates before launching a non-daemon coordinator thread. It
passes progress and terminal messages through a per-job queue, each tagged with
a unique run ID. There are at most 1,026 messages per job and no dependency on a
browser consuming them. Stale run IDs are ignored, and cancellation requires the
matching ID. The coordinator contains no Streamlit calls or global job registry.

`app.py` owns session state and uses a native Streamlit fragment to poll progress
every 0.2 seconds while a job exists. It publishes the report only after joining
the finished coordinator, and reenables submission through a full rerun. An
unexpected job failure displays an error with no misleading successful report;
ordinary socket errors remain recorded connection outcomes.

## Verification

Tests coordinate blocked probes with events rather than sleeps. They cover
cancellation before work, while sockets are active, with queued work, and at
completion; bounded submission, monotonic progress, ordered partial results,
socket closure, and thread cleanup on failure; two-session isolation and stale
messages; and finite completion without a UI consumer. AppTest verifies progress,
cancel/disabled controls, cancelled downloads and saves, import/history/comparison
compatibility, and recovery after a failed job. All storage tests use temporary
databases. See [the test guide](../tests/README.md).

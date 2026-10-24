# NetScope tests

## Setup and run

Use Python 3.11–3.14. In PowerShell, from the project directory:

```powershell
cd D:\Project\NetScope
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Create `.venv` first with `python -m venv .venv` if it does not exist. Streamlit
is the dashboard's existing dependency and supplies `streamlit.testing.v1.AppTest`;
the test runner is Python's built-in `unittest`. No separate test package is needed.
Dashboard tests require Streamlit to be installed; they are not silently skipped
when it is missing.

The requirements file is shared by the application and tests. It permits Streamlit
1.66 patch releases starting at 1.66.1; it does not pin every transitive dependency.

## Coverage

- `test_localhost_restrictions.py`: both scanner entry points, rejected targets
  before socket creation, DNS-free loopback connections, timeout configuration,
  socket cleanup, real local listeners, and dashboard loopback configuration.
- `test_scan_results.py`: success/refusal/timeout/error classification, Windows
  error codes, socket-creation failures, unknown services, report counts and
  timestamps, monotonic duration, JSON round-trip, boolean helper compatibility,
  and command-line export into a temporary directory.
- `test_scan_limits.py`: integer port and range validation, inclusive boundaries,
  the 1,024-port cap, finite timeout bounds, timeout forwarding, an explicit-range
  local scan, and event-controlled proof of the 32-connection cap and cleanup.
- `test_dashboard.py`: initial screen without scanning, a real local scan,
  status counts and table, JSON download control and payload, empty open-port
  results, target/range rejection, failed-scan report clearing, and report retention
  across filtering, form edits, and reruns without another scan. Downloads remain
  complete when the table is filtered.
- `test_reports.py`: current example compatibility, schema versions, byte/row
  limits, malformed/duplicate JSON, invalid Unicode, numeric and timestamp bounds,
  result/count/open-port consistency, mutation isolation, and a real new-scan
  round-trip. Parser tests verify that loading opens neither files nor sockets.
- `test_report_import.py`: native AppTest uploads, independent live/import controls,
  invalid/oversized files, empty reports, normalized downloads, and import/filter
  operations that never invoke the scanner. Streamlit's internal event-loop
  socket pairs are left intact while the scanner probe boundary is mocked.

## Safety and cleanup

Real integration tests bind listeners to `127.0.0.1` using port `0`, allowing the
operating system to select an available port. Context managers close the
listeners even if an assertion fails. They need no administrator privileges or
pre-existing services. Failure scenarios use mocks, and command-line reports
are written in a temporary directory that is cleaned up after the test.

No test connects to an external host. Unsupported target strings are tested
through validation and mocked probes only. AppTest runs the dashboard in process;
it does not launch a publicly reachable dashboard server. It verifies the download
control and JSON supplied to Streamlit, rather than driving a browser save dialog.
Streamlit may log a harmless missing `ScriptRunContext` warning in its testing mode.

Concurrency tests coordinate workers with events rather than timing sleeps and
verify every simulated socket is closed across all four outcomes. Outcomes are
tied to port numbers so tests do not depend on thread scheduling order.

# Part 2: Make scan results accurate

## Goal

Describe connection outcomes accurately and produce consistent JSON reports
without breaking the existing `open_ports` field.

## Tasks

- [x] Distinguish `open`, `closed`, `timeout`, and `error`.
- [x] Report `closed` only when the connection is explicitly refused.
- [x] Include scan duration, UTC timestamps, and summary counts.
- [x] Include a result for every checked port.
- [x] Explain that service labels are conventional assignments, not detected software.
- [x] Preserve the existing `open_ports` field when extending reports.
- [x] Add tests for outcome classification and report consistency.

## Completion check

Every checked port has a result. Status counts sum to the number of checked
ports, and `open_ports` agrees with the successful results. Reports serialize
to JSON, and timeouts are not presented as proof that a port is closed.

## Verification

Test success, refusal, timeout, and other socket failures with controlled
outcomes. Round-trip the report through JSON and check timestamps, counts,
and compatibility with the existing dashboard and command-line export.

### Completed verification

- All 15 tests pass with `.venv\Scripts\python.exe -m unittest discover -s tests -v`,
  including the seven Plan 1 safety tests.
- Controlled socket outcomes cover success, explicit refusal, timeout, and other
  errors, including Windows error codes and socket-creation failures.
- Reports round-trip through JSON; counts, port coverage, UTC timestamps,
  monotonic duration, and the original `open_ports` row shape are checked.
- The original boolean `scan_port()` behavior is preserved and tested.
- Command-line execution prints the same JSON that it saves to `reports/scan.json`;
  the test uses a temporary directory and mocked connections.
- A Streamlit testing run against a real local listener verifies the open-port
  table, count, and full JSON download. It used system Python's installed
  Streamlit 1.66.1; the project virtual environment still needs Streamlit installed
  as described in the README.
- No external hosts were contacted. Only this plan's checklist was completed;
  later dashboard controls and richer presentation remain in Part 4.

[Back to plan index](README.md) · [Next: Automated tests](03-automated-tests.md)

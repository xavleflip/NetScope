# Part 3: Add automated tests

## Goal

Provide repeatable proof that the scanner, reports, and dashboard work safely.
Add tests during Parts 1 and 2, then complete coverage of the full workflow here.

## Tasks

- [ ] Test a real local listening socket using an operating-system-assigned port.
- [ ] Test rejected targets without making external connections.
- [ ] Test timeouts, connection refusals, and other socket errors.
- [ ] Verify sockets are closed on success and failure.
- [ ] Verify JSON reports, summary counts, and the existing `open_ports` field.
- [ ] Test the dashboard scan, result display, and download control.
- [ ] Document the command used to run the suite.

## Completion check

Tests pass without contacting external hosts or requiring administrator access.
They clean up their local sockets and do not depend on a service already running
on a fixed port.

## Verification

Run the complete suite from the project directory. Use real sockets for local
integration and mocks for deterministic timeout/error scenarios. Extend these
tests when Part 4 adds dashboard controls and concurrency.

[Back to plan index](README.md) · [Next: Dashboard](04-dashboard.md)

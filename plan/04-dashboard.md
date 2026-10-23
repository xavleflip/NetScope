# Part 4: Improve the dashboard

## Goal

Let users choose a bounded local scan, inspect accurate results, and download
the same report after dashboard interactions.

## Tasks

- [ ] Keep results and downloads available across interactions using session state.
- [ ] Add validated port-range and timeout controls.
- [ ] Validate an ascending range within ports 1–65535.
- [ ] Limit each scan to 1,024 ports and cap concurrent connections.
- [ ] Enforce limits in the scanner as well as the interface.
- [ ] Show status counts, clear validation messages, and an open-port filter.
- [ ] Keep downloads complete even when the displayed table is filtered.
- [ ] Ensure a failed new scan cannot make an older report look like its result.
- [ ] Extend tests for limits, result retention, filtering, and downloads.

## Completion check

Users can scan, inspect, filter, and download consistent results. Invalid input
creates no connections. Downloads contain every scan result, and results remain
available across normal dashboard reruns.

## Verification

Exercise the workflow with an authorized local listener. Check invalid ranges,
oversized scans, and invalid timeouts. Verify bounded worker/socket usage and
that a filter change does not trigger another scan.

[Back to plan index](README.md) · [Next: Installation](05-installation.md)

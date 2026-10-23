# Part 1: Strengthen localhost restrictions

## Goal

Ensure every supported scanning path connects only to localhost, and keep the
dashboard accessible only from the local machine.

## Tasks

- [x] Enforce validation wherever sockets are opened, including `scan_port()`.
- [x] Map `localhost` directly to `127.0.0.1` without DNS.
- [x] Reject unsupported targets before creating a socket.
- [x] Add Streamlit configuration that binds the dashboard to loopback.
- [x] Add regression tests alongside these changes.

## Completion check

Unsupported targets are rejected before any connection attempt, including when
the lower-level scanner helper is called directly. Starting the dashboard from
the project directory binds it to loopback by default.

## Verification

Use mocked sockets to prove rejected targets create no connections. Use an
authorized local listener to verify accepted targets work. Never test rejection
by actually connecting to an external host.

### Completed verification

- Seven regression tests pass using `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
- Real local listeners verify both accepted names and both scanner entry points.
- Mocked socket and resolver calls verify rejected targets create no connections
  and accepted names require no hostname resolution.
- A temporary Streamlit server started without an address override responds to
  a loopback health check. The operating system reports its listening address
  as `127.0.0.1` only. The temporary server was stopped after verification.
- Dashboard startup used system Python with Streamlit 1.66.1 because the project
  virtual environment does not currently have Streamlit installed. Install it
  there using the README instructions before launching with that environment.

[Back to plan index](README.md) · [Next: Scan results](02-scan-results.md)

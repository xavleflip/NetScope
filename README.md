# NetScope

A beginner cybersecurity portfolio project that checks common TCP ports on
localhost, displays open ports in a Streamlit dashboard, and exports JSON reports.

## Current features

- Scan `127.0.0.1` or `localhost` through the dashboard or `scan_target()`.
- Check TCP ports **21, 22, 25, 53, 80, 443, 3306, and 8080**.
- Use a 0.5-second connection timeout per port, scanning sequentially.
- Display open ports with conventional service labels from the operating system.
- Download a JSON report from the dashboard.
- Run the scanner directly to print a report and save `reports/scan.json`.

## Installation

Use Python 3.11 or newer. Open PowerShell in this folder:

```powershell
cd D:\Project\NetScope
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install streamlit
```

If `.venv` already exists, reuse it and run only the installation command.
The scanner uses Python's standard library; Streamlit is needed for the dashboard.

## Run the dashboard

From the project folder:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open <http://127.0.0.1:8501>, keep the target as `127.0.0.1` or `localhost`,
and click **Start Scan**. Use **Download JSON Report** after the scan completes.
The explicit server address keeps the dashboard accessible only through loopback.
Do not expose it through a public server, proxy, or tunnel.

## Run the scanner directly

```powershell
.\.venv\Scripts\python.exe scanner.py
```

This scans `127.0.0.1`, prints JSON, and creates or overwrites
`reports/scan.json` relative to the current working directory. The dashboard
offers a browser download instead of automatically saving that file.

## Try a controlled local example

In another terminal, start a temporary server from an empty folder:

```powershell
python -m http.server 8080 --bind 127.0.0.1
```

Scan `127.0.0.1` in NetScope. Port 8080 should appear in the results. Stop the
temporary server with Ctrl+C and scan again; it should disappear unless another
process is listening there. Use an empty folder because the HTTP server serves
files from its working directory.

## Understanding the report

Reports contain:

| Field | Meaning |
| --- | --- |
| `target` | Requested localhost target. |
| `timestamp` | UTC timestamp recorded before scanning. |
| `open_ports` | List of successful TCP connections, with `port` and `service`. |

An open port means a connection succeeded at scan time. It does not establish
that the service is vulnerable. Service labels describe conventional port
assignments, not detected software, and can vary by operating system.

This version omits unsuccessful connections from the report. It does **not**
distinguish closed ports, timeouts, and other socket errors. An empty result
means no successful connection was observed on the eight checked ports; it does
not mean the computer has no listening services.

## Project files

```text
app.py              Streamlit dashboard and JSON download
scanner.py          TCP scanner and command-line report export
reports/scan.json   Generated report when running scanner.py directly
README.md           Setup, usage, restrictions, and roadmap
```

## Security restrictions and scope

Use only on a computer you own or are explicitly authorized to test. A shared
or employer-owned machine still requires permission. No administrator privileges
are required. Connections can appear in service logs.

`scan_target()` accepts only the exact strings `127.0.0.1` and `localhost`.
However, the lower-level `scan_port()` helper does not validate targets, and
`localhost` is resolved by the operating system. Call `scan_target()` as the
supported entry point and use `127.0.0.1` for an explicit IPv4 loopback target.
Do not use the helper to scan external or unauthorized hosts.

The project performs TCP connections without sending application payloads. It
does not perform UDP scans, banner detection, vulnerability checks, exploitation,
or password guessing. In a container or remote environment, localhost refers to
that environment, not necessarily the computer displaying your browser.

Reports can reveal local services. Review them before sharing or committing
them to source control.

## Troubleshooting

- **Streamlit is missing:** install it using the same `.venv` Python executable
  used to start the dashboard.
- **No ports appear:** run the controlled server on port 8080 and try again.
- **Target rejected:** enter exactly `127.0.0.1` or `localhost`.
- **Dashboard port occupied:** append `--server.port 8502` and open
  <http://127.0.0.1:8502>.
- **Download disappears:** this version renders results only during the scan
  button's run; run the scan again if another interaction clears the results.

## Next-step roadmap

1. Enforce loopback validation at the socket boundary and pin `localhost` to a
   loopback literal without DNS resolution.
2. Add automated tests with a real local listener, rejected targets, and timeouts.
3. Add `requirements.txt` and `.gitignore` for reproducible setup and clean commits.
4. Report closed, timeout, and error states separately, with scan duration.
5. Add validated port-range selection and retain results in Streamlit session state.

The current folder has no automated test suite. The controlled example above is
a manual smoke check. For a portfolio demonstration, show the local server's
open/closed transition, a reviewed JSON report, and explain the limits of TCP
reachability and conventional service labels.

# NetScope
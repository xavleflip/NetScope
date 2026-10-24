# NetScope

## What this project does

NetScope is a beginner cybersecurity project built with Python and Streamlit.
It checks TCP ports on your own computer, shows connection outcomes with conventional
service labels, and lets you download the results as a JSON report or explicitly
save them in local history for later use.

In the dashboard, choose an inclusive range within ports **1–65535**, up to
**1,024 ports per scan**, and a **0.05–2 second** timeout per connection.
Up to **32 connections** run concurrently per scan. It accepts only `127.0.0.1`
or `localhost`. An open port means a connection succeeded; service labels are
hints and do not identify the software running.

JSON reports include every checked port as `open`, `closed` (connection refused),
`timeout`, or `error`, plus UTC start/end timestamps, duration, and summary counts.
Timeouts do not establish whether a port is closed. The dashboard shows status
counts and all results, with an open-port filter. The download always contains
the full report and the compatible `open_ports` list.

New reports include `schema_version: 1` alongside `target`, `timestamp`, `started_at`, `finished_at`,
`duration_seconds`, `timeout_seconds`, `summary`, `results`, and `open_ports`.
Each result has `port`, `service`, `status`, and an `error` message when applicable.

Use only on a computer you own or are authorized to test. This project checks TCP
connections; it does not detect vulnerabilities or scan external hosts. Review
reports before sharing them, and keep the dashboard bound to localhost.

## Install

Use Python **3.11–3.14**. Development verification uses Windows with Python 3.14.7;
other Python/platform combinations have not yet been verified. Open PowerShell:

```powershell
cd D:\Project\NetScope
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `.venv` already exists, skip the command that creates it.
Use the virtual environment's Python for installation, launch, and tests; activation
is optional. `requirements.txt` supports Streamlit 1.66 patch releases starting at
1.66.1. It is a compatible version range, not an exact lock of all dependencies.

Verify the installation:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite uses Python's built-in test runner and Streamlit's testing API; no
separate testing package is needed. See [the test guide](tests/README.md) for details.

## Start

From the project folder, run:

```powershell
cd D:\Project\NetScope
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

1. Open <http://127.0.0.1:8501> in your browser.
2. Enter `127.0.0.1` or `localhost` as the target.
3. Choose the start/end ports and timeout, then click **Start Scan**.
4. Review the status counts and table, or select **Show only open ports**.
5. Click **Download JSON Report** to save the full results.

To inspect an existing report, use **Import a saved report** and choose a JSON
file up to **1 MiB** with at most **1,024 result rows**. Current version-1 and
unversioned example reports are accepted. Imported evidence appears separately
from your latest scan; importing never starts a scan or automatically saves a file.
Invalid uploads leave the live report intact. See [the report format](docs/report-format.md)
for validation rules and compatibility. Validation does not prove a report is authentic.

Click **Save report** on a scan or import to keep it after restarting the app.
Under **Local history**, select a saved report to review or download it. Saving
the same normalized report again reuses its existing entry. To remove one, click
**Delete selected report** and confirm the displayed report ID.

History lives in `data/netscope.db` inside this project folder. It is local,
unencrypted, and ignored by Git; it may reveal service information. Scanning and
importing alone do not save history. See [local history](docs/local-history.md)
for backup, restore, deletion, and storage error guidance.

Run from the project folder so `.streamlit/config.toml` is loaded. Its default
address is `127.0.0.1`; the launch command also explicitly sets loopback. If port
8501 is busy, append `--server.port 8502` and open <http://127.0.0.1:8502>.

Results stay available when you change the filter or edit the form. Click
**Start Scan** again to replace them. A failed new scan clears the previous
report. Connection timeouts apply per port; the full scan can take longer.

Press **Ctrl+C** in PowerShell to stop the dashboard.

To run the scanner without the dashboard:

```powershell
.\.venv\Scripts\python.exe scanner.py
```

This checks the original common ports **21, 22, 25, 53, 80, 443, 3306, and 8080**,
prints the results, and creates or overwrites `reports/scan.json`.

## Try the portfolio demonstration

Start the dashboard as above. In another PowerShell terminal, create an empty
temporary folder and start a local HTTP server:

```powershell
cd D:\Project\NetScope
$demoPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$demoFolder = Join-Path ([System.IO.Path]::GetTempPath()) ("netscope-demo-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $demoFolder | Out-Null
Set-Location -LiteralPath $demoFolder
& $demoPython -m http.server 8080 --bind 127.0.0.1
```

1. Scan `127.0.0.1`, using port `8080` for both endpoints and timeout `2` seconds.
2. Download the report while the server is running; expect `open`.
3. Stop the HTTP server with **Ctrl+C**, wait for the prompt, and scan again.
4. Download the new report. It may show `closed` or `timeout`; a timeout alone
   does not prove the port is closed. Stop the dashboard when finished.

If 8080 is occupied, use another available port in both the command and dashboard.
Our recorded Windows demonstration changed from **open to timeout**. See the
[screenshots, reviewed reports, architecture, and lessons](docs/portfolio-demo.md).

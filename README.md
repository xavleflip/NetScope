# NetScope

## What this project does

NetScope is a beginner cybersecurity project built with Python and Streamlit.
It checks TCP ports on your own computer, shows connection outcomes with conventional
service labels, and lets you download the results as a JSON report.

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

## Install

Install Python 3.11 or newer, then open PowerShell and run:

```powershell
cd D:\Project\NetScope
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install streamlit
```

If `.venv` already exists, skip the command that creates it.

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

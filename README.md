# NetScope

## What this project does

NetScope is a beginner cybersecurity project built with Python and Streamlit.
It checks common TCP ports on your own computer, shows open ports with conventional
service labels, and lets you download the results as a JSON report.

The scanner checks ports **21, 22, 25, 53, 80, 443, 3306, and 8080**. It accepts
only `127.0.0.1` or `localhost`. An open port means a connection succeeded;
service labels are hints and do not identify the software running.

JSON reports include every checked port as `open`, `closed` (connection refused),
`timeout`, or `error`, plus UTC start/end timestamps, duration, and summary counts.
Timeouts do not establish whether a port is closed. The dashboard shows open ports;
the download contains the full report and the compatible `open_ports` list.

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
3. Click **Start Scan** to see open ports.
4. Click **Download JSON Report** to save the results.

Press **Ctrl+C** in PowerShell to stop the dashboard.

To run the scanner without the dashboard:

```powershell
.\.venv\Scripts\python.exe scanner.py
```

This prints the results and creates or overwrites `reports/scan.json`.

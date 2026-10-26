"""Terminal controls for the same localhost scanner used by the dashboard."""

import argparse
from pathlib import Path
import signal
import sys
from threading import Event

from exports import serialize_report, write_report
import scanner


def _parser():
    return argparse.ArgumentParser(
        description="NetScope localhost-only TCP scanner. No DNS or external targets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Limits: ports 1-65535, at most 1024 ports and 32 concurrent probes;
timeout 0.05-2 seconds per connection. Both range endpoints are required.

Examples (run with your virtual environment's Python):
  python scanner.py
  python scanner.py --target localhost --start-port 8000 --end-port 8080 --timeout 0.5
  python scanner.py --start-port 8080 --end-port 8080 --format csv --output scan-local.csv
  python scanner.py --start-port 8080 --end-port 8080 --output scan-local.json --overwrite

No options: scan the original eight common ports, print JSON, and overwrite
reports/scan.json. With options: output goes to stdout and only --output saves
a file. Explicit output paths refuse existing files unless --overwrite is used.
Output parents must exist. Progress/diagnostics go to stderr. Ctrl+C requests
cooperative cancellation and retains cancelled evidence, including skipped ports.
Exit codes: 0 completed, 1 operational failure, 2 invalid arguments, 130 interrupted.
Reports may reveal local service information. Review them before sharing.""",
    )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    parser.add_argument("--target", default="127.0.0.1", help="127.0.0.1 or localhost only")
    parser.add_argument("--start-port", type=int, help="inclusive first port")
    parser.add_argument("--end-port", type=int, help="inclusive last port")
    parser.add_argument("--timeout", type=float, default=scanner.DEFAULT_TIMEOUT,
                        help="connection timeout in seconds (default: 0.5)")
    parser.add_argument("--format", choices=("json", "csv"), default="json", help="stdout/file format (default: json)")
    parser.add_argument("--output", type=Path, help="optional destination file; parent must exist")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing the explicit output file")
    args = parser.parse_args(argv)
    if (args.start_port is None) != (args.end_port is None):
        parser.error("--start-port and --end-port must be supplied together")
    if args.overwrite and args.output is None:
        parser.error("--overwrite requires --output")
    try:
        scanner.validate_scan_request(args.target, start_port=args.start_port,
                                      end_port=args.end_port, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))

    cancel = Event()

    def interrupt(signum, frame):
        # No IO or exceptions in a signal handler: active probes must finish.
        cancel.set()

    def progress(completed, total):
        if completed == 0 or completed == total or completed % scanner.MAX_WORKERS == 0:
            print(f"Progress: {completed}/{total} probes completed", file=sys.stderr, flush=True)

    previous_handler = signal.signal(signal.SIGINT, interrupt)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="")
        report = scanner.scan_target(args.target, start_port=args.start_port, end_port=args.end_port,
                                     timeout=args.timeout, cancel_event=cancel, on_progress=progress)
        text = serialize_report(report, args.format)
        destination = args.output
        if not argv:
            Path("reports").mkdir(exist_ok=True)
            destination = Path("reports/scan.json")
        if destination is not None:
            write_report(destination, text, overwrite=args.overwrite or not argv)
            print(f"Saved report: {destination}", file=sys.stderr)
        sys.stdout.write(text)
        sys.stdout.flush()
        count = report["summary"]["total"]
        print(f"Scan {report['scan_status']}: {count}/{len(report['requested_ports'])} probes completed.",
              file=sys.stderr)
        return 130 if cancel.is_set() else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"NetScope failed: {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)

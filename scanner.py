
import socket
import json
from datetime import datetime, timezone
from pathlib import Path

PORTS = [21, 22, 25, 53, 80, 443, 3306, 8080]

def scan_port(target, port):
    try:
        with socket.create_connection((target, port), timeout=0.5):
            return True
    except (OSError, TimeoutError):
        return False

def scan_target(target="127.0.0.1"):
    # This beginner version is restricted to loopback.
    if target not in ("127.0.0.1", "localhost"):
        raise ValueError("Localhost scanning only")

    results = {
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "open_ports": []
    }

    for port in PORTS:
        if scan_port(target, port):
            try:
                service = socket.getservbyport(port, "tcp")
            except OSError:
                service = "unknown"

            results["open_ports"].append({
                "port": port,
                "service": service
            })

    return results

if __name__ == "__main__":
    result = scan_target()
    print(json.dumps(result, indent=2))

    Path("reports").mkdir(exist_ok=True)
    Path("reports/scan.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )

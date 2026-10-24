"""Shared localhost, port, and timeout rules for scans and report imports."""

MAX_PORTS = 1024
MIN_TIMEOUT = 0.05
MAX_TIMEOUT = 2.0


def loopback_address(target):
    if not isinstance(target, str) or target not in ("127.0.0.1", "localhost"):
        raise ValueError("Localhost scanning only")
    return "127.0.0.1"


def validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Ports must be integers within 1–65535.")


def validate_timeout(timeout):
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT):
        raise ValueError(f"Timeout must be {MIN_TIMEOUT}–{MAX_TIMEOUT} seconds.")

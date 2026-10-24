import socket
from threading import Event, Lock, Thread
import unittest
from unittest.mock import patch

from scanner import MAX_PORTS, MAX_WORKERS, scan_port, scan_target


class ScanLimitTests(unittest.TestCase):
    def test_invalid_ranges_are_rejected_before_sockets(self):
        cases = (
            (0, 1), (1, 65536), (10, 9), (1, MAX_PORTS + 1),
            (True, 5), (1.0, 5), ("1", 5), (1, False), (1, 5.0),
            (None, 5), (1, None),
        )
        with patch("scanner.socket.socket") as factory:
            for start, end in cases:
                with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                    scan_target(start_port=start, end_port=end)
            factory.assert_not_called()

    def test_direct_helper_rejects_invalid_ports_before_sockets(self):
        with patch("scanner.socket.socket") as factory:
            for port in (0, 65536, True, 1.0, "80", None):
                with self.subTest(port=port), self.assertRaises(ValueError):
                    scan_port("localhost", port)
            factory.assert_not_called()

    def test_invalid_timeouts_are_rejected_by_both_entry_points(self):
        with patch("scanner.socket.socket") as factory:
            for timeout in (0, -1, 0.049, 2.001, True, None, "0.5", float("nan"), float("inf")):
                for entry_point in (scan_port, scan_target):
                    with self.subTest(timeout=timeout, entry_point=entry_point.__name__), self.assertRaises(ValueError):
                        if entry_point is scan_port:
                            entry_point("localhost", 80, timeout=timeout)
                        else:
                            entry_point(start_port=80, end_port=80, timeout=timeout)
            factory.assert_not_called()

    def test_timeout_boundaries_reach_socket(self):
        for timeout in (0.05, 2.0):
            with self.subTest(timeout=timeout), patch("scanner.socket.socket") as factory:
                report = scan_target(start_port=80, end_port=80, timeout=timeout)
                factory.return_value.__enter__.return_value.settimeout.assert_called_once_with(timeout)
                self.assertEqual(report["timeout_seconds"], timeout)

    def test_maximum_range_and_port_boundaries_are_inclusive(self):
        def outcome(target, port, timeout):
            return {"port": port, "service": "unknown", "status": "closed"}

        for start, end in ((1, MAX_PORTS), (65534, 65535)):
            with self.subTest(start=start, end=end), patch("scanner._scan_port_result", side_effect=outcome):
                report = scan_target(start_port=start, end_port=end)
                self.assertEqual([row["port"] for row in report["results"]], list(range(start, end + 1)))
                self.assertEqual(report["summary"]["total"], end - start + 1)

    def test_real_local_listener_with_explicit_range(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            report = scan_target("localhost", start_port=port, end_port=port, timeout=0.1)
        self.assertEqual(report["results"][0]["status"], "open")
        self.assertEqual(report["open_ports"][0]["port"], port)

    def test_worker_socket_cap_order_and_cleanup_across_outcomes(self):
        release = Event()
        saturated = Event()
        lock = Lock()
        state = {"active": 0, "peak": 0, "closed": 0}
        reports = []
        failures = []

        class ControlledSocket:
            def __enter__(self):
                return self

            def settimeout(self, timeout):
                if timeout != 0.05:
                    raise AssertionError("Timeout was not forwarded")

            def connect(self, address):
                if address[0] != "127.0.0.1":
                    raise AssertionError("Non-loopback target")
                with lock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                    if state["active"] == MAX_WORKERS:
                        saturated.set()
                if not release.wait(10):
                    raise AssertionError("Workers were not released")
                outcome = address[1] % 4
                if outcome == 1:
                    raise ConnectionRefusedError("refused")
                if outcome == 2:
                    raise TimeoutError("slow")
                if outcome == 3:
                    raise OSError("failed")

            def __exit__(self, *args):
                with lock:
                    state["active"] -= 1
                    state["closed"] += 1

        def run_scan():
            try:
                reports.append(scan_target(start_port=1, end_port=MAX_WORKERS * 2, timeout=0.05))
            except Exception as exc:
                failures.append(exc)

        with patch("scanner.socket.socket", side_effect=lambda *args: ControlledSocket()), patch(
            "scanner.socket.getservbyport", return_value="unknown"
        ):
            worker = Thread(target=run_scan)
            worker.start()
            try:
                self.assertTrue(saturated.wait(10), "Workers did not run concurrently")
            finally:
                release.set()
                worker.join(10)
            self.assertFalse(worker.is_alive(), "Scanner left workers running")

        self.assertEqual(failures, [])
        self.assertEqual(state, {"active": 0, "peak": MAX_WORKERS, "closed": MAX_WORKERS * 2})
        report = reports[0]
        self.assertEqual([row["port"] for row in report["results"]], list(range(1, MAX_WORKERS * 2 + 1)))
        self.assertEqual(report["summary"], {
            "total": MAX_WORKERS * 2,
            **{status: MAX_WORKERS // 2 for status in ("open", "closed", "timeout", "error")},
        })


if __name__ == "__main__":
    unittest.main()

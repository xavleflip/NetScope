from concurrent.futures import ThreadPoolExecutor as RealPool
from threading import Event, Lock, Thread, current_thread
import unittest
from unittest.mock import patch

from reports import validate_report
from scanner import MAX_WORKERS, scan_target


class CancellationTests(unittest.TestCase):
    def test_cancel_before_work_opens_no_sockets(self):
        cancel = Event()
        cancel.set()
        progress = []
        with patch("scanner.socket.socket") as sockets:
            report = scan_target(start_port=1, end_port=64, cancel_event=cancel,
                                 on_progress=lambda completed, total: progress.append((completed, total)))
        sockets.assert_not_called()
        self.assertEqual(report["scan_status"], "cancelled")
        self.assertEqual(report["requested_ports"], list(range(1, 65)))
        self.assertEqual(report["summary"]["total"], 0)
        self.assertEqual(report["results"], [])
        self.assertEqual(progress, [(0, 64)])
        self.assertEqual(validate_report(report), report)

    def test_cancel_blocked_sockets_stops_submission_and_joins_every_worker(self):
        cancel, saturated, release = Event(), Event(), Event()
        lock = Lock()
        state = {"active": 0, "closed": 0, "started": 0}
        workers, reports, errors = [], [], []
        submissions = []

        class ControlledSocket:
            def __enter__(self):
                return self

            def settimeout(self, timeout):
                self.timeout = timeout

            def connect(self, address):
                with lock:
                    workers.append(current_thread())
                    state["active"] += 1
                    state["started"] += 1
                    if state["active"] == MAX_WORKERS:
                        saturated.set()
                if not release.wait(10):
                    raise AssertionError("Test did not release sockets")

            def __exit__(self, *args):
                with lock:
                    state["active"] -= 1
                    state["closed"] += 1

        class RecordingPool(RealPool):
            def submit(self, function, port):
                submissions.append(port)
                return super().submit(function, port)

        def run():
            try:
                reports.append(scan_target(start_port=1, end_port=128, timeout=0.05, cancel_event=cancel))
            except Exception as exc:
                errors.append(exc)

        with patch("scanner.ThreadPoolExecutor", RecordingPool), patch(
            "scanner.socket.socket", side_effect=lambda *args: ControlledSocket()
        ), patch("scanner.socket.getservbyport", return_value="unknown"):
            driver = Thread(target=run)
            driver.start()
            try:
                self.assertTrue(saturated.wait(10))
                self.assertEqual(len(submissions), MAX_WORKERS)
                cancel.set()
            finally:
                cancel.set()
                release.set()
                driver.join(10)
            self.assertFalse(driver.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(state, {"active": 0, "closed": MAX_WORKERS, "started": MAX_WORKERS})
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(submissions), MAX_WORKERS)
        report = reports[0]
        self.assertEqual(report["scan_status"], "cancelled")
        self.assertEqual(report["summary"]["total"], MAX_WORKERS)
        self.assertEqual([row["port"] for row in report["results"]], list(range(1, MAX_WORKERS + 1)))
        self.assertEqual(len(report["requested_ports"]), 128)
        self.assertEqual(validate_report(report), report)

    def test_cancel_queued_work_skips_probes_that_have_not_started(self):
        started, release, cancel = Event(), Event(), Event()
        reports = []

        def probe(target, port, timeout):
            started.set()
            if not release.wait(10):
                raise AssertionError("Test did not release probe")
            return {"port": port, "service": "unknown", "status": "open"}

        with patch("scanner.ThreadPoolExecutor", side_effect=lambda **kwargs: RealPool(max_workers=1)), patch(
            "scanner._scan_port_result", side_effect=probe
        ) as probes:
            driver = Thread(target=lambda: reports.append(scan_target(start_port=1, end_port=100, cancel_event=cancel)))
            driver.start()
            try:
                self.assertTrue(started.wait(10))
                cancel.set()
            finally:
                cancel.set()
                release.set()
                driver.join(10)
            self.assertFalse(driver.is_alive())
            self.assertEqual(probes.call_count, 1)
        self.assertEqual(reports[0]["summary"]["total"], 1)
        self.assertEqual(reports[0]["scan_status"], "cancelled")

    def test_progress_is_monotonic_and_cancel_at_completion_is_labelled(self):
        cancel = Event()
        progress = []

        def notify(completed, total):
            progress.append((completed, total))
            if completed == total:
                cancel.set()

        with patch("scanner._scan_port_result", side_effect=lambda target, port, timeout:
                   {"port": port, "service": "unknown", "status": "closed"}):
            report = scan_target(start_port=1, end_port=40, cancel_event=cancel, on_progress=notify)
        self.assertEqual(progress, [(count, 40) for count in range(41)])
        self.assertEqual(report["scan_status"], "cancelled")
        self.assertEqual(report["summary"]["total"], 40)
        self.assertEqual(validate_report(report), report)

    def test_unexpected_failure_waits_for_active_probes_and_closes_sockets(self):
        started, release = Event(), Event()
        workers, closed, failures = [], [], []

        class BrokenSocket:
            def __enter__(self):
                return self

            def settimeout(self, timeout):
                pass

            def connect(self, address):
                workers.append(current_thread())
                started.set()
                if not release.wait(10):
                    raise AssertionError("Test did not release probe")
                raise RuntimeError("unexpected failure")

            def __exit__(self, *args):
                closed.append(self)

        def run():
            try:
                scan_target(start_port=1, end_port=64)
            except RuntimeError as exc:
                failures.append(str(exc))

        with patch("scanner.socket.socket", side_effect=lambda *args: BrokenSocket()):
            driver = Thread(target=run)
            driver.start()
            try:
                self.assertTrue(started.wait(10))
            finally:
                release.set()
                driver.join(10)
            self.assertFalse(driver.is_alive())
        self.assertEqual(failures, ["unexpected failure"])
        self.assertEqual(len(closed), len(workers))
        self.assertTrue(all(not worker.is_alive() for worker in workers))

    def test_progress_failure_also_joins_workers(self):
        workers = []

        def probe(target, port, timeout):
            workers.append(current_thread())
            return {"port": port, "service": "unknown", "status": "open"}

        def progress(completed, total):
            if completed:
                raise RuntimeError("consumer failed")

        with patch("scanner._scan_port_result", side_effect=probe):
            with self.assertRaisesRegex(RuntimeError, "consumer failed"):
                scan_target(start_port=1, end_port=64, on_progress=progress)
        self.assertTrue(all(not worker.is_alive() for worker in workers))


if __name__ == "__main__":
    unittest.main()

from threading import Event
import unittest
from unittest.mock import patch

from jobs import ScanJob


class JobTests(unittest.TestCase):
    def test_invalid_request_never_starts_a_thread(self):
        with patch("jobs.Thread") as thread:
            with self.assertRaises(ValueError):
                ScanJob("example.com", start_port=1, end_port=1, timeout=0.5)
        thread.assert_not_called()

    def test_jobs_are_isolated_and_ignore_foreign_messages_or_cancellation(self):
        starts = {1: Event(), 2: Event()}
        release = Event()

        def probe(target, port, timeout):
            starts[port].set()
            if not release.wait(10):
                raise AssertionError("Test did not release jobs")
            return {"port": port, "service": "unknown", "status": "open"}

        with patch("scanner._scan_port_result", side_effect=probe):
            first = ScanJob("localhost", start_port=1, end_port=1, timeout=0.05)
            second = ScanJob("127.0.0.1", start_port=2, end_port=2, timeout=0.05)
            try:
                self.assertTrue(starts[1].wait(10))
                self.assertTrue(starts[2].wait(10))
                self.assertFalse(second.cancel(first.run_id))
                self.assertFalse(second.cancel_event.is_set())
                second.messages.put((first.run_id, "report", {"fake": True}))
                second.messages.put((first.run_id, "progress", (999, 999)))
                second.poll()
                self.assertIsNone(second.report)
                self.assertEqual(second.completed, 0)
                self.assertTrue(first.cancel(first.run_id))
            finally:
                release.set()
                self.assertTrue(first.join(10))
                self.assertTrue(second.join(10))
        self.assertEqual(first.report["scan_status"], "cancelled")
        self.assertEqual(second.report["scan_status"], "completed")
        self.assertFalse(first.cancel(first.run_id))
        self.assertEqual(second.report["results"][0]["port"], 2)
        self.assertFalse(first.thread.daemon)
        self.assertFalse(second.thread.daemon)

    def test_finite_job_finishes_without_any_ui_consumer(self):
        with patch("scanner._scan_port_result", side_effect=lambda target, port, timeout:
                   {"port": port, "service": "unknown", "status": "closed"}):
            job = ScanJob("127.0.0.1", start_port=1, end_port=1024, timeout=0.05)
            job.thread.join(10)
        self.assertFalse(job.active)
        self.assertFalse(job.thread.daemon)
        self.assertIsNone(job.report)
        job.poll()
        self.assertEqual(job.completed, 1024)
        self.assertEqual(job.report["summary"]["total"], 1024)
        self.assertIsNone(job.error)

    def test_failure_is_reported_without_success_evidence(self):
        with patch("scanner._scan_port_result", side_effect=RuntimeError("worker failed")):
            job = ScanJob("localhost", start_port=1, end_port=32, timeout=0.05)
            self.assertTrue(job.join(10))
        self.assertEqual(job.error, "worker failed")
        self.assertIsNone(job.report)


if __name__ == "__main__":
    unittest.main()

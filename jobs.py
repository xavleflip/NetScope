"""One finite scan job and its messages; no Streamlit calls or global jobs."""

from queue import Empty, SimpleQueue
from threading import Event, Thread
from uuid import uuid4

import scanner
from reports import validate_report


class ScanJob:
    def __init__(self, target, *, start_port, end_port, timeout):
        self.total = len(scanner.validate_scan_request(
            target, start_port=start_port, end_port=end_port, timeout=timeout))
        self.run_id = uuid4().hex
        self.cancel_event = Event()
        self.messages = SimpleQueue()
        self.completed = 0
        self.report = None
        self.error = None
        self.thread = Thread(target=self._run, args=(target, start_port, end_port, timeout),
                             name=f"netscope-job-{self.run_id}", daemon=False)
        self.thread.start()

    def _run(self, target, start_port, end_port, timeout):
        # At most 1,025 progress messages plus one terminal message, even if no
        # browser remains to consume them. Workers never wait for a UI consumer.
        def progress(completed, total):
            self.messages.put((self.run_id, "progress", (completed, total)))
        try:
            report = scanner.scan_target(target, start_port=start_port, end_port=end_port,
                                         timeout=timeout, cancel_event=self.cancel_event,
                                         on_progress=progress)
            self.messages.put((self.run_id, "report", validate_report(report)))
        except Exception as exc:
            self.messages.put((self.run_id, "error", str(exc)))

    @property
    def active(self):
        return self.thread.is_alive()

    def cancel(self, run_id):
        """An old button cannot cancel a different run."""
        if run_id != self.run_id or not self.active:
            return False
        self.cancel_event.set()
        return True

    def poll(self):
        """Consume only this run's messages on the caller/UI thread."""
        while True:
            try:
                run_id, kind, value = self.messages.get_nowait()
            except Empty:
                break
            if run_id != self.run_id:
                continue
            if kind == "progress" and self.report is None and self.error is None:
                self.completed, _ = value
            elif kind == "report":
                self.report = value
            elif kind == "error":
                self.error = value

    def join(self, timeout=None):
        self.thread.join(timeout)
        self.poll()
        return not self.active

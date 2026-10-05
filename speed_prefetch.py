"""One-slot opt-in preparation queue. Never captures; uses the caller's resident worker."""
import threading
import time
from contextlib import contextmanager


class WorkerAdmission:
    """Foreground wins admission; an already running native call is not preempted."""
    def __init__(self):
        self.condition = threading.Condition()
        self.busy = False
        self.foreground = 0

    @contextmanager
    def enter(self, speculative=False, deadline=None):
        with self.condition:
            if not speculative:
                self.foreground += 1
            try:
                while self.busy or (speculative and self.foreground):
                    remaining = None if deadline is None else deadline-time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("worker_admission_timeout")
                    self.condition.wait(remaining)
                self.busy = True
            finally:
                if not speculative:
                    self.foreground -= 1
        try:
            yield
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()


class LatestFramePrefetch:
    def __init__(self, prepare, ttl_seconds=2):
        self.prepare = prepare
        self.ttl = ttl_seconds
        self.lock = threading.Lock()
        self.pending = None
        self.thread = None
        self.generation = 0
        self.superseded = 0
        self.latest_result = None

    def submit(self, payload, *, opt_in=False, captured_at=None):
        if opt_in is not True:
            return {'status': 'blocked', 'code': 'prefetch_opt_in_required'}
        now = time.monotonic()
        captured_at = now if captured_at is None else captured_at
        if now - captured_at > self.ttl or captured_at > now:
            return {'status': 'discarded', 'code': 'stale_frame'}
        with self.lock:
            self.generation += 1
            if self.pending is not None:
                self.superseded += 1
            self.pending = (self.generation, dict(payload), captured_at)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True, name='theia-prefetch')
                self.thread.start()
        return {'status': 'queued', 'generation': self.generation, 'pending_capacity': 1}

    def _run(self):
        while True:
            with self.lock:
                item, self.pending = self.pending, None
                if item is None:
                    self.thread = None
                    return
            generation, payload, captured_at = item
            if time.monotonic() - captured_at > self.ttl:
                result = {'status': 'discarded', 'code': 'stale_frame'}
            else:
                try:
                    result = self.prepare({**payload, '_speculative': True,
                                           '_prefetch_deadline': captured_at + self.ttl})
                except Exception as exc:
                    result = {'status': 'error', 'code': 'prefetch_failed', 'error_type': type(exc).__name__}
            if time.monotonic() - captured_at > self.ttl and result.get('status') not in {'error','blocked'}:
                result = {'status': 'discarded', 'code': 'stale_frame'}
            with self.lock:
                if generation == self.generation:
                    self.latest_result = result
                else:
                    self.superseded += 1

    def join(self, timeout=3):
        thread = self.thread
        if thread:
            thread.join(timeout)

    def status(self):
        with self.lock:
            return {'status': 'ok', 'pending': self.pending is not None,
                    'generation': self.generation, 'superseded': self.superseded,
                    'latest_result': self.latest_result}

from __future__ import annotations

import importlib.util
import json
import queue
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "windows_computer_use_locate_worker.py"


def load_worker(name: str = "theia_worker_protocol"):
    spec = importlib.util.spec_from_file_location(name, WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_echoes_request_id_and_total_and_pass_timings(monkeypatch):
    worker = load_worker("theia_worker_timing")
    monkeypatch.setattr(
        worker,
        "_locate",
        lambda payload: {
            "status": "found",
            "backend": "cpp_dll",
            "passes": [
                {"phase": "coarse", "seconds": 0.125},
                {"phase": "refine", "duration_ms": 17.5},
            ],
        },
    )

    result = worker._handle({"action": "locate", "request_id": "req-123"})

    assert result["request_id"] == "req-123"
    assert result["timing"]["total_ms"] >= 0
    assert result["timing"]["passes"] == [
        {"phase": "coarse", "duration_ms": 125.0},
        {"phase": "refine", "duration_ms": 17.5},
    ]


def test_persistent_call_skips_stale_response_and_correlates_request(monkeypatch):
    import windows_computer_use as plugin

    writes: list[dict] = []

    class FakeStdin:
        def write(self, value: str) -> None:
            writes.append(json.loads(value))

        def flush(self) -> None:
            return None

    class FakeProc:
        stdin = FakeStdin()

        @staticmethod
        def poll():
            return None

    class ReactiveQueue:
        def __init__(self):
            self.calls = 0

        def get(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"status": "found", "request_id": "stale-request"})
            return json.dumps({"status": "found", "request_id": writes[-1]["request_id"], "center": {"x": 1, "y": 2}})

    monkeypatch.setattr(plugin, "_start_persistent_external_worker", lambda python=None: {"status": "ok"})
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PROC", FakeProc())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_QUEUE", ReactiveQueue())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PYTHON", "worker-python")

    result = plugin._call_persistent_external_worker({"action": "locate"}, timeout=1)

    assert writes and writes[0]["request_id"]
    assert result["request_id"] == writes[0]["request_id"]
    assert result["center"] == {"x": 1, "y": 2}
    assert result["stale_responses_discarded"] == 1


def test_persistent_calls_are_serialized(monkeypatch):
    import windows_computer_use as plugin

    writes: list[dict] = []
    active = 0
    max_active = 0
    state_lock = threading.Lock()

    class FakeStdin:
        def write(self, value: str) -> None:
            writes.append(json.loads(value))

        def flush(self) -> None:
            return None

    class FakeProc:
        stdin = FakeStdin()

        @staticmethod
        def poll():
            return None

    class CorrelatedQueue:
        def get(self, timeout=None):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.04)
            request_id = writes[-1]["request_id"]
            with state_lock:
                active -= 1
            return json.dumps({"status": "found", "request_id": request_id})

    monkeypatch.setattr(plugin, "_start_persistent_external_worker", lambda python=None: {"status": "ok"})
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PROC", FakeProc())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_QUEUE", CorrelatedQueue())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PYTHON", "worker-python")

    results: list[dict] = []
    threads = [
        threading.Thread(target=lambda: results.append(plugin._call_persistent_external_worker({"action": "locate"}, timeout=1)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 2
    assert max_active == 1
    assert len({result["request_id"] for result in results}) == 2


def test_timeout_restarts_worker_and_clears_stale_queue(monkeypatch):
    import windows_computer_use as plugin

    class FakeStdin:
        def write(self, value: str) -> None:
            return None

        def flush(self) -> None:
            return None

    class FakeProc:
        stdin = FakeStdin()

        def __init__(self):
            self.terminated = False

        @staticmethod
        def poll():
            return None

        def terminate(self):
            self.terminated = True

    class TimeoutQueue:
        @staticmethod
        def get(timeout=None):
            raise queue.Empty

    proc = FakeProc()
    monkeypatch.setattr(plugin, "_start_persistent_external_worker", lambda python=None: {"status": "ok"})
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PROC", proc)
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_QUEUE", TimeoutQueue())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PYTHON", "worker-python")

    result = plugin._call_persistent_external_worker({"action": "locate"}, timeout=0.01)

    assert result["status"] == "error"
    assert result["worker_restarted"] is True
    assert proc.terminated is True
    assert plugin._EXTERNAL_WORKER_PROC is None
    assert plugin._EXTERNAL_WORKER_QUEUE is None


def test_worker_eof_fails_immediately_and_restarts(monkeypatch):
    import windows_computer_use as plugin

    class FakeStdin:
        def write(self, value: str) -> None:
            return None

        def flush(self) -> None:
            return None

    class FakeProc:
        stdin = FakeStdin()

        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 7

    class EofQueue:
        @staticmethod
        def get(timeout=None):
            return plugin._EXTERNAL_WORKER_EOF

    monkeypatch.setattr(plugin, "_start_persistent_external_worker", lambda python=None: {"status": "ok"})
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PROC", FakeProc())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_QUEUE", EofQueue())
    monkeypatch.setattr(plugin, "_EXTERNAL_WORKER_PYTHON", "worker-python")

    result = plugin._call_persistent_external_worker({"action": "locate"}, timeout=300)

    assert result["status"] == "error"
    assert "exited while awaiting response" in result["error"]
    assert result["worker_restarted"] is True


def test_worker_signature_changes_with_code_mtime_and_locate_config(monkeypatch, tmp_path):
    import windows_computer_use as plugin

    worker = tmp_path / "worker.py"
    worker.write_text("# one\n", encoding="utf-8")
    monkeypatch.setattr(plugin, "_worker_script_path", lambda: worker)
    monkeypatch.setenv("COMPUTER_USE_LOCATE_MODEL", "model-a")

    first = plugin._external_worker_signature("python-a")
    monkeypatch.setenv("COMPUTER_USE_LOCATE_MODEL", "model-b")
    second = plugin._external_worker_signature("python-a")
    worker.write_text("# two - different size\n", encoding="utf-8")
    third = plugin._external_worker_signature("python-a")

    assert first != second
    assert second != third

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_locate_runtime.py"


def load_benchmark(name: str = "theia_benchmark_locate_runtime"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_is_process_free_and_required_cli_options_parse(monkeypatch, tmp_path):
    def unexpected_process(*args, **kwargs):
        raise AssertionError("benchmark import launched a process")

    monkeypatch.setattr(subprocess, "Popen", unexpected_process)
    module = load_benchmark()

    image = tmp_path / "screen.png"
    image.write_bytes(b"not-opened-during-argument-parsing")
    args = module.build_parser().parse_args(
        [
            "--worker-python",
            "worker-python",
            "--worker-script",
            "worker.py",
            "--image",
            str(image),
            "--target",
            "search=the Search button",
            "--target",
            "settings=the Settings icon",
            "--runs",
            "7",
            "--baseline",
            "baseline.json",
            "--write-baseline",
            "new-baseline.json",
            "--backend",
            "external",
        ]
    )

    assert args.worker_python == "worker-python"
    assert args.worker_script == "worker.py"
    assert args.targets == ["search=the Search button", "settings=the Settings icon"]
    assert args.runs == 7
    assert args.baseline == "baseline.json"
    assert args.write_baseline == "new-baseline.json"
    assert args.backend == "external"


def test_target_parser_rejects_missing_or_duplicate_ids():
    module = load_benchmark("theia_benchmark_target_parser")

    with pytest.raises(ValueError, match="id=description"):
        module.parse_targets(["missing delimiter"])
    with pytest.raises(ValueError, match="duplicate target id"):
        module.parse_targets(["same=one", "same=two"])


def test_benchmark_covers_cold_warm_steady_pair_batch_and_refine():
    module = load_benchmark("theia_benchmark_phases")
    targets = module.parse_targets(["search=Search button", "settings=Settings icon"])

    class FakeWorker:
        def __init__(self):
            self.payloads = []
            self.next_coordinate = 10

        def request(self, payload):
            self.payloads.append(payload.copy())
            if payload["action"] == "locate_batch":
                response = {
                    "status": "found",
                    "backend": "external",
                    "model": "nvidia/LocateAnything-3B",
                    "results": [
                        {"id": target["id"], "label": target["description"], "center": {"x": 40 + i, "y": 50 + i}}
                        for i, target in enumerate(payload["targets"])
                    ],
                    "timing": {"total_ms": 12.0, "passes": [{"phase": "pbd", "duration_ms": 9.0}]},
                }
                return response, 13.0
            coordinate = self.next_coordinate
            self.next_coordinate += 1
            response = {
                "status": "found",
                "backend": "external",
                "model": "nvidia/LocateAnything-3B",
                "center": {"x": coordinate, "y": coordinate + 1},
                "timing": {"total_ms": 5.0, "passes": [{"phase": "direct", "duration_ms": 4.0}]},
            }
            return response, 6.0

    worker = FakeWorker()
    report = module.run_benchmark(
        worker,
        targets=targets,
        image_path="screen.png",
        image_size=(1920, 1080),
        runs=2,
        backend="external",
        include_refine=True,
        gpu_info={"available": False, "reason": "not installed"},
    )

    benchmarks = report["benchmarks"]
    assert benchmarks["cold"]["count"] == 1
    assert benchmarks["first_warm"]["count"] == 1
    assert benchmarks["steady_state_direct"]["targets"]["search"]["count"] == 2
    assert benchmarks["steady_state_direct"]["targets"]["settings"]["count"] == 2
    assert benchmarks["two_independent_same_image"]["count"] == 2
    assert all(len(sample["requests"]) == 2 for sample in benchmarks["two_independent_same_image"]["samples"])
    assert benchmarks["multi_pbd_batch"]["supported"] is True
    assert benchmarks["multi_pbd_batch"]["count"] == 2
    assert benchmarks["refine"]["targets"]["search"]["count"] == 2

    batch_payloads = [payload for payload in worker.payloads if payload["action"] == "locate_batch"]
    assert batch_payloads
    assert batch_payloads[0]["task"] == "multi"
    assert batch_payloads[0]["generation_mode"] == "fast"
    assert batch_payloads[0]["targets"] == [
        {"id": "search", "description": "Search button"},
        {"id": "settings", "description": "Settings icon"},
    ]
    assert any(payload.get("strategy") == "refine" for payload in worker.payloads)

    assert report["environment"]["process_mode"] == "persistent_jsonl_server"
    assert report["environment"]["backend"] == "external"
    assert report["environment"]["model"] == "nvidia/LocateAnything-3B"
    assert report["image"]["width"] == 1920
    assert report["image"]["height"] == 1080
    assert report["environment"]["nvidia_smi"]["available"] is False
    assert report["parity_snapshot"]["targets"]["search"]["label"] == "Search button"
    assert all(isinstance(value, int) for value in report["parity_snapshot"]["targets"]["search"]["coordinate"].values())

    direct_sample = benchmarks["steady_state_direct"]["targets"]["search"]["samples"][0]
    assert direct_sample["worker_timing"]["total_ms"] == 5.0
    assert direct_sample["worker_timing"]["passes"][0]["duration_ms"] == 4.0
    assert benchmarks["steady_state_direct"]["targets"]["search"]["wall_ms"]["p50"] == 6.0


def test_parity_compares_labels_and_integer_coordinates_with_tolerance():
    module = load_benchmark("theia_benchmark_parity")
    baseline = {
        "schema_version": 1,
        "targets": {
            "search": {"label": "Search button", "coordinate": {"x": 100, "y": 200}},
            "settings": {"label": "Settings icon", "coordinate": {"x": 300, "y": 400}},
        },
    }
    within_tolerance = {
        "schema_version": 1,
        "targets": {
            "search": {"label": "Search button", "coordinate": {"x": 102, "y": 198}},
            "settings": {"label": "Settings icon", "coordinate": {"x": 300, "y": 400}},
        },
    }

    passed = module.compare_parity(within_tolerance, baseline, tolerance=2)
    assert passed["status"] == "passed"
    assert passed["mismatches"] == []

    changed = {
        "schema_version": 1,
        "targets": {
            "search": {"label": "Search control", "coordinate": {"x": 103, "y": 200}},
            "settings": {"label": "Settings icon", "coordinate": None},
        },
    }
    failed = module.compare_parity(changed, {"parity_snapshot": baseline}, tolerance=2)
    assert failed["status"] == "failed"
    assert failed["tolerance_px"] == 2
    assert {item["kind"] for item in failed["mismatches"]} == {"label", "coordinate", "missing_coordinate"}
    assert module.parity_exit_code(failed) == 2


def test_worker_client_uses_jsonl_server_protocol_without_real_processes():
    module = load_benchmark("theia_benchmark_worker_client")
    calls = []

    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                json.dumps({"status": "found", "center": {"x": 7, "y": 9}})
                + "\n"
                + json.dumps({"status": "ok", "action": "shutdown"})
                + "\n"
            )
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -1

    process = FakeProcess()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    client = module.WorkerServer("worker-python", "worker.py", popen_factory=fake_popen)
    assert calls == []
    with client:
        response, wall_ms = client.request({"action": "locate", "description": "Search"})
        assert response["center"] == {"x": 7, "y": 9}
        assert wall_ms >= 0

    assert calls[0][0] == ["worker-python", "worker.py", "--server"]
    requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert requests[0]["action"] == "locate"
    assert requests[0]["request_id"].startswith("bench-")
    assert requests[-1]["action"] == "shutdown"


def test_nvidia_smi_is_optional_and_parses_vram_without_failing():
    module = load_benchmark("theia_benchmark_nvidia_smi")

    class Completed:
        returncode = 0
        stdout = "0, NVIDIA RTX 4090, 24564, 1024\n"
        stderr = ""

    info = module.query_nvidia_smi(runner=lambda *args, **kwargs: Completed())
    assert info["available"] is True
    assert info["gpus"][0]["memory_total_mib"] == 24564
    assert info["gpus"][0]["memory_used_mib"] == 1024

    missing = module.query_nvidia_smi(
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi"))
    )
    assert missing["available"] is False
    assert "nvidia-smi" in missing["reason"]


def test_main_writes_baseline_and_returns_nonzero_on_parity_change(monkeypatch, tmp_path, capsys):
    module = load_benchmark("theia_benchmark_main")
    image = tmp_path / "screen.png"
    image.write_bytes(b"fixture bytes")
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    coordinate = {"x": 10, "y": 20}

    class FakeWorker:
        startup_ms = 1.25

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def request(self, payload):
            return {
                "status": "found",
                "backend": "external",
                "model": "test-model",
                "center": coordinate.copy(),
                "timing": {"total_ms": 2.0, "passes": []},
            }, 3.0

    monkeypatch.setattr(module, "WorkerServer", lambda *args, **kwargs: FakeWorker())
    monkeypatch.setattr(module, "image_dimensions", lambda path: (800, 600))
    monkeypatch.setattr(module, "query_nvidia_smi", lambda: {"available": False, "reason": "test"})

    common = [
        "--worker-python",
        "fake-python",
        "--worker-script",
        str(tmp_path / "worker.py"),
        "--image",
        str(image),
        "--target",
        "search=Search button",
        "--runs",
        "1",
        "--backend",
        "external",
    ]
    assert module.main(common + ["--write-baseline", str(baseline_path), "--output", str(report_path)]) == 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert baseline["targets"]["search"]["coordinate"] == {"x": 10, "y": 20}
    assert report["environment"]["worker_python"] == "fake-python"
    assert report["environment"]["worker_script"].endswith("worker.py")
    assert report["environment"]["process_startup_ms"] == 1.25
    capsys.readouterr()

    coordinate.update(x=20)
    assert module.main(common + ["--baseline", str(baseline_path), "--parity-tolerance", "2"]) == 2
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["parity"]["status"] == "failed"

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "windows_computer_use_locate_worker.py"


def load_worker(name: str):
    spec = importlib.util.spec_from_file_location(name, WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_preprocessing_is_reused_for_same_immutable_image(tmp_path):
    worker = load_worker("theia_stage_cache")
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (1600, 900), "white").save(image_path)

    first = worker._get_cpp_stage(str(image_path), None, 1024)
    second = worker._get_cpp_stage(str(image_path), None, 1024)

    assert first is second
    assert first["image"].size == (1024, 576)
    assert first["cache_hit"] is True
    assert first["identity"] == second["identity"]


def test_scaled_point_never_returns_one_pixel_past_image_edge():
    worker = load_worker("theia_point_clamp")
    assert worker._scale_point((1000, 1000), (100, 50)) == {"x": 99, "y": 49}


def test_image_identity_verifies_capture_digest_against_bytes(tmp_path):
    worker = load_worker("theia_capture_digest")
    image_path = tmp_path / "screen.png"
    content = b"immutable-png"
    image_path.write_bytes(content)
    stat = image_path.stat()
    Path(f"{image_path}.meta.json").write_text(json.dumps({
        "immutable": True,
        "sha256": "a" * 64,
        "file_size": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
    }), encoding="utf-8")

    identity = worker._image_identity(str(image_path))

    assert identity[-1] == __import__("hashlib").sha256(content).hexdigest()


def test_stage_cache_separates_roi_and_resize_parameters(tmp_path):
    worker = load_worker("theia_stage_cache_parameters")
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (1600, 900), "white").save(image_path)

    full = worker._get_cpp_stage(str(image_path), None, 1024)
    roi = worker._get_cpp_stage(str(image_path), [100, 50, 600, 400], 1024)
    smaller = worker._get_cpp_stage(str(image_path), None, 512)

    assert full is not roi
    assert full is not smaller
    assert roi["offset"] == (100, 50)
    assert roi["work_size"] == (600, 400)
    assert smaller["image"].size == (512, 288)


def test_exact_result_cache_avoids_second_decode(monkeypatch, tmp_path):
    worker = load_worker("theia_result_cache")
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 240), "white").save(image_path)
    calls = []

    monkeypatch.setattr(worker, "_cpp_runtime_paths", lambda: ("cli.exe", "model.gguf"))
    monkeypatch.setattr(worker.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        worker,
        "_locate_with_cpp_uncached",
        lambda payload: calls.append(dict(payload)) or {
            "status": "found",
            "backend": "cpp",
            "runtime": "dll",
            "box": {"x1": 10, "y1": 20, "x2": 30, "y2": 40},
            "center": {"x": 20, "y": 30},
        },
    )
    payload = {
        "description": "Save button",
        "image_path": str(image_path),
        "backend": "cpp",
        "strategy": "direct",
        "max_side": 1024,
        "generation_mode": "hybrid",
        "max_new_tokens": 32,
    }

    first = worker._locate_with_cpp(payload)
    second = worker._locate_with_cpp(payload)

    assert len(calls) == 1
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["result_cache"] == "exact"
    assert second["center"] == {"x": 20, "y": 30}


def test_auto_batch_starts_exact_without_proven_one_pass(monkeypatch):
    worker = load_worker("theia_adaptive_batch_cold")
    worker._ONE_PASS_STATS.clear()
    calls = []
    monkeypatch.setattr(
        worker,
        "_locate_batch_exact",
        lambda payload, targets: calls.append("exact") or {"status": "found", "targets": [], "passes": []},
    )
    monkeypatch.setattr(
        worker,
        "_locate_batch_one_pass",
        lambda payload, targets: calls.append("one_pass") or {"status": "found", "label_mapping_valid": True},
    )

    result = worker._locate_batch({
        "image_path": "screen.png",
        "mode": "auto",
        "targets": [{"id": "a", "description": "Save"}, {"id": "b", "description": "Cancel"}],
    })

    assert calls == ["exact"]
    assert result["mode_used"] == "exact_adaptive"
    assert result["one_pass_eligible"] is False


def test_auto_batch_uses_one_pass_after_two_explicit_successes(monkeypatch):
    worker = load_worker("theia_adaptive_batch_warm")
    worker._ONE_PASS_STATS.clear()
    calls = []
    monkeypatch.setattr(
        worker,
        "_locate_batch_exact",
        lambda payload, targets: calls.append("exact") or {"status": "found", "targets": [], "passes": []},
    )
    monkeypatch.setattr(
        worker,
        "_locate_batch_one_pass",
        lambda payload, targets: calls.append("one_pass") or {
            "status": "found", "targets": [], "passes": [], "label_mapping_valid": True,
        },
    )
    base = {
        "image_path": "screen.png",
        "targets": [{"id": "a", "description": "Save"}, {"id": "b", "description": "Cancel"}],
    }

    worker._locate_batch({**base, "mode": "one_pass"})
    worker._locate_batch({**base, "mode": "one_pass"})
    result = worker._locate_batch({**base, "mode": "auto"})

    assert calls == ["one_pass", "one_pass", "one_pass"]
    assert result["mode_used"] == "one_pass_adaptive"
    assert result["one_pass_eligible"] is True

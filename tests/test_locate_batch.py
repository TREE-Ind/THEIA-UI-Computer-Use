from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "windows_computer_use_locate_worker.py"


def load_worker(name: str):
    spec = importlib.util.spec_from_file_location(name, WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hit(description: str, label: str | None = None, x: int = 10):
    box = {"x1": x, "y1": 20, "x2": x + 20, "y2": 40}
    return {
        "status": "found",
        "backend": "cpp_dll",
        "description": description,
        "box": box,
        "boxes": [box],
        "center": {"x": x + 10, "y": 30},
        "detections": [{"label": label or description, "box": box, "center": {"x": x + 10, "y": 30}}],
        "passes": [{"phase": "coarse", "duration_ms": 5.0}],
    }


def test_exact_batch_runs_independent_queries_on_one_image_and_preserves_ids(monkeypatch):
    worker = load_worker("theia_batch_exact")
    calls = []

    def fake_locate(payload):
        calls.append(dict(payload))
        return hit(payload["description"], x=10 * len(calls))

    monkeypatch.setattr(worker, "_locate", fake_locate)
    payload = {
        "action": "locate_batch",
        "mode": "exact",
        "image_path": "immutable.png",
        "targets": [
            {"id": "save", "description": "Save icon"},
            {"id": "cancel", "description": "Cancel button"},
        ],
    }

    result = worker._handle(payload)

    assert result["status"] == "found"
    assert result["mode_requested"] == "exact"
    assert result["mode_used"] == "exact"
    assert [item["id"] for item in result["targets"]] == ["save", "cancel"]
    assert [call["image_path"] for call in calls] == ["immutable.png", "immutable.png"]
    assert [call["description"] for call in calls] == ["Save icon", "Cancel button"]
    assert result["timing"]["passes"]


def test_one_pass_maps_labels_to_target_ids_without_losing_labels(monkeypatch):
    worker = load_worker("theia_batch_one_pass")
    calls = []

    def fake_locate(payload):
        calls.append(dict(payload))
        return {
            "status": "found",
            "backend": "cpp_dll",
            "detections": [
                {"label": "Cancel button", "box": {"x1": 50, "y1": 1, "x2": 70, "y2": 21}},
                {"label": "Save icon", "box": {"x1": 10, "y1": 1, "x2": 30, "y2": 21}},
            ],
            "passes": [{"phase": "multi_category", "duration_ms": 8.0}],
        }

    monkeypatch.setattr(worker, "_locate", fake_locate)
    result = worker._handle({
        "action": "locate_batch",
        "mode": "one_pass",
        "image_path": "immutable.png",
        "targets": [
            {"id": "save", "description": "Save icon"},
            {"id": "cancel", "description": "Cancel button"},
        ],
    })

    assert len(calls) == 1
    assert calls[0]["task"] == "multi"
    assert calls[0]["description"] == "Save icon</c>Cancel button"
    assert result["label_mapping_valid"] is True
    assert result["mode_used"] == "one_pass"
    assert [(item["id"], item["label"]) for item in result["targets"]] == [
        ("save", "Save icon"),
        ("cancel", "Cancel button"),
    ]
    assert result["targets"][0]["center"] == {"x": 20, "y": 11}


def test_auto_uses_exact_until_one_pass_mapping_is_proven(monkeypatch):
    worker = load_worker("theia_batch_auto")
    calls = []

    def fake_locate(payload):
        calls.append(dict(payload))
        if payload.get("task") == "multi":
            raise AssertionError("cold auto mode must not speculate with one-pass")
        return hit(payload["description"])

    monkeypatch.setattr(worker, "_locate", fake_locate)
    result = worker._handle({
        "action": "locate_batch",
        "mode": "auto",
        "image_path": "immutable.png",
        "targets": [
            {"id": "save", "description": "Save icon"},
            {"id": "cancel", "description": "Cancel button"},
        ],
    })

    assert len(calls) == 2
    assert result["mode_requested"] == "auto"
    assert result["mode_used"] == "exact_adaptive"
    assert result["label_mapping_valid"] is True
    assert result["one_pass_eligible"] is False
    assert [item["id"] for item in result["targets"]] == ["save", "cancel"]


@pytest.mark.parametrize(
    "targets,error_fragment",
    [
        ([], "non-empty"),
        ([{"id": "same", "description": "one"}, {"id": "same", "description": "two"}], "unique"),
        ([{"id": "missing", "description": ""}], "description"),
    ],
)
def test_batch_rejects_invalid_targets_before_inference(monkeypatch, targets, error_fragment):
    worker = load_worker(f"theia_batch_invalid_{len(targets)}_{error_fragment}")
    calls = []
    monkeypatch.setattr(worker, "_locate", lambda payload: calls.append(payload) or {})

    result = worker._handle({"action": "locate_batch", "mode": "auto", "image_path": "screen.png", "targets": targets})

    assert result["status"] == "error"
    assert error_fragment in result["error"]
    assert calls == []

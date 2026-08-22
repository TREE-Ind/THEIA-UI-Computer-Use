"""Coordinate mapping tests for cpp locate worker (no CLI/GPU required)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

WORKER = Path(__file__).resolve().parent.parent / "windows_computer_use_locate_worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location("locate_worker", WORKER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_preproc_target_matches_cpp_padding():
    mod = _load_worker()
    # 512x288 desktop thumb typical
    tw, th = mod._preproc_target(512, 288)
    assert tw % 28 == 0 and th % 28 == 0
    assert tw >= 512 and th >= 288


def test_cpp_boxes_not_double_scaled():
    mod = _load_worker()
    # Values like CLI output (~0-200), must NOT be treated as 0..1000 tokens again.
    raw = [{"x1": 27.69, "y1": 89.91, "x2": 175.81, "y2": 222.04}]
    mapped = mod._cpp_boxes_target_to_image(raw, 512, 288)
    assert mapped
    b = mapped[0]
    assert b["x2"] > b["x1"] and b["y2"] > b["y1"]
    # Old bug produced tiny boxes (~14px wide); fixed mapping should be much larger.
    assert (b["x2"] - b["x1"]) > 40


def test_scale_thumb_to_full():
    mod = _load_worker()
    boxes = [{"x1": 10, "y1": 20, "x2": 30, "y2": 40}]
    out = mod._scale_boxes_between_sizes(boxes, 512, 288, 1920, 1080)
    assert out[0]["x1"] == 38  # 10 * 1920/512 rounded
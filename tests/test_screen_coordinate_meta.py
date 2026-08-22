"""Screen coordinate adjustment for region captures."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import tempfile
from pathlib import Path

from PIL import Image

PLUGIN = Path(__file__).resolve().parent.parent / "windows_computer_use.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("wcu", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_screen_adjust_crop_meta():
    mod = _load_plugin()
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "crop.png"
        Image.new("RGB", (20, 20), "white").save(img)
        stat = img.stat()
        digest = hashlib.sha256(img.read_bytes()).hexdigest()
        meta_path = f"{img}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump({
                "screen_origin": {"x": 491, "y": 316}, "immutable": True,
                "sha256": digest, "file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns,
            }, mf)
        hit = {
            "status": "found",
            "center": {"x": 100, "y": 200},
            "box": {"x1": 90, "y1": 190, "x2": 110, "y2": 210},
        }
        out = mod._screen_adjust_locate_hit(hit, str(img))
        assert out["center"] == {"x": 591, "y": 516}
        assert out["coordinate_space"] == "screen_pixels"
        assert out["screen_coordinates_valid"] is True


def test_screen_adjust_rejects_spoofed_sidecar():
    mod = _load_plugin()
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "crop.png"
        Image.new("RGB", (20, 20), "white").save(img)
        stat = img.stat()
        with open(f"{img}.meta.json", "w", encoding="utf-8") as mf:
            json.dump({
                "screen_origin": {"x": 900, "y": 700}, "immutable": True,
                "sha256": "0" * 64, "file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns,
            }, mf)
        hit = {"status": "found", "center": {"x": 10, "y": 10}}
        out = mod._screen_adjust_locate_hit(hit, str(img))
        assert out["center"] == {"x": 10, "y": 10}
        assert out["screen_coordinates_valid"] is False
        assert out["coordinate_space"] == "image_pixels_unverified"


def test_find_click_fails_closed_without_trusted_capture_meta(monkeypatch):
    mod = _load_plugin()
    clicks = []
    monkeypatch.setattr(mod, "_locate", lambda **kwargs: [{
        "status": "found", "center": {"x": 10, "y": 10},
        "coordinate_space": "image_pixels_unverified", "screen_coordinates_valid": False,
    }])
    monkeypatch.setattr(mod, "_click", lambda *args, **kwargs: clicks.append((args, kwargs)))
    result = mod._find_click("Settings tab", image_path="external.png")
    assert result["status"] == "blocked"
    assert clicks == []


def test_pick_anchor_top_center():
    mod = _load_plugin()
    hit = {"box": {"x1": 0, "y1": 100, "x2": 100, "y2": 200}}
    x, y = mod._pick_anchor_point(hit, "top_center")
    assert x == 50
    assert 100 < y < 120


def test_interpolate_drag_points():
    mod = _load_plugin()
    pts = mod._interpolate_drag_points(0, 0, 100, 50, 3)
    assert len(pts) == 3
    assert pts[0] == {"x": 0, "y": 0}
    assert pts[-1] == {"x": 100, "y": 50}
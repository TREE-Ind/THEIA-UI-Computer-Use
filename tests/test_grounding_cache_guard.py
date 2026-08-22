from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

PLUGIN = Path(__file__).resolve().parent.parent / "windows_computer_use.py"


def _load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fixture(tmp_path: Path):
    path = tmp_path / "screen.png"
    image = Image.new("RGB", (120, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 60, 50), fill="black")
    image.save(path)
    stat = path.stat()
    Path(f"{path}.meta.json").write_text(json.dumps({
        "screen_origin": {"x": 200, "y": 300},
        "capture_region": [200, 300, 120, 100],
        "immutable": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns,
    }), encoding="utf-8")
    targets = {"button": {"id": "button", "center": {"x": 250, "y": 340}}}
    return path, image, targets


def test_visual_guard_accepts_unchanged_anchor(monkeypatch, tmp_path):
    mod = _load_plugin("wcu_guard_same")
    path, image, targets = _fixture(tmp_path)
    guard = mod._build_visual_guard(str(path), targets)
    monkeypatch.setattr(mod, "_capture_guard_image", lambda region: (image.copy(), (200, 300)))

    verified = mod._verify_visual_guard(guard)

    assert verified["matched"] is True
    assert verified["max_distance"] == 0.0


def test_visual_guard_rejects_changed_anchor(monkeypatch, tmp_path):
    mod = _load_plugin("wcu_guard_changed")
    path, _image, targets = _fixture(tmp_path)
    guard = mod._build_visual_guard(str(path), targets)
    changed = Image.new("RGB", (120, 100), "white")
    monkeypatch.setattr(mod, "_capture_guard_image", lambda region: (changed, (200, 300)))

    verified = mod._verify_visual_guard(guard)

    assert verified["matched"] is False
    assert verified["max_distance"] > 0.3


def test_grounding_cache_refuses_reuse_when_visual_guard_changes(monkeypatch):
    mod = _load_plugin("wcu_guard_entry")
    fingerprint = {
        "kind": "window", "handle": 42, "process_id": 7, "dpi": 144,
        "left": 0, "top": 0, "width": 800, "height": 600,
        "client_bounds": {"left": 0, "top": 30, "width": 800, "height": 570},
    }
    mod._GROUNDING_CACHE["stable"] = {
        "kind": "targets",
        "window_fingerprint": fingerprint,
        "visual_guard": {"anchors": [{"id": "a"}]},
        "targets": {"a": {"id": "a", "center": {"x": 10, "y": 10}}},
    }
    monkeypatch.setattr(mod, "_grounding_window_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(mod, "_verify_visual_guard", lambda guard: {"matched": False, "max_distance": 0.9})
    monkeypatch.setattr(mod, "_result", lambda status="ok", **extra: {"status": status, **extra})

    entry, error = mod._grounding_cache_entry("stable")

    assert entry is None
    assert error["status"] == "stale"
    assert "visual anchors changed" in error["error"]


def test_window_fingerprint_includes_native_identity(monkeypatch):
    mod = _load_plugin("wcu_guard_fingerprint")
    monkeypatch.setattr(mod, "_active_window", lambda: {
        "title": "Editor", "left": -100, "top": 20, "width": 900, "height": 700,
        "handle": 99, "process_id": 123, "dpi": 120,
        "client_bounds": {"left": -92, "top": 50, "width": 884, "height": 662},
    })

    fingerprint = mod._grounding_window_fingerprint()

    assert fingerprint["handle"] == 99
    assert fingerprint["process_id"] == 123
    assert fingerprint["dpi"] == 120
    assert fingerprint["client_bounds"]["left"] == -92


def test_window_fingerprint_changes_with_monitor_topology(monkeypatch):
    mod = _load_plugin("wcu_guard_topology")
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    monkeypatch.setattr(mod, "_virtual_screen_bounds", lambda: {"left": -100, "top": 0, "right": 100, "bottom": 100, "width": 200, "height": 100})
    monkeypatch.setattr(mod, "_monitor_topology", lambda: [
        {"left": -100, "top": 0, "right": 0, "bottom": 100, "dpi_x": 96, "dpi_y": 96},
        {"left": 0, "top": 0, "right": 100, "bottom": 100, "dpi_x": 144, "dpi_y": 144},
    ])
    first = mod._grounding_window_fingerprint()
    monkeypatch.setattr(mod, "_monitor_topology", lambda: [
        {"left": -100, "top": 0, "right": 0, "bottom": 100, "dpi_x": 144, "dpi_y": 144},
        {"left": 0, "top": 0, "right": 100, "bottom": 100, "dpi_x": 96, "dpi_y": 96},
    ])
    second = mod._grounding_window_fingerprint()
    assert first != second

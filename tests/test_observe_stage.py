from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

PLUGIN = Path(__file__).resolve().parent.parent / "windows_computer_use.py"


def _load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_capture_active_client_uses_native_client_roi(monkeypatch, tmp_path):
    mod = _load_plugin("wcu_active_client")
    mod.SCRATCH_DIR = tmp_path
    monkeypatch.setattr(mod, "_virtual_screen_bounds", lambda: {
        "left": -1920, "top": 0, "right": 1920, "bottom": 1080, "width": 3840, "height": 1080,
    })
    monkeypatch.setattr(mod, "_active_window", lambda: {
        "title": "Editor", "left": -1800, "top": 10, "width": 1000, "height": 900,
        "client_bounds": {"left": -1792, "top": 42, "width": 984, "height": 850},
    })

    virtual = Image.new("RGB", (3840, 1080), "white")

    class PG:
        def screenshot(self, **kwargs):
            assert kwargs == {"region": None, "allScreens": True}
            return virtual.copy()

    monkeypatch.setattr(mod, "_pyautogui", lambda: PG())

    result = mod._capture_screen(scope="active_client")

    assert result["scope"] == "active_client"
    assert result["screen_origin"] == {"x": -1792, "y": 42}
    assert result["capture_region"] == [-1792, 42, 984, 850]


def test_observe_stage_captures_once_then_grounds_same_image(monkeypatch):
    mod = _load_plugin("wcu_observe_stage")
    captured = {"count": 0}
    locate_args = []

    def fake_capture(**kwargs):
        captured["count"] += 1
        assert kwargs["scope"] == "active_window"
        return {
            "status": "ok", "image_path": "immutable.png",
            "screen_origin": {"x": -100, "y": 20}, "capture_region": [-100, 20, 800, 600],
        }

    def fake_locate_batch(**kwargs):
        locate_args.append(kwargs)
        return {"status": "found", "image_path": kwargs["image_path"], "targets": [
            {"id": "save", "status": "found", "center": {"x": 10, "y": 20}},
        ]}

    monkeypatch.setattr(mod, "_capture_screen", fake_capture)
    monkeypatch.setattr(mod, "_locate_batch", fake_locate_batch)
    monkeypatch.setattr(mod, "_active_window", lambda: None)

    result = mod._observe_stage(
        targets=[{"id": "save", "description": "Save button"}],
        scope="active_window",
    )

    assert captured["count"] == 1
    assert locate_args[0]["image_path"] == "immutable.png"
    assert locate_args[0]["mode"] == "exact"
    assert result["capture"]["image_path"] == "immutable.png"
    assert result["grounding"]["status"] == "found"
    assert result["stage_static"] is True


def test_observe_stage_without_targets_is_capture_only(monkeypatch):
    mod = _load_plugin("wcu_observe_capture")
    monkeypatch.setattr(mod, "_capture_screen", lambda **kwargs: {"status": "ok", "image_path": "screen.png"})
    monkeypatch.setattr(mod, "_locate_batch", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no targets")))
    monkeypatch.setattr(mod, "_active_window", lambda: None)

    result = mod._observe_stage(targets=[], scope="virtual_desktop")

    assert result["grounding"] is None


def test_grounding_capture_prefers_active_window_but_keeps_taskbar_visible(monkeypatch):
    mod = _load_plugin("wcu_capture_roi_policy")
    scopes = []
    monkeypatch.setattr(mod, "_active_window", lambda: {"title": "Editor"})
    monkeypatch.setattr(mod, "_capture_screen", lambda **kwargs: scopes.append(kwargs["scope"]) or {"image_path": "screen.png"})

    mod._capture_for_grounding("Save button in editor")
    mod._capture_for_grounding("Windows Search on the taskbar")

    assert scopes == ["active_window", "primary"]

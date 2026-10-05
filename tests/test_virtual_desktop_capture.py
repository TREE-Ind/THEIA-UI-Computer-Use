from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path

from PIL import Image
import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "windows_computer_use.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("wcu_virtual_desktop", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_negative_secondary_monitor_coordinate_is_on_virtual_desktop(monkeypatch):
    mod = _load_plugin()
    monkeypatch.setattr(
        mod,
        "_virtual_screen_bounds",
        lambda: {"left": -1920, "top": 0, "width": 4480, "height": 1440, "right": 2560, "bottom": 1440},
    )

    mod._ensure_on_screen(-1200, 500)


def test_region_is_clipped_to_virtual_desktop(monkeypatch):
    mod = _load_plugin()
    monkeypatch.setattr(
        mod,
        "_virtual_screen_bounds",
        lambda: {"left": -1920, "top": -200, "width": 4480, "height": 1640, "right": 2560, "bottom": 1440},
    )

    region, clipped = mod._normalize_region([-1930, -210, 100, 100], return_clipped=True)

    assert region == (-1920, -200, 90, 90)
    assert clipped is True


def test_region_outside_virtual_desktop_is_rejected(monkeypatch):
    mod = _load_plugin()
    monkeypatch.setattr(
        mod,
        "_virtual_screen_bounds",
        lambda: {"left": -1920, "top": 0, "width": 4480, "height": 1440, "right": 2560, "bottom": 1440},
    )

    try:
        mod._normalize_region([3000, 0, 100, 100])
    except ValueError as exc:
        assert "does not intersect the virtual desktop" in str(exc)
    else:
        raise AssertionError("expected out-of-bounds region to fail")


def test_all_screens_capture_metadata_uses_virtual_origin(monkeypatch, tmp_path):
    mod = _load_plugin()
    mod.SCRATCH_DIR = tmp_path
    monkeypatch.setattr(
        mod,
        "_virtual_screen_bounds",
        lambda: {"left": -1920, "top": -200, "width": 4480, "height": 1640, "right": 2560, "bottom": 1440},
    )
    monkeypatch.setattr(mod, "_active_window", lambda: None)

    class FakeScreenshot:
        width = 4480
        height = 1640

        def convert(self, mode):
            from PIL import Image
            return Image.new(mode, (self.width, self.height), 'white')

        def save(self, path):
            Path(path).write_bytes(b"png")

    class FakePyAutoGUI:
        def screenshot(self, **kwargs):
            assert kwargs == {"region": None, "allScreens": True}
            return FakeScreenshot()

    monkeypatch.setattr(mod, "_pyautogui", lambda: FakePyAutoGUI())

    result = mod._capture_screen(all_screens=True)
    meta = mod._load_capture_meta(result["image_path"])

    assert result["screen_origin"] == {"x": -1920, "y": -200}
    assert result["virtual_screen"]["width"] == 4480
    assert meta["screen_origin"] == {"x": -1920, "y": -200}
    assert meta["capture_region"] == [-1920, -200, 4480, 1640]
    assert meta["immutable"] is True
    assert meta["sha256"] == hashlib.sha256(b"png").hexdigest()


def test_negative_origin_region_crops_the_correct_virtual_pixels(monkeypatch, tmp_path):
    mod = _load_plugin()
    mod.SCRATCH_DIR = tmp_path
    monkeypatch.setattr(mod, "_virtual_screen_bounds", lambda: {
        "left": -100, "top": 0, "width": 200, "height": 10, "right": 100, "bottom": 10,
    })
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    virtual = Image.new("RGB", (200, 10), "red")
    for x in range(100, 200):
        for y in range(10):
            virtual.putpixel((x, y), (0, 0, 255))

    class PG:
        def screenshot(self, **kwargs):
            assert kwargs == {"region": None, "allScreens": True}
            return virtual.copy()

    monkeypatch.setattr(mod, "_pyautogui", lambda: PG())

    result = mod._capture_screen(scope="region", region=[-50, 0, 100, 10])
    captured = Image.open(result["image_path"]).convert("RGB")

    assert captured.size == (100, 10)
    assert captured.getpixel((0, 5)) == (255, 0, 0)
    assert captured.getpixel((49, 5)) == (255, 0, 0)
    assert captured.getpixel((50, 5)) == (0, 0, 255)
    assert captured.getpixel((99, 5)) == (0, 0, 255)
    assert result["screen_origin"] == {"x": -50, "y": 0}


def test_capture_rejects_conflicting_all_screens_and_scope():
    mod = _load_plugin()
    with pytest.raises(ValueError, match="all_screens"):
        mod._capture_screen(scope="active_window", all_screens=True)

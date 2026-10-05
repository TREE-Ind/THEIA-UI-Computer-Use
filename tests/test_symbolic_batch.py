from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "windows_computer_use.py"


def load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_locate_batch_captures_once_preserves_ids_and_adjusts_crop_origin(monkeypatch, tmp_path):
    module = load_plugin("theia_plugin_locate_batch")
    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    stat = image.stat()
    (tmp_path / "screen.png.meta.json").write_text(
        json.dumps({
            "screen_origin": {"x": 100, "y": 200}, "immutable": True,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "file_size": stat.st_size, "file_mtime_ns": stat.st_mtime_ns,
        }), encoding="utf-8"
    )
    captures = []
    monkeypatch.setattr(module, "_capture_screen", lambda **kwargs: captures.append(kwargs) or {"image_path": str(image)})
    calls = []
    monkeypatch.setattr(
        module,
        "_external_worker_call",
        lambda payload, **kwargs: calls.append(payload) or {
            "status": "found",
            "mode_used": "exact",
            "targets": [
                {"id": "save", "description": "Save icon", "status": "found", "center": {"x": 10, "y": 20}, "box": {"x1": 1, "y1": 2, "x2": 19, "y2": 38}},
                {"id": "cancel", "description": "Cancel button", "status": "found", "center": {"x": 40, "y": 50}, "box": {"x1": 30, "y1": 40, "x2": 50, "y2": 60}},
            ],
            "timing": {"total_ms": 12.5},
        },
    )

    result = module._locate_batch(
        targets=[{"id": "save", "description": "Save icon"}, {"id": "cancel", "description": "Cancel button"}],
        image_path=None,
        mode="exact",
        backend="cpp",
    )

    assert len(captures) == 1
    assert calls[0]["action"] == "locate_batch"
    assert calls[0]["backend"] == "cpp"
    assert calls[0]["image_path"] == str(image)
    assert [item["id"] for item in result["targets"]] == ["save", "cancel"]
    assert result["targets"][0]["center"] == {"x": 110, "y": 220}
    assert result["targets"][1]["box"] == {"x1": 130, "y1": 240, "x2": 150, "y2": 260}


def test_symbolic_batch_resolves_all_targets_before_first_action(monkeypatch):
    module = load_plugin("theia_symbolic_batch")
    # This unit tests resolution/order; acquisition and fail-closed exact pixel
    # validation are exercised end-to-end in test_automatic_pixels.py.
    def valid_frame(path, fingerprint, points):
        assert path == "immutable.png"
        assert points == [(11, 22)]
        return True
    monkeypatch.setattr(module._SPEED, "validate_action_frame", valid_frame)
    locate_calls = []
    click_calls = []
    monkeypatch.setattr(
        module,
        "_locate_batch",
        lambda **kwargs: locate_calls.append(kwargs) or {
            "status": "found",
            "targets": [
                {"id": "field", "status": "found", "center": {"x": 11, "y": 22}, "screen_coordinates_valid": True},
                {"id": "tab", "status": "found", "center": {"x": 33, "y": 44}, "screen_coordinates_valid": True},
            ],
        },
    )
    monkeypatch.setattr(module, "_click", lambda **kwargs: click_calls.append(kwargs) or {"status": "ok"})
    monkeypatch.setattr(module, "_type", lambda **kwargs: {"status": "ok"})

    result = module._computer_use_batch(
        targets=[
            {"id": "field", "description": "Search field"},
            {"id": "tab", "description": "Top tab"},
        ],
        image_path="immutable.png",
        static_screen=True,
        steps=[
            {"action": "click", "target_id": "field", "target_hint": "Search field", "safe_purpose": "focus_input", "risk": "non_destructive"},
        ],
    )

    assert len(locate_calls) == 1
    assert click_calls == [{"x": 11, "y": 22}]
    assert result["status"] == "ok"
    assert result["resolved_targets"]["field"] == {"x": 11, "y": 22}
    assert result["steps"][0]["step"]["target_id"] == "field"


def test_symbolic_batch_preflight_blocks_before_locate(monkeypatch):
    module = load_plugin("theia_symbolic_preflight")
    locate_calls = []
    monkeypatch.setattr(module, "_locate_batch", lambda **kwargs: locate_calls.append(kwargs) or {})

    result = module._computer_use_batch(
        targets=[{"id": "safe", "description": "Safe tab"}],
        static_screen=True,
        steps=[
            {"action": "click", "target_id": "safe", "target_hint": "Safe tab", "safe_purpose": "navigate_view", "risk": "non_destructive"},
            {"action": "click", "x": 1, "y": 2, "target_hint": "Submit payment", "safe_purpose": "focus_input", "risk": "non_destructive"},
        ],
    )

    assert result["status"] == "blocked"
    assert result["executed_steps"] == 0
    assert locate_calls == []


def test_symbolic_batch_blocks_high_impact_description_even_with_safe_hint(monkeypatch):
    module = load_plugin("theia_symbolic_description_safety")
    monkeypatch.setattr(module, "_locate_batch", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not locate")))

    result = module._computer_use_batch(
        targets=[{"id": "buy", "description": "Confirm purchase"}],
        static_screen=True,
        steps=[{"action": "click", "target_id": "buy", "target_hint": "purchase item", "safe_purpose": "select_item", "risk": "non_destructive"}],
    )

    assert result["status"] == "blocked"
    assert result["executed_steps"] == 0
    assert "Confirm purchase" in result["error"]


def test_symbolic_batch_requires_explicit_immutable_screen_acknowledgement(monkeypatch):
    module = load_plugin("theia_symbolic_static")
    monkeypatch.setattr(module, "_locate_batch", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not locate")))
    result = module._computer_use_batch(
        targets=[{"id": "safe", "description": "Safe tab"}],
        static_screen=False,
        steps=[{"action": "click", "target_id": "safe", "target_hint": "Safe tab", "risk": "non_destructive"}],
    )
    assert result["status"] == "blocked"
    assert "static_screen" in result["error"]


def test_locate_batch_tool_is_registered():
    module = load_plugin("theia_locate_batch_registration")

    class Ctx:
        def __init__(self):
            self.tools = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

    ctx = Ctx()
    module.register_tools(ctx)
    tools = {tool["name"]: tool for tool in ctx.tools}
    assert "computer_use_locate_batch" in tools
    schema = tools["computer_use_locate_batch"]["schema"]["parameters"]
    assert set(schema["required"]) == {"targets"}
    assert schema["properties"]["mode"]["enum"] == ["auto", "exact", "one_pass"]

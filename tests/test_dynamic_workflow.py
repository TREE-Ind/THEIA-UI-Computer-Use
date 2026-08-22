from __future__ import annotations

import importlib.util
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "windows_computer_use.py"


def _load_plugin(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _safe_stage(target_id: str, description: str):
    lowered = description.lower()
    if "tab" in lowered or "page" in lowered:
        purpose, hint = "navigate_view", description
    elif "selector" in lowered or "option" in lowered or "theme" in lowered:
        purpose, hint = "choose_option", description
    else:
        purpose, hint = "select_item", description if "item" in lowered else f"{description} item"
    return {
        "scope": "active_window",
        "static_screen": True,
        "targets": [{"id": target_id, "description": description}],
        "steps": [{
            "action": "click", "risk": "non_destructive", "target_id": target_id,
            "target_hint": hint, "safe_purpose": purpose,
        }],
    }


def test_dynamic_workflow_preflights_all_stages_before_capture(monkeypatch):
    mod = _load_plugin("wcu_dynamic_block")
    monkeypatch.setattr(mod, "_observe_stage", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not capture")))
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    stages = [
        _safe_stage("tab", "Settings tab"),
        {
            "scope": "active_window",
            "targets": [{"id": "submit", "description": "Submit purchase button"}],
            "steps": [{
                "action": "click", "risk": "non_destructive", "target_id": "submit",
                "target_hint": "Submit purchase button",
            }],
        },
    ]

    result = mod._dynamic_workflow(stages)

    assert result["status"] == "blocked"
    assert result["executed_stages"] == 0
    assert result["captures"] == 0


def test_dynamic_workflow_recaptures_and_resolves_each_stage(monkeypatch):
    mod = _load_plugin("wcu_dynamic_execute")
    observations = []
    batches = []
    monkeypatch.setattr(mod, "_active_window", lambda: None)

    def fake_observe(**kwargs):
        index = len(observations)
        observations.append(kwargs)
        target = kwargs["targets"][0]
        return {
            "status": "ok",
            "capture": {"image_path": f"stage-{index}.png"},
            "grounding": {
                "status": "found", "targets": [{
                    "id": target["id"], "status": "found",
                    "center": {"x": 100 + index, "y": 200 + index},
                    "screen_coordinates_valid": True,
                }],
            },
        }

    def fake_batch(steps, **kwargs):
        batches.append((steps, kwargs))
        return {"status": "ok", "planned_steps": len(steps), "executed_steps": len(steps)}

    monkeypatch.setattr(mod, "_observe_stage", fake_observe)
    monkeypatch.setattr(mod, "_computer_use_batch", fake_batch)

    result = mod._dynamic_workflow([
        _safe_stage("settings", "Settings tab"),
        _safe_stage("theme", "Theme selector"),
    ])

    assert result["status"] == "ok"
    assert result["captures"] == 2
    assert len(observations) == 2
    assert all(0 < item["timeout_seconds"] <= 120 for item in observations)
    assert batches[0][0][0]["x"] == 100
    assert batches[1][0][0]["x"] == 101
    assert "target_id" not in batches[0][0][0]
    assert batches[0][0][0]["resolved_target_id"] == "settings"


def test_dynamic_workflow_stops_before_actions_when_grounding_fails(monkeypatch):
    mod = _load_plugin("wcu_dynamic_grounding_fail")
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    monkeypatch.setattr(mod, "_observe_stage", lambda **kwargs: {
        "status": "ok", "capture": {"image_path": "stage.png"},
        "grounding": {"status": "not_found", "targets": []},
    })
    monkeypatch.setattr(mod, "_computer_use_batch", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not act")))

    result = mod._dynamic_workflow([_safe_stage("missing", "Missing tab")])

    assert result["status"] == "stopped"
    assert result["executed_stages"] == 0
    assert result["captures"] == 1


def test_dynamic_workflow_caps_stages():
    mod = _load_plugin("wcu_dynamic_caps")
    result = mod._dynamic_workflow([_safe_stage(str(i), f"Tab {i}") for i in range(9)])
    assert result["status"] == "error"
    assert "at most 8" in result["error"]


def test_dynamic_workflow_blocks_coordinate_actions_after_invalidating_action(monkeypatch):
    mod = _load_plugin("wcu_dynamic_stale")
    monkeypatch.setattr(mod, "_observe_stage", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not capture")))
    stage = {
        "scope": "active_window", "static_screen": True,
        "targets": [
            {"id": "settings", "description": "Settings tab"},
            {"id": "theme", "description": "Theme tab"},
        ],
        "steps": [
            {"action": "click", "risk": "non_destructive", "target_id": "settings", "target_hint": "Settings tab", "safe_purpose": "navigate_view"},
            {"action": "click", "risk": "non_destructive", "target_id": "theme", "target_hint": "Theme tab", "safe_purpose": "navigate_view"},
        ],
    }

    result = mod._dynamic_workflow([stage])

    assert result["status"] == "blocked"
    assert result["captures"] == 0
    assert "fresh stage" in result["error"]


def test_batch_malformed_late_step_executes_nothing(monkeypatch):
    mod = _load_plugin("wcu_batch_complete_preflight")
    clicks = []
    monkeypatch.setattr(mod, "_click", lambda **kwargs: clicks.append(kwargs) or {"status": "ok"})
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    monkeypatch.setattr(mod, "_virtual_screen_bounds", lambda: {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080})

    result = mod._computer_use_batch([
        {"action": "click", "risk": "non_destructive", "x": 10, "y": 10, "target_hint": "Settings tab", "safe_purpose": "navigate_view"},
        {"action": "move", "risk": "non_destructive"},
    ])

    assert result["status"] == "blocked"
    assert result["executed_steps"] == 0
    assert clicks == []


def test_batch_blocks_consequential_synonym_even_with_safe_purpose(monkeypatch):
    mod = _load_plugin("wcu_batch_trash")
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    result = mod._computer_use_batch([
        {"action": "click", "risk": "non_destructive", "x": 10, "y": 10, "target_hint": "Trash icon", "safe_purpose": "select_item"},
    ])
    assert result["status"] == "blocked"
    assert result["executed_steps"] == 0


def test_batch_expired_deadline_executes_nothing(monkeypatch):
    mod = _load_plugin("wcu_batch_deadline")
    moves = []
    monkeypatch.setattr(mod, "_move", lambda **kwargs: moves.append(kwargs) or {"status": "ok"})
    monkeypatch.setattr(mod, "_active_window", lambda: None)
    monkeypatch.setattr(mod, "_virtual_screen_bounds", lambda: {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080})

    result = mod._computer_use_batch([
        {"action": "move", "risk": "non_destructive", "x": 10, "y": 10},
    ], deadline=mod.time.monotonic() - 1)

    assert result["status"] == "stopped"
    assert result["executed_steps"] == 0
    assert moves == []

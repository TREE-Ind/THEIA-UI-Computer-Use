"""Contract tests for a bounded Jev controller; no live desktop or network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from system_one_loop import run_loop


def spec():
    return [
        {"candidates": [{"id": "records", "description": "Records section button", "risk": "non_destructive", "safe_purpose": "navigate_view", "action": "click"}]},
        {"candidates": [{"id": "details", "description": "Details panel button", "risk": "non_destructive", "safe_purpose": "inspect", "action": "click"}]},
    ]


def choices_spec():
    stages = spec()
    stages[0]["candidates"].append({"id": "team", "description": "Team section button", "risk": "non_destructive", "safe_purpose": "navigate_view", "action": "click"})
    stages[1]["candidates"].append({"id": "summary", "description": "Summary panel button", "risk": "non_destructive", "safe_purpose": "inspect", "action": "click"})
    return stages

def harness(decisions=("records", "details"), stale=False, action_status="ok"):
    state = {"step": 0, "actions": [], "decisions": []}
    def active(): return {"title": "Public Demo", "handle": 17, "left": 0, "top": 0, "width": 800, "height": 600}
    def observe(targets):
        i = state["step"]
        return {"status": "ok", "capture": {"sha256": f"shot{i}", "image_path": f"shot{i}.png", "capture_region": [0, 0, 800, 600]},
                "grounding": {"targets": [{"id": t["id"], "description": t["description"], "status": "found", "runtime": "dll", "screen_coordinates_valid": True,
                    "capture_metadata_provenance": "trusted_runtime_registry", "center": {"x": 100, "y": 200}} for t in targets]}}
    def capture(): return {"sha256": "stale" if stale else f"shot{state['step']}", "capture_region": [0, 0, 800, 600]}
    def decide(**kwargs):
        state["decisions"].append(kwargs)
        choice = decisions[len(state["decisions"])-1]
        return {"status": "proposed", "candidate_id": choice, "snapshot_id": kwargs["snapshot_id"], "confidence": 0.98}
    def action(**kwargs):
        state["actions"].append(kwargs)
        if action_status == "ok": state["step"] += 1
        return {"status": action_status, "executed_steps": 1 if action_status == "ok" else 0}
    def preflight(candidate): return None
    return state, dict(observe=observe, capture=capture, decide=decide, action=action, active_window=active, preflight=preflight)


def test_two_verified_stages_complete_without_a_main_model_turn():
    state, deps = harness()
    result = run_loop(goal="Open details", window="Public Demo", stages=choices_spec(),
                      completion_target={"id": "done", "description": "Done panel"}, public_context=True, **deps)
    assert result["status"] == "completed"
    assert result["executed_stages"] == 2
    assert result["verified_completion"] is True
    assert [x["target_id"] for x in state["actions"]] == ["records", "details"]
    assert len(state["decisions"]) == 2
    assert [d["snapshot_id"] for d in state["decisions"]] == ["shot0", "shot1"]


def test_stale_capture_stops_without_action():
    state, deps = harness(stale=True)
    result = run_loop(goal="Open details", window="Public Demo", stages=spec(),
                      completion_target={"id": "done", "description": "Done panel"}, public_context=True, **deps)
    assert result["status"] == "escalate" and result["reason"] == "stale_capture"
    assert state["actions"] == []


def test_unsafe_candidate_preflight_blocks_before_capture_or_network():
    state, deps = harness()
    deps["preflight"] = lambda c: "unsafe" if c["id"] == "pay" else None
    stages = [{"candidates": [{"id": "pay", "description": "Pay now button", "risk": "non_destructive", "safe_purpose": "navigate_view", "action": "click"}]}]
    result = run_loop(goal="Pay", window="Public Demo", stages=stages,
                      completion_target={"id": "done", "description": "Done panel"}, public_context=True, **deps)
    assert result["status"] == "blocked" and state["actions"] == state["decisions"] == []


def test_provider_escalation_and_nonpublic_context_never_act():
    state, deps = harness()
    result = run_loop(goal="Open details", window="Public Demo", stages=spec(),
                      completion_target={"id": "done", "description": "Done panel"}, public_context=False, **deps)
    assert result["status"] == "blocked" and not state["decisions"]
    deps["decide"] = lambda **kw: {"status": "escalate", "reason": "low_confidence"}
    result = run_loop(goal="Open details", window="Public Demo", stages=choices_spec(),
                      completion_target={"id": "done", "description": "Done panel"}, public_context=True, **deps)
    assert result["status"] == "escalate" and state["actions"] == []


def test_registered_tool_runs_one_real_plugin_stage_via_injected_boundaries(monkeypatch):
    import json
    import windows_computer_use as ui
    state, deps = harness(decisions=("records",))
    monkeypatch.setattr(ui, '_active_window', deps['active_window'])
    monkeypatch.setattr(ui, '_observe_stage', lambda **kw: deps['observe'](kw['targets']))
    monkeypatch.setattr(ui, '_capture_screen', lambda **kw: deps['capture']())
    monkeypatch.setattr(ui, '_decide_next', lambda **kw: deps['decide'](**kw))
    monkeypatch.setattr(ui, '_computer_use_batch', lambda **kw: deps['action'](**kw))
    class Ctx:
        tools = []
        def register_tool(self, **kw): self.tools.append(kw)
    ctx=Ctx(); ui.register_tools(ctx)
    tool=next(t for t in ctx.tools if t['name']=='computer_use_jev_loop')
    result=json.loads(tool['handler']({'goal':'Open details','window':'Public Demo',
        'public_context':True,'stages':spec()[:1],
        'completion_target':{'id':'done','description':'Done panel'}}))
    assert result['status']=='completed'
    assert len(state['actions'])==1


def test_invalid_candidate_id_never_reaches_provider():
    state, deps = harness()
    bad = [{"candidates": [{"id": "bad\nname", "description": "Details panel button",
             "risk": "non_destructive", "safe_purpose": "inspect", "action": "click"}]}]
    result = run_loop(goal="Open details", window="Public Demo", stages=bad,
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "blocked" and state["decisions"] == state["actions"] == []


def test_invalid_proposal_or_failed_action_returns_control_to_hermes():
    state, deps = harness(decisions=("absent",))
    result = run_loop(goal="Open details", window="Public Demo", stages=choices_spec(),
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["reason"] == "invalid_proposal" and state["actions"] == []
    state, deps = harness(decisions=("records",), action_status="blocked")
    result = run_loop(goal="Open details", window="Public Demo", stages=spec()[:1],
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["reason"] == "action_failed" and result["status"] == "escalate"


def test_transient_loading_screen_is_reobserved_before_second_action():
    state, deps = harness()
    original = deps["observe"]
    state["loading_observations"] = 0
    def observe(targets):
        if state["step"] == 1 and state["loading_observations"] < 2:
            state["loading_observations"] += 1
            return {"status": "ok", "capture": {"sha256": "loading", "image_path": "loading.png"},
                    "grounding": {"status": "not_found", "targets": [
                        {"id": t["id"], "status": "not_found", "runtime": "dll"} for t in targets]}}
        return original(targets)
    deps["observe"] = observe
    result = run_loop(goal="Open details", window="Public Demo", stages=spec(),
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "completed"
    assert state["loading_observations"] == 2
    assert [x["target_id"] for x in state["actions"]] == ["records", "details"]


def test_single_authorized_candidate_skips_jev_but_still_preflights_and_verifies():
    state, deps = harness()
    deps["decide"] = lambda **kw: (_ for _ in ()).throw(AssertionError("unneeded provider"))
    result = run_loop(goal="Open records", window="Public Demo", stages=spec()[:1],
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "completed"
    assert [x["target_id"] for x in state["actions"]] == ["records"]


def test_untrusted_provenance_is_not_retried_or_acted_on():
    state, deps = harness()
    calls = []
    def observe(targets):
        calls.append(targets)
        result = harness()[1]["observe"](targets)
        result["grounding"]["targets"][0]["capture_metadata_provenance"] = "untrusted"
        return result
    deps["observe"] = observe
    result = run_loop(goal="Open records", window="Public Demo", stages=spec()[:1],
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["reason"] == "untrusted_grounding"
    assert len(calls) == 1 and not state["actions"]


def test_missing_target_retry_is_bounded_without_any_click(monkeypatch):
    import system_one_loop
    monkeypatch.setattr(system_one_loop.time, "sleep", lambda _: None)
    state, deps = harness()
    calls = []
    def observe(targets):
        calls.append(targets)
        return {"status": "ok", "capture": {"sha256": "loading", "image_path": "loading.png"},
                "grounding": {"status": "not_found", "targets": [
                    {"id": t["id"], "status": "not_found", "runtime": "dll"} for t in targets]}}
    deps["observe"] = observe
    result = run_loop(goal="Open records", window="Public Demo", stages=spec()[:1],
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "escalate" and result["reason"] == "untrusted_grounding"
    assert len(calls) == 4 and not state["actions"] and not state["decisions"]


def test_final_heading_can_arrive_after_transient_navigation(monkeypatch):
    import system_one_loop
    monkeypatch.setattr(system_one_loop.time, "sleep", lambda _: None)
    state, deps = harness()
    original = deps["observe"]
    state["final_attempts"] = 0
    def observe(targets):
        if targets[0]["id"] == "done":
            state["final_attempts"] += 1
            if state["final_attempts"] == 1:
                return {"status": "ok", "capture": {"sha256": "loading", "image_path": "loading.png"},
                        "grounding": {"targets": [{"id": "done", "status": "not_found", "runtime": "dll"}]}}
        return original(targets)
    deps["observe"] = observe
    result = run_loop(goal="Open records", window="Public Demo", stages=spec()[:1],
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "completed" and state["final_attempts"] == 2


def test_jev_receives_only_trusted_compact_visible_grounding():
    import json
    state, deps = harness()
    original = deps["observe"]
    def observe(targets):
        result = original(targets)
        if len(targets) > 1:
            result["grounding"]["targets"][0]["center"] = {"x": 100, "y": 80}
            result["grounding"]["targets"][1]["center"] = {"x": 700, "y": 510}
        result["capture"]["image_path"] = "private-screenshot-path.png"
        return result
    deps["observe"] = observe
    result = run_loop(goal="Open details", window="Public Demo", stages=choices_spec(),
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "completed"
    first, second = [d["grounding_manifest"] for d in state["decisions"]]
    assert first == {"stage_index": 0, "stage_count": 2, "previous_verified": False,
                     "visible": [{"id": "records", "description": "Records section button", "purpose": "navigate_view", "position": "top_left"},
                                 {"id": "team", "description": "Team section button", "purpose": "navigate_view", "position": "bottom_right"}]}
    assert second["stage_index"] == 1 and second["previous_verified"] is True
    assert "private-screenshot-path" not in json.dumps(state["decisions"])
    assert '"x"' not in json.dumps(state["decisions"]) and '"y"' not in json.dumps(state["decisions"])


def test_out_of_capture_detection_never_reaches_jev_or_click():
    state, deps = harness()
    original = deps["observe"]
    def observe(targets):
        result = original(targets)
        result["grounding"]["targets"][0]["center"] = {"x": 810, "y": 200}
        return result
    deps["observe"] = observe
    result = run_loop(goal="Open details", window="Public Demo", stages=choices_spec(),
                      completion_target={"id": "done", "description": "Done panel"},
                      public_context=True, **deps)
    assert result["status"] == "escalate" and result["reason"] == "untrusted_grounding"
    assert not state["decisions"] and not state["actions"]

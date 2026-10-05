"""Bounded Jev-guided GUI stages; injected THEIA functions keep the provider actionless."""
from __future__ import annotations

import time
import re
from typing import Any

_ID_RE = re.compile(r"[A-Za-z0-9_]{1,64}\Z")

def _safe_target(target: Any) -> bool:
    return (isinstance(target, dict) and set(target) == {"id", "description"}
            and isinstance(target["id"], str) and bool(_ID_RE.fullmatch(target["id"]))
            and isinstance(target["description"], str) and 0 < len(target["description"]) <= 256
            and bool(target["description"].strip()))


def _grounded(observation: Any, ids: list[str]) -> bool:
    if not isinstance(observation, dict) or observation.get("status") != "ok":
        return False
    capture = observation.get("capture") or {}
    if not capture.get("sha256") or not capture.get("image_path"):
        return False
    grounding = observation.get("grounding") or {}
    results = grounding.get("targets") or []
    found = {x.get("id"): x for x in results if isinstance(x, dict)}
    return (len(results) == len(ids) and set(found) == set(ids) and all(
        found[i].get("status") == "found" and found[i].get("runtime") == "dll"
        and found[i].get("screen_coordinates_valid") is True
        and found[i].get("capture_metadata_provenance") == "trusted_runtime_registry"
        and isinstance(found[i].get("center"), dict) for i in ids))

def _grounding_state(observation: Any, ids: list[str]) -> str:
    """Only an explicit native not_found is transient; malformed provenance is not."""
    if _grounded(observation, ids):
        return "ready"
    if not isinstance(observation, dict) or observation.get("status") != "ok":
        return "unsafe"
    shot = observation.get("capture") or {}
    if not shot.get("sha256") or not shot.get("image_path"):
        return "unsafe"
    targets = (observation.get("grounding") or {}).get("targets") or []
    if len(targets) != len(ids) or {t.get("id") for t in targets if isinstance(t, dict)} != set(ids):
        return "unsafe"
    for target in targets:
        if target.get("runtime") != "dll" or target.get("status") not in {"found", "not_found"}:
            return "unsafe"
        if target["status"] == "found" and (target.get("screen_coordinates_valid") is not True
            or target.get("capture_metadata_provenance") != "trusted_runtime_registry"
            or not isinstance(target.get("center"), dict)):
            return "unsafe"
    return "retry"

def _grounding_manifest(observation: dict, options: list[dict], index: int,
                        stage_count: int, previous_verified: bool) -> dict | None:
    """Project trusted detections to public coarse positions, never raw pixels."""
    region = observation["capture"].get("capture_region")
    if (not isinstance(region, (list, tuple)) or len(region) != 4 or
        any(type(v) is not int for v in region) or region[2] <= 0 or region[3] <= 0):
        return None
    left, top, width, height = region
    found = {t["id"]: t for t in observation["grounding"]["targets"]}
    visible = []
    for option in options:
        center = found[option["id"]]["center"]
        x, y = center.get("x"), center.get("y")
        if (type(x) is not int or type(y) is not int or
            not left <= x < left + width or not top <= y < top + height):
            return None
        horizontal = ("left", "center", "right")[min(2, (x - left) * 3 // width)]
        vertical = ("top", "middle", "bottom")[min(2, (y - top) * 3 // height)]
        visible.append({"id": option["id"], "description": option["description"],
                        "purpose": option["safe_purpose"], "position": f"{vertical}_{horizontal}"})
    return {"stage_index": index, "stage_count": stage_count,
            "previous_verified": previous_verified, "visible": visible}


def run_loop(*, goal: str, window: str, stages: list, completion_target: dict,
             public_context: bool, observe, capture, decide, action, active_window,
             preflight, max_duration_ms: int = 60000, readiness=None, timed_observe=None) -> dict:
    """Choose safe IDs without a main-model turn; stop on any unverified transition.

    `public_context` is an explicit opt-in to sending goal and candidate text to
    TypeSafe. Only caller-supplied descriptions are transmitted, never pixels.
    """
    if public_context is not True:
        return {"status": "blocked", "reason": "public_context_required", "executed_stages": 0}
    if (not isinstance(goal, str) or not 0 < len(goal) <= 512 or
        not isinstance(window, str) or not 0 < len(window) <= 512 or
        not isinstance(stages, list) or not 1 <= len(stages) <= 4 or
        not _safe_target(completion_target) or
        isinstance(max_duration_ms, bool) or not isinstance(max_duration_ms, int) or
        not 1000 <= max_duration_ms <= 120000):
        return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
    for stage in stages:
        if (not isinstance(stage, dict) or "candidates" not in stage or
                set(stage) - {"candidates", "expected_target", "wait_for_target", "wait_timeout_ms", "ready_pixel"}):
            return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
        for key in ("expected_target", "wait_for_target"):
            if key in stage and not _safe_target(stage[key]):
                return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
        if (type(stage.get("wait_timeout_ms", 1000)) is not int or
                not 100 <= stage.get("wait_timeout_ms", 1000) <= 10000):
            return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
        pixel = stage.get("ready_pixel")
        if pixel is not None and (not isinstance(pixel, list) or len(pixel) != 6 or
                any(type(v) is not int for v in pixel) or any(not 0 <= v <= 255 for v in pixel[2:]) or readiness is None):
            return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
        options = stage["candidates"]
        if not isinstance(options, list) or not 1 <= len(options) <= 16:
            return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
        ids = []
        for option in options:
            if (not isinstance(option, dict) or set(option) != {"id", "description", "risk", "safe_purpose", "action"}
                or not _safe_target({k: option[k] for k in ("id", "description")})
                or option["risk"] != "non_destructive" or option["action"] not in {"click", "double_click"}):
                return {"status": "blocked", "reason": "invalid_plan", "executed_stages": 0}
            ids.append(option["id"])
            preflight_reason = preflight(option)
            if preflight_reason:
                mismatch = 'does not match declared safe_purpose' in str(preflight_reason)
                consequential = preflight_reason == 'high_impact_target' or 'high-impact' in str(preflight_reason)
                return {"status": "blocked", "reason": "unsafe_candidate", "executed_stages": 0,
                        "candidate_id": option['id'], "phase": "preflight", "retryable": False,
                        "code": ("safe_purpose_description_mismatch" if mismatch else
                                 "consequential_candidate_blocked" if consequential else "preflight_failed"),
                        "next_step": ("describe_the_actual_visible_page_view_or_section_for_navigate_view_no_relabeling_consequential_targets"
                                      if mismatch and option['safe_purpose'] == 'navigate_view' else
                                      "revise_explicit_safe_plan_keep_consequential_boundary_separate")}
        if len(ids) != len(set(ids)):
            return {"status": "blocked", "reason": "duplicate_candidates", "executed_stages": 0}
    started = time.monotonic()
    deadline = started + max_duration_ms / 1000
    initial = active_window()
    if not initial or window not in str(initial.get("title", "")) or not initial.get("handle"):
        return {"status": "escalate", "reason": "wrong_window", "executed_stages": 0}
    identity_keys = ("handle", "process_id", "dpi", "left", "top", "width", "height")
    identity = {key:initial.get(key) for key in identity_keys}
    completed = []
    def stop(reason):
        return {"status": "escalate", "reason": reason, "executed_stages": len(completed),
                "stages": completed, "duration_ms": round((time.monotonic()-started)*1000, 1)}
    def same_window():
        now = active_window()
        return bool(now and {key:now.get(key) for key in identity_keys} == identity
                    and window in str(now.get("title", "")))
    def observe_ready(targets, ready_pixel=None, wait_timeout_ms=None):
        ids = [t["id"] for t in targets]
        local_deadline = min(deadline, time.monotonic() + wait_timeout_ms / 1000) if wait_timeout_ms else deadline
        for attempt in range(4):
            if time.monotonic() >= deadline or not same_window():
                return None, "deadline" if time.monotonic() >= deadline else "wrong_window"
            if time.monotonic() >= local_deadline:
                return None, "target_wait_timeout"
            if ready_pixel is not None and not readiness(ready_pixel):
                time.sleep(min(0.25, max(0, local_deadline - time.monotonic())))
                continue
            observed = (timed_observe(targets, max(.001, local_deadline - time.monotonic()))
                        if timed_observe is not None else observe(targets))
            if time.monotonic() >= local_deadline:
                return None, "deadline" if time.monotonic() >= deadline else "target_wait_timeout"
            if not same_window():
                return None, "wrong_window"
            state = _grounding_state(observed, ids)
            if state == "ready":
                return observed, None
            if state == "unsafe":
                return None, "untrusted_grounding"
            if attempt < 3:
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        return None, "untrusted_grounding"
    previous_action = None
    try:
        for index, stage in enumerate(stages):
            if time.monotonic() >= deadline: return stop("deadline")
            if not same_window(): return stop("wrong_window")
            if stage.get("wait_for_target"):
                _, error = observe_ready([stage["wait_for_target"]], stage.get("ready_pixel"), stage.get("wait_timeout_ms", 1000))
                if error: return stop(error)
            options = stage["candidates"]
            targets = [{"id": x["id"], "description": x["description"]} for x in options]
            observed, error = observe_ready(targets, stage.get("ready_pixel"), stage.get("wait_timeout_ms"))
            if error: return stop(error)
            if completed:
                completed[-1]["semantic_verified"] = True
            shot = observed["capture"]
            manifest = _grounding_manifest(observed, options, index, len(stages), bool(completed))
            if manifest is None: return stop("untrusted_grounding")
            proposal = ({"status": "proposed", "candidate_id": options[0]["id"],
                         "snapshot_id": shot["sha256"], "latency_ms": 0.0}
                        if len(options) == 1 else decide(
                            goal=goal, window=window, snapshot_id=shot["sha256"],
                            candidates=[{k: x[k] for k in ("id", "description", "risk")} for x in options],
                            previous_action=previous_action, grounding_manifest=manifest))
            if proposal.get("status") != "proposed": return stop(proposal.get("reason") or proposal.get("status") or "provider_error")
            chosen = next((x for x in options if x["id"] == proposal.get("candidate_id")), None)
            if chosen is None or proposal.get("snapshot_id") != shot["sha256"]: return stop("invalid_proposal")
            if time.monotonic() >= deadline: return stop("deadline")
            fresh = capture()
            if (not same_window() or fresh.get("sha256") != shot["sha256"]
                    or fresh.get("capture_region") != shot.get("capture_region")):
                return stop("stale_capture")
            result = action(target_id=chosen["id"], target=targets[[x["id"] for x in options].index(chosen["id"])],
                            image_path=shot["image_path"], action=chosen["action"], safe_purpose=chosen["safe_purpose"],
                            deadline=deadline)
            if result.get("status") != "ok" or result.get("executed_steps") != 1: return stop("action_failed")
            if not same_window(): return stop("wrong_window")
            after = capture()
            if not after.get("sha256") or after["sha256"] == shot["sha256"]: return stop("unverified_transition")
            completed.append({"index": index, "candidate_id": chosen["id"], "verified_change": True,
                              "semantic_verified": False, "decision_ms": proposal.get("latency_ms")})
            if stage.get("expected_target"):
                _, error = observe_ready([stage["expected_target"]], wait_timeout_ms=stage.get("wait_timeout_ms"))
                if error: return stop("checkpoint_unverified")
                completed[-1]["semantic_verified"] = True
                completed[-1]["checkpoint_id"] = stage["expected_target"]["id"]
            previous_action = chosen["id"]
        if time.monotonic() >= deadline: return stop("deadline")
        final, error = observe_ready([completion_target])
        if time.monotonic() >= deadline: return stop("deadline")
        if error: return stop("completion_unverified" if error == "untrusted_grounding" else error)
        completed[-1]["semantic_verified"] = True
        return {"status": "completed", "verified_completion": True, "executed_stages": len(completed),
                "stages": completed, "duration_ms": round((time.monotonic()-started)*1000, 1)}
    except Exception:
        return stop("runtime_error")

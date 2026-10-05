"""Read-only closed-set THEIA decisions; provider adapters never execute UI actions."""
from __future__ import annotations

import json
import math
import os
import time
from urllib.request import Request, urlopen

API_URL = "https://api.typesafe.ai/v1/systemone"
RESERVED = {"wait", "escalate"}
PURPOSES = {"choose_option", "expand_collapse", "focus_input", "inspect", "navigate_view", "select_item"}
POSITIONS = {f"{vertical}_{horizontal}" for vertical in ("top", "middle", "bottom")
             for horizontal in ("left", "center", "right")}


class ProviderError(Exception):
    """A provider call failed; do not expose its response or credentials."""


class InvalidResponse(Exception):
    """A provider response cannot be trusted as a closed-set decision."""


class TypeSafeDecisionProvider:
    """Official TypeSafe Jev adapter. Another provider can implement choose()."""

    def __init__(self, *, opener=urlopen, timeout=10):
        self.opener = opener
        self.timeout = timeout

    def choose(self, state, criteria):
        key = os.getenv("TYPESAFE_API_KEY", "")
        if not key:
            raise ProviderError("missing credential")
        payload = {"state": state, "model": "jev-latest", "questions": {
            "next_step": {"type": "choice", "instructions":
                "Which single available step best advances the goal on this current screen? "
                "Choose wait if the UI is changing; escalate if uncertain or the action requires authorization.",
                "criteria": criteria}}}
        request = Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}, method="POST")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise InvalidResponse("response too large")
            return json.loads(raw)["answers"]["next_step"]
        except InvalidResponse:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError("provider unavailable") from exc


def _valid_candidates(candidates):
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 16:
        return False
    ids = []
    for item in candidates:
        if not isinstance(item, dict) or item.get("risk") != "non_destructive":
            return False
        name, description = item.get("id"), item.get("description")
        if not isinstance(name, str) or not name.isascii() or not name or len(name) > 64 or not all(c.isalnum() or c == "_" for c in name) or name in RESERVED:
            return False
        if not isinstance(description, str) or not description.strip() or len(description) > 256:
            return False
        ids.append(name)
    return len(set(ids)) == len(ids)


def _validated_answer(answer, allowed):
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise InvalidResponse("not a choice")
    choice, probabilities, confidence = answer.get("choice"), answer.get("probabilities"), answer.get("confidence")
    if not isinstance(choice, str) or choice not in allowed or not isinstance(probabilities, dict) or set(probabilities) != set(allowed):
        raise InvalidResponse("unknown choice or distribution")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p < 0 or p > 1 for p in probabilities.values()):
        raise InvalidResponse("invalid probabilities")
    if abs(sum(probabilities.values()) - 1) > 0.01 or probabilities[choice] != max(probabilities.values()):
        raise InvalidResponse("inconsistent distribution")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise InvalidResponse("invalid confidence")
    return choice, float(confidence)


def _valid_manifest(manifest, candidates):
    if not isinstance(manifest, dict) or set(manifest) != {"stage_index", "stage_count", "previous_verified", "visible"}:
        return False
    index, count = manifest["stage_index"], manifest["stage_count"]
    if (type(index) is not int or type(count) is not int or not 1 <= count <= 4 or
        not 0 <= index < count or type(manifest["previous_verified"]) is not bool):
        return False
    visible = manifest["visible"]
    if not isinstance(visible, list) or len(visible) != len(candidates):
        return False
    for item, candidate in zip(visible, candidates):
        if (not isinstance(item, dict) or set(item) != {"id", "description", "purpose", "position"} or
            item["id"] != candidate["id"] or item["description"] != candidate["description"] or
            type(item["purpose"]) is not str or item["purpose"] not in PURPOSES or
            type(item["position"]) is not str or item["position"] not in POSITIONS):
            return False
    return True


def decide_next_step(provider, *, goal, window, candidates, snapshot_id, previous_action=None,
                     min_confidence=0.75, grounding_manifest=None):
    """Return a proposal tied to a capture; caller must verify provenance and safety.

    No screenshot, coordinates, or action tool is invoked here. Do not put secrets
    or private UI contents in goal/window/candidate descriptions sent to a cloud.
    """
    if not _valid_candidates(candidates):
        return {"status": "escalate", "reason": "invalid_candidates"}
    if not all(isinstance(v, str) and 0 < len(v) <= 512 for v in (goal, window, snapshot_id)):
        return {"status": "escalate", "reason": "invalid_state"}
    if previous_action is not None and (not isinstance(previous_action, str) or len(previous_action) > 256):
        return {"status": "escalate", "reason": "invalid_state"}
    if not isinstance(min_confidence, (int, float)) or isinstance(min_confidence, bool) or not 0 <= min_confidence <= 1:
        return {"status": "escalate", "reason": "invalid_threshold"}
    if grounding_manifest is not None and not _valid_manifest(grounding_manifest, candidates):
        return {"status": "escalate", "reason": "invalid_grounding_manifest"}
    criteria = {item["id"]: item["description"] for item in candidates}
    criteria.update({"wait": "UI is changing; observe again without acting",
                     "escalate": "Insufficient evidence or requires agent/user decision"})
    state = {"goal": goal, "window": window, "snapshot_id": snapshot_id,
             "previous_action": previous_action, "candidates": [
                 {"id": item["id"], "description": item["description"]} for item in candidates]}
    if grounding_manifest is not None:
        state["grounding_manifest"] = grounding_manifest
    started = time.monotonic()
    try:
        answer = provider.choose(state, criteria)
    except ProviderError:
        return {"status": "escalate", "reason": "provider_error"}
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    try:
        choice, confidence = _validated_answer(answer, criteria)
    except InvalidResponse:
        return {"status": "escalate", "reason": "invalid_provider_response"}
    if choice == "escalate" or confidence < min_confidence:
        return {"status": "escalate", "reason": "model_escalation" if choice == "escalate" else "low_confidence",
                "confidence": confidence, "latency_ms": elapsed_ms}
    if choice == "wait":
        return {"status": "wait", "snapshot_id": snapshot_id, "confidence": confidence,
                "latency_ms": elapsed_ms}
    return {"status": "proposed", "candidate_id": choice, "snapshot_id": snapshot_id,
            "confidence": confidence, "latency_ms": elapsed_ms,
            "note": "Decision only; recapture/verify provenance and safety before any action."}

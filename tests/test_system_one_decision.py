import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from system_one_decision import TypeSafeDecisionProvider, decide_next_step


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return json.dumps(self.payload).encode()[:size]


def sample_candidates():
    return [{"id": "search", "description": "Focus search field", "risk": "non_destructive"},
            {"id": "help", "description": "Open help menu", "risk": "non_destructive"}]


def test_jev_choice_returns_proposal_without_coordinates_or_action(monkeypatch):
    recorded = {}
    def fake_open(request, timeout):
        recorded['url'] = request.full_url
        recorded['timeout'] = timeout
        recorded['headers'] = dict(request.header_items())
        recorded['body'] = json.loads(request.data)
        return FakeResponse({"model": "jev-1.13.0", "answers": {"next_step": {
            "type": "choice", "choice": "search", "probabilities": {
                "search": 0.91, "help": 0.04, "wait": 0.03, "escalate": 0.02},
            "confidence": 0.89}}, "usage": {"input_tokens": 50, "output_tokens": 12}})
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-secret')
    provider = TypeSafeDecisionProvider(opener=fake_open)
    result = decide_next_step(provider, goal='Find documentation', window='Test App',
                              candidates=sample_candidates(), snapshot_id='capture-1')
    assert result['status'] == 'proposed'
    assert result['candidate_id'] == 'search'
    assert 'x' not in result and 'action' not in result
    assert recorded['url'] == 'https://api.typesafe.ai/v1/systemone'
    assert recorded['headers']['Authorization'] == 'Bearer test-only-secret'
    assert recorded['headers']['User-agent'].startswith('Mozilla/5.0')
    assert recorded['body']['model'] == 'jev-latest'
    assert recorded['body']['questions']['next_step']['type'] == 'choice'
    assert set(recorded['body']['questions']['next_step']['criteria']) == {'search', 'help', 'wait', 'escalate'}
    assert recorded['body']['state']['snapshot_id'] == 'capture-1'


def test_no_key_fails_closed_before_network(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    provider = TypeSafeDecisionProvider(opener=lambda *a, **k: pytest.fail('network called'))
    result = decide_next_step(provider, goal='Find documentation', window='Test App',
                              candidates=sample_candidates(), snapshot_id='capture-1')
    assert result['status'] == 'escalate'
    assert result['reason'] == 'provider_error'
    assert 'secret' not in json.dumps(result)


def test_unknown_choice_and_bad_distribution_fail_closed(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-secret')
    for answer in [
        {"type": "choice", "choice": "submit", "probabilities": {"submit": 1.0}, "confidence": 1.0},
        {"type": "choice", "choice": ["search"], "probabilities": {"search": 1.0}, "confidence": 1.0},
        {"type": "choice", "choice": "search", "probabilities": {"search": 0.9, "help": 0.2, "wait": 0, "escalate": 0}, "confidence": 0.9},
    ]:
        provider = TypeSafeDecisionProvider(opener=lambda *a, **k: FakeResponse({"answers": {"next_step": answer}}))
        result = decide_next_step(provider, goal='Find documentation', window='Test App',
                                  candidates=sample_candidates(), snapshot_id='capture-1')
        assert result['status'] == 'escalate'
        assert result['reason'] == 'invalid_provider_response'


def test_low_confidence_escalates(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-secret')
    answer = {"type": "choice", "choice": "search", "probabilities": {
        "search": 0.4, "help": 0.3, "wait": 0.2, "escalate": 0.1}, "confidence": 0.2}
    provider = TypeSafeDecisionProvider(opener=lambda *a, **k: FakeResponse({"answers": {"next_step": answer}}))
    result = decide_next_step(provider, goal='Find documentation', window='Test App',
                              candidates=sample_candidates(), snapshot_id='capture-1')
    assert result['status'] == 'escalate'
    assert result['reason'] == 'low_confidence'


def test_theia_registers_decision_only_tool_and_missing_key_escalates(monkeypatch):
    import windows_computer_use
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    class Ctx:
        tools = []
        def register_tool(self, **kwargs):
            self.tools.append(kwargs)
    ctx = Ctx()
    windows_computer_use.register_tools(ctx)
    tool = next(t for t in ctx.tools if t['name'] == 'computer_use_decide_next')
    assert tool['schema']['parameters']['required'] == ['goal', 'window', 'snapshot_id', 'candidates']
    result = json.loads(tool['handler']({'goal': 'Find documentation', 'window': 'Test App',
                'snapshot_id': 'capture-1', 'candidates': sample_candidates()}))
    assert result['status'] == 'escalate'
    assert result['reason'] == 'provider_error'


def test_rejects_unsafe_or_duplicate_candidates_before_network():
    provider = TypeSafeDecisionProvider(opener=lambda *a, **k: pytest.fail('network called'))
    for candidates in [
        [{"id": "pay", "description": "Pay invoice", "risk": "consequential"}],
        [{"id": "x", "description": "One", "risk": "non_destructive"},
         {"id": "x", "description": "Two", "risk": "non_destructive"}],
    ]:
        result = decide_next_step(provider, goal='Test', window='Test App',
                                  candidates=candidates, snapshot_id='capture-1')
        assert result['status'] == 'escalate'
        assert result['reason'] == 'invalid_candidates'


def test_grounded_manifest_reaches_jev_as_structured_state_without_coordinates():
    captured = {}
    class Provider:
        def choose(self, state, criteria):
            captured.update(state)
            return {'type': 'choice', 'choice': 'search', 'probabilities': {
                'search': 0.9, 'help': 0.05, 'wait': 0.03, 'escalate': 0.02}, 'confidence': 0.9}
    manifest = {'stage_index': 0, 'stage_count': 2, 'previous_verified': False,
                'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'top_left'},
                            {'id': 'help', 'description': 'Open help menu', 'purpose': 'inspect', 'position': 'bottom_right'}]}
    result = decide_next_step(Provider(), goal='Find documentation', window='Test App',
                              candidates=sample_candidates(), snapshot_id='capture-1',
                              grounding_manifest=manifest)
    assert result['candidate_id'] == 'search'
    assert captured['grounding_manifest'] == manifest
    assert '"x"' not in json.dumps(captured) and '"y"' not in json.dumps(captured)


@pytest.mark.parametrize('change', [
    {'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'top_left', 'x': 999}]},
    {'visible': [{'id': 'pay', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'top_left'}]},
    {'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'offscreen'}]},
    {'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': ['focus_input'], 'position': 'top_left'},
                 {'id': 'help', 'description': 'Open help menu', 'purpose': 'inspect', 'position': 'bottom_right'}]},
])
def test_malformed_grounding_manifest_fails_before_provider(change):
    manifest = {'stage_index': 0, 'stage_count': 1, 'previous_verified': False,
                'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'top_left'},
                            {'id': 'help', 'description': 'Open help menu', 'purpose': 'inspect', 'position': 'bottom_right'}]}
    manifest.update(change)
    class Provider:
        def choose(self, *args): pytest.fail('provider called')
    result = decide_next_step(Provider(), goal='Find documentation', window='Test App',
                              candidates=sample_candidates(), snapshot_id='capture-1',
                              grounding_manifest=manifest)
    assert result['status'] == 'escalate' and result['reason'] == 'invalid_grounding_manifest'


def test_registered_jev_tool_accepts_manifest_and_transmits_only_compact_state(monkeypatch):
    import urllib.request
    import windows_computer_use as ui
    captured = {}
    def fake_open(request, timeout):
        captured.update(json.loads(request.data)['state'])
        return FakeResponse({'answers': {'next_step': {'type': 'choice', 'choice': 'search',
            'probabilities': {'search': 0.9, 'help': 0.05, 'wait': 0.03, 'escalate': 0.02}, 'confidence': 0.9}}})
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-secret')
    monkeypatch.setattr(urllib.request, 'urlopen', fake_open)
    class Ctx:
        tools = []
        def register_tool(self, **kwargs): self.tools.append(kwargs)
    ctx = Ctx(); ui.register_tools(ctx)
    tool = next(t for t in ctx.tools if t['name'] == 'computer_use_decide_next')
    assert 'grounding_manifest' in tool['schema']['parameters']['properties']
    manifest = {'stage_index': 0, 'stage_count': 1, 'previous_verified': False,
                'visible': [{'id': 'search', 'description': 'Focus search field', 'purpose': 'focus_input', 'position': 'top_left'},
                            {'id': 'help', 'description': 'Open help menu', 'purpose': 'inspect', 'position': 'bottom_right'}]}
    result = json.loads(tool['handler']({'goal': 'Find documentation', 'window': 'Test App',
        'snapshot_id': 'capture-1', 'candidates': sample_candidates(), 'grounding_manifest': manifest}))
    assert result['status'] == 'proposed' and captured['grounding_manifest'] == manifest
    assert '"x"' not in json.dumps(captured) and 'image_path' not in json.dumps(captured)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from system_one_loop import run_loop
from test_system_one_loop import harness, spec


def test_expected_intermediate_checkpoint_is_semantic_not_just_changed_pixels():
    state, deps = harness()
    stages = spec()[:1]
    stages[0]['expected_target'] = {'id': 'checkpoint', 'description': 'Details heading'}
    original = deps['observe']
    def observe(targets):
        result = original(targets)
        if targets[0]['id'] == 'checkpoint':
            result['grounding']['targets'][0]['status'] = 'not_found'
        return result
    deps['observe'] = observe
    result = run_loop(goal='Open details', window='Public Demo', stages=stages,
        completion_target={'id':'done', 'description':'Done panel'}, public_context=True, **deps)
    assert result['reason'] == 'checkpoint_unverified'
    assert len(state['actions']) == 1


def test_wait_for_target_and_readiness_gate_skip_jev_for_deterministic_stage():
    state, deps = harness()
    stages = spec()[:1]
    stages[0].update(wait_for_target={'id':'ready','description':'Loaded panel'},
                     wait_timeout_ms=1000, ready_pixel=[1,2,3,4,5,0])
    seen = []
    original = deps['observe']
    deps['observe'] = lambda targets: (seen.append(targets[0]['id']) or original(targets))
    result = run_loop(goal='Open details', window='Public Demo', stages=stages,
        completion_target={'id':'done', 'description':'Done panel'}, public_context=True,
        readiness=lambda pixel: True, **deps)
    assert result['status'] == 'completed'
    assert seen[0] == 'ready'
    assert not state['decisions']
    assert result['stages'][0]['semantic_verified'] is True


def test_stage_local_deadline_is_checked_after_slow_observation(monkeypatch):
    import system_one_loop
    state,deps=harness()
    clock=[0.0]
    monkeypatch.setattr(system_one_loop.time,'monotonic',lambda: clock[0])
    original=deps['observe']
    def observe(targets):
        clock[0] += .2
        return original(targets)
    deps['observe']=observe
    stages=spec()[:1]; stages[0]['wait_timeout_ms']=100
    result=run_loop(goal='Open details',window='Public Demo',stages=stages,
        completion_target={'id':'done','description':'Done panel'},public_context=True,**deps)
    assert result['reason'] == 'target_wait_timeout'
    assert not state['actions']


def test_local_deadline_is_propagated_to_grounding_transport():
    state,deps=harness()
    remaining=[]
    def timed_observe(targets, timeout_seconds):
        remaining.append(timeout_seconds)
        return deps['observe'](targets)
    stages=spec()[:1]; stages[0]['wait_timeout_ms']=100
    result=run_loop(goal='Open details',window='Public Demo',stages=stages,
        completion_target={'id':'done','description':'Done panel'},public_context=True,
        timed_observe=timed_observe,**deps)
    assert result['status'] == 'completed'
    assert 0 < remaining[0] <= .1

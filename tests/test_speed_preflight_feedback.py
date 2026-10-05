import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_one_loop as loop
import windows_computer_use as ui


def test_navigate_description_mismatch_returns_specific_feedback_before_observation():
    candidate = dict(id='tutorial', description='Tutorial link', risk='non_destructive',
                     safe_purpose='navigate_view', action='click')
    def preflight(option):
        return ui._batch_block_reason(dict(action=option['action'], risk=option['risk'],
            target_id=option['id'], target_hint=option['description'], safe_purpose=option['safe_purpose']), 0, allow_symbolic=True)
    def forbidden(*args, **kwargs):
        raise AssertionError('unsafe plan must not observe, decide or act')
    result = loop.run_loop(goal='Read public Tutorial', window='Public',
        stages=[dict(candidates=[candidate])], completion_target=dict(id='heading', description='Tutorial heading'),
        public_context=True, observe=forbidden, capture=forbidden, decide=forbidden,
        action=forbidden, active_window=forbidden, preflight=preflight)
    assert result['reason'] == 'unsafe_candidate'
    assert result['candidate_id'] == 'tutorial'
    assert result['code'] == 'safe_purpose_description_mismatch'
    assert result['executed_stages'] == 0
    assert 'page' in result['next_step']


def test_consequential_description_remains_blocked_not_navigation_hint():
    candidate = dict(id='purchase', description='Confirm purchase page link', risk='non_destructive',
                     safe_purpose='navigate_view', action='click')
    result = loop.run_loop(goal='Read public page', window='Public',
        stages=[dict(candidates=[candidate])], completion_target=dict(id='heading', description='Heading'),
        public_context=True, observe=None, capture=None, decide=None, action=None, active_window=None,
        preflight=lambda _: "step 0 target_hint appears high-impact and is blocked")
    assert result['reason'] == 'unsafe_candidate'
    assert result['code'] == 'consequential_candidate_blocked'
    assert result['executed_stages'] == 0


def test_registered_controller_preserves_specific_consequential_feedback(monkeypatch):
    candidate=dict(id='purchase', description='Confirm purchase page link', risk='non_destructive',
                   safe_purpose='navigate_view', action='click')
    monkeypatch.setattr(ui,'_active_window',lambda: (_ for _ in ()).throw(AssertionError('preflight must finish first')))
    result=ui._jev_loop(goal='Read public page',window='Public',stages=[dict(candidates=[candidate])],
                        completion_target=dict(id='heading',description='Heading'),public_context=True)
    assert result['code']=='consequential_candidate_blocked'
    assert result['executed_stages']==0


def test_controller_checks_dpi_identity_before_observation():
    candidate=dict(id='details',description='Details page',risk='non_destructive',
                   safe_purpose='navigate_view',action='click')
    windows=iter([{'handle':1,'process_id':7,'title':'Public','dpi':96},
                  {'handle':1,'process_id':7,'title':'Public','dpi':144}])
    def forbidden(*args,**kwargs): raise AssertionError('changed DPI must stop before observation')
    result=loop.run_loop(goal='Read details',window='Public',stages=[dict(candidates=[candidate])],
        completion_target=dict(id='heading',description='Heading'),public_context=True,
        observe=forbidden,capture=forbidden,decide=forbidden,action=forbidden,
        active_window=lambda:next(windows),preflight=lambda _:None)
    assert result['reason']=='wrong_window'
    assert result['executed_stages']==0

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui


def test_keyboard_then_type_retains_guard_with_structured_recapture_guidance(monkeypatch):
    monkeypatch.setattr(ui,'_active_window',lambda: None)
    steps=[{'action':'press','keys':['END'],'risk':'non_destructive'},
           {'action':'type','text':'public text','field_hint':'Public notes text field','risk':'non_destructive'}]
    result=ui._computer_use_batch(steps=steps)
    assert result['status']=='blocked' and result['executed_steps']==0
    assert result['code']=='fresh_stage_required'
    assert result['blocked_step']==0
    assert result['next_stage']=={'after_step':0,'resume_step':1,'observation_required':True,
        'reground_remaining_targets':True,'verify_keyboard_focus':True,'automatic_retry':False}
    assert result['next_step']=='split_at_invalidating_action_recapture_verify_focus_and_reground'


def test_dynamic_workflow_reports_boundary_before_capture(monkeypatch):
    monkeypatch.setattr(ui,'_active_window',lambda: None)
    monkeypatch.setattr(ui,'_observe_stage',lambda **kw: (_ for _ in ()).throw(AssertionError('capture')))
    result=ui._dynamic_workflow(stages=[{'static_screen':True,'steps':[
        {'action':'press','keys':'end','risk':'non_destructive'},
        {'action':'press','keys':'home','risk':'non_destructive'}]}])
    assert result['status']=='blocked' and result['captures']==0
    assert result['code']=='fresh_stage_required'
    assert result['blocked_stage']==0 and result['blocked_step']==0
    assert result['next_stage']['observation_required'] is True


def test_action_program_reports_same_stage_boundary(monkeypatch):
    monkeypatch.setattr(ui,'_active_window',lambda: None)
    result=ui._computer_use_execute_code(code="press(keys='end')\npress(keys='home')",static_screen=True)
    assert result['status']=='blocked' and result['executed_steps']==0
    assert result['code']=='fresh_stage_required'
    assert result['next_stage']['automatic_retry'] is False

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui
from test_system_one_loop import harness


def test_pixel_readiness_alone_never_establishes_semantic_success(monkeypatch):
    state,deps=harness()
    monkeypatch.setattr(ui,'_active_window',deps['active_window'])
    monkeypatch.setattr(ui,'_pixel_matches',lambda *args: {'matches':True})
    observed=[]
    def observe(**kw):
        result=deps['observe'](kw['targets'])
        result['grounding']['targets'][0]['status']='not_found'
        observed.append(result)
        return result
    monkeypatch.setattr(ui,'_observe_stage',observe)
    monkeypatch.setattr(ui._speed_module('speed_runtime').time,'sleep',lambda _: None)
    result=ui._SPEED.verify_target({'id':'done','description':'Expected heading'},'Public Demo',ready_pixel=[1,2,3,4,5,0])
    assert result['semantic_verified'] is False
    assert result['reason'] == 'completion_unverified'
    assert len(observed) == 4


def test_verified_target_requires_current_native_provenance(monkeypatch):
    state,deps=harness()
    monkeypatch.setattr(ui,'_active_window',deps['active_window'])
    monkeypatch.setattr(ui,'_observe_stage',lambda **kw: deps['observe'](kw['targets']))
    result=ui._SPEED.verify_target({'id':'done','description':'Expected heading'},'Public Demo')
    assert result['status']=='verified' and result['semantic_verified'] is True
    assert result['pixels_changed_is_success'] is False
    def wrong_backend(**kw):
        result=deps['observe'](kw['targets']); result['grounding']['targets'][0]['runtime']='cli'
        return result
    monkeypatch.setattr(ui,'_observe_stage',wrong_backend)
    assert ui._SPEED.verify_target({'id':'done','description':'Expected heading'},'Public Demo')['reason']=='untrusted_grounding'

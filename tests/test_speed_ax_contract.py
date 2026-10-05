import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import speed_accessibility as ax

class Backend:
    def call_tool(self, name, args, **kwargs):
        assert name == 'get_window_state'
        assert args == dict(pid=7,window_id=17,include_screenshot=False,max_elements=200)
        return {'pid':7,'window_id':17,'snapshot_id':'s00000001','elements':[dict(element_index=1,label='Public',role='Edit',value='SECRET',enabled=False,selected=True,frame=dict(x=1,y=2,w=3,h=4),element_token='s00000001:1')], 'coordinate_space':'screen_physical_pixels'}

def test_gate_before_backend():
    assert ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17)['code']=='public_context_opt_in_required'

def test_screenshot_free_canonical_contract():
    r=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    c=r['candidates'][0]
    assert c['enabled'] is False and c['selected'] is True
    assert c['bounds']==[1,2,3,4] and c['coordinate_space']=='screen_physical_pixels'
    assert c['element_token']=='s00000001:1' and 'value' not in c and 'attributes' not in c
    assert r['screenshot_requested'] is False

def test_transport_fixed_socket():
    assert ax.InstalledDaemonBackend('driver').transport_args == ['mcp','--socket',r'\\.\pipe\cua-driver']

def test_sdk_alias_serialization_preserves_structured_only():
    class Result:
        def model_dump(self, **kwargs):
            assert kwargs == {'by_alias':True}
            return dict(isError=False,structuredContent={'elements':[]},content=[])
    assert ax.structured_result(Result())=={'elements':[]}

import pytest

@pytest.mark.parametrize('error_code',['cua_daemon_transport_unavailable','cua_transport_quarantined','cua_transport_lock_timeout'])
def test_precise_transport_error_no_raw_exception(error_code):
    class Backend:
        def call_tool(self,*args): raise ax.AdapterError(error_code)
    r=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    assert r['code']==error_code and 'error' not in r and not r['retryable']

@pytest.mark.parametrize('raw',[None,{}, {'elements':[{'frame':{}}]}])
def test_bad_structured_contract_fails_closed(raw):
    class Backend:
        def call_tool(self,*args): return raw
    assert ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)['code']=='cua_structured_contract_invalid'

@pytest.mark.parametrize('opt_in,public',[(False,False),(True,False),(False,True),(1,True)])
def test_public_gate_prevents_backend_initialization(monkeypatch,opt_in,public):
    import windows_computer_use as ui
    monkeypatch.setattr(ui,'_active_window',lambda: (_ for _ in ()).throw(AssertionError('read before gate')))
    r=ui._SPEED.accessibility_candidates('public',opt_in=opt_in,public_context=public)
    assert r['code']=='public_context_opt_in_required'

def test_sdk_unexpected_image_fails_closed():
    class Result:
        def model_dump(self,**kw): return dict(content=[dict(type='image',data='PRIVATE')],structuredContent={'elements':[]})
    with pytest.raises(ax.ContractError): ax.structured_result(Result())


def test_real_transport_lock_timeout_is_preserved_without_launch():
    backend = ax.InstalledDaemonBackend('never-launch')
    backend.lock.acquire()
    try:
        with pytest.raises(ax.AdapterError) as failure:
            backend.call_tool('get_window_state', {'include_screenshot':False}, timeout=.001)
        assert failure.value.code == 'cua_transport_lock_timeout'
        assert backend.thread is None
    finally:
        backend.lock.release()


def test_real_quarantined_transport_is_preserved_without_launch():
    backend = ax.InstalledDaemonBackend('never-launch')
    backend.failure = 'previous_timeout'
    with pytest.raises(ax.AdapterError) as failure:
        backend.call_tool('get_window_state', {'include_screenshot':False})
    assert failure.value.code == 'cua_transport_quarantined'
    assert backend.thread is None

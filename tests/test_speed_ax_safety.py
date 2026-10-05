import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from copy import deepcopy
from contextlib import asynccontextmanager
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speed_accessibility as ax


def fake_core(monkeypatch, sanitizer):
    for name in ['tools', 'tools.computer_use', 'tools.environments']:
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    backend = ModuleType('tools.computer_use.cua_backend')
    backend.sanitized_cua_driver_env = sanitizer
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    local = ModuleType('tools.environments.local')
    local._sanitize_subprocess_env = lambda env: {k:v for k,v in env.items() if k != 'OPENAI_API_KEY'}
    monkeypatch.setitem(sys.modules, local.__name__, local)


def fake_sdk(monkeypatch, captured):
    mcp = ModuleType('mcp')
    mcp.ClientSession = None
    def params(**kw):
        captured.append(kw)
        return kw
    mcp.StdioServerParameters = params
    monkeypatch.setitem(sys.modules, 'mcp', mcp)
    client = ModuleType('mcp.client')
    client.__path__ = []
    monkeypatch.setitem(sys.modules, 'mcp.client', client)
    stdio = ModuleType('mcp.client.stdio')
    @asynccontextmanager
    async def transport(params):
        raise RuntimeError('fixture stops before process launch')
        yield
    stdio.stdio_client = transport
    monkeypatch.setitem(sys.modules, stdio.__name__, stdio)


def test_proxy_uses_core_sanitizer_not_parent_environment(monkeypatch):
    captured = []
    calls = []
    monkeypatch.setenv('OPENAI_API_KEY', 'test-secret-not-real')
    fake_core(monkeypatch, lambda: calls.append(True) or {'PATH':'safe-path', 'DO_NOT_TRACK':'1'})
    fake_sdk(monkeypatch, captured)
    ax.InstalledDaemonBackend('never-launch')._run()
    assert calls == [True]
    assert captured[0]['env'].get('PATH') == 'safe-path'
    assert captured[0]['env'].get('OPENAI_API_KEY') is None
    assert captured[0]['env'].get('DO_NOT_TRACK') == '1'


def test_proxy_fails_closed_if_core_sanitizer_missing(monkeypatch):
    captured = []
    fake_core(monkeypatch, None)
    fake_sdk(monkeypatch, captured)
    backend = ax.InstalledDaemonBackend('never-launch')
    backend._run()
    assert len(captured) == 0
    assert backend.ready.is_set() and backend.failure


def test_proxy_rechecks_sanitizer_to_prevent_core_fallback(monkeypatch):
    captured = []
    fake_core(monkeypatch, lambda: {'OPENAI_API_KEY':'test-secret-not-real', 'PATH':'safe-path'})
    fake_sdk(monkeypatch, captured)
    ax.InstalledDaemonBackend('never-launch')._run()
    assert captured[0]['env'].get('OPENAI_API_KEY') is None
    assert captured[0]['env'].get('PATH') == 'safe-path'

SCHEMA = {'type':'object', 'properties':{'pid':{'type':'integer'},
    'window_id':{'type':'integer'}, 'include_screenshot':{'type':'boolean'},
    'max_elements':{'type':'integer','minimum':1}}, 'required':['pid','window_id']}

@pytest.mark.parametrize('defect', ['missing_tool','missing_screenshot','wrong_type','extra_required','wrong_limit','missing_identity_required'])
def test_proxy_refuses_incompatible_actual_tools_list(monkeypatch, defect):
    import asyncio
    captured=[]
    fake_core(monkeypatch, lambda: {'PATH':'safe'})
    fake_sdk(monkeypatch, captured)
    backend=ax.InstalledDaemonBackend('never-launch')
    schema=deepcopy(SCHEMA)
    if defect=='missing_screenshot': del schema['properties']['include_screenshot']
    if defect=='wrong_type': schema['properties']['pid']['type']='string'
    if defect=='extra_required': schema['required'].append('session')
    if defect=='wrong_limit': schema['properties']['max_elements']['minimum']=500
    if defect=='missing_identity_required': schema['required']=[]
    class Tool:
        def model_dump(self, **kw):
            return {'name':'get_window_state','inputSchema':schema}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def initialize(self):
            asyncio.get_running_loop().call_soon(backend.closed.set)
        async def list_tools(self):
            return SimpleNamespace(tools=[] if defect=='missing_tool' else [Tool()])
    sys.modules['mcp'].ClientSession=lambda *args:Session()
    @asynccontextmanager
    async def transport(params): yield (None,None)
    sys.modules['mcp.client.stdio'].stdio_client=transport
    backend._run()
    assert backend.failure and backend.session is None
    assert backend.ready.is_set()


@pytest.mark.parametrize('timeout',[float('nan'),float('inf'),-1,0,True,31])
def test_invalid_timeout_rejected_before_transport(timeout):
    backend=ax.InstalledDaemonBackend('never-launch')
    with pytest.raises(ax.ContractError):
        backend.call_tool('get_window_state',{'pid':7,'window_id':17,'include_screenshot':False,'max_elements':200},timeout=timeout)
    assert backend.thread is None


def valid_snapshot():
    return {'pid':7,'window_id':17,'snapshot_id':'s00000001',
            'elements':[{'element_index':1,'element_token':'s00000001:1',
                         'frame':{'x':1,'y':2,'w':3,'h':4}}]}

@pytest.mark.parametrize('defect',['nan','inf','huge','negative','wrong_snapshot','missing_snapshot','wrong_token','missing_index','duplicate_index','wrong_window'])
def test_candidates_reject_untrusted_snapshot_metadata(defect):
    raw=valid_snapshot()
    element=raw['elements'][0]
    if defect=='nan': element['frame']['x']=float('nan')
    if defect=='inf': element['frame']['w']=float('inf')
    if defect=='huge': element['frame']['x']=10**400
    if defect=='negative': element['frame']['w']=-1
    if defect=='wrong_snapshot': element['element_token']='s00000002:1'
    if defect=='missing_snapshot': del raw['snapshot_id']
    if defect=='wrong_token': element['element_token']='arbitrary'
    if defect=='missing_index': del element['element_index']
    if defect=='duplicate_index': raw['elements'].append(deepcopy(element))
    if defect=='wrong_window': raw['window_id']=999
    class Backend:
        def call_tool(self,*args): return raw
    result=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    assert result['status']=='blocked'
    assert result['code']=='cua_structured_contract_invalid'


def test_candidate_exposes_snapshot_local_identity():
    class Backend:
        def call_tool(self,*args): return valid_snapshot()
    result=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    assert result['snapshot_id']=='s00000001'
    assert result['candidates'][0]['snapshot_id']=='s00000001'
    assert result['candidates'][0]['id_provenance']=='snapshot_local_element_index'


def test_timeout_cancels_pending_sdk_call_and_closes_proxy(monkeypatch):
    import asyncio, threading
    backend=ax.InstalledDaemonBackend('never-launch')
    started=threading.Event()
    cancelled=threading.Event()
    cleaned=threading.Event()
    async def main():
        backend.loop=asyncio.get_running_loop()
        backend.closed=asyncio.Event()
        class Session:
            async def call_tool(self,*args):
                started.set()
                try: await asyncio.sleep(60)
                finally: cancelled.set()
        backend.session=Session()
        backend.ready.set()
        try: await backend.closed.wait()
        finally: cleaned.set()
    backend.thread=threading.Thread(target=lambda:asyncio.run(main()),daemon=True)
    backend.thread.start()
    assert backend.ready.wait(1)
    try:
        with pytest.raises(Exception):
            backend.call_tool('get_window_state',{'include_screenshot':False},timeout=.03)
        assert started.is_set()
        assert cancelled.wait(.5), 'pending SDK future not cancelled on timeout'
        assert cleaned.wait(.5), 'quarantined proxy not closed'
        assert backend.failure
    finally:
        backend.close()

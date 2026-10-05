"""Default local THEIA acquisition is fused, not a caller opt-in."""
import importlib.util
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def setup_ui(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('automatic_ui', ROOT / 'windows_computer_use.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    ui.SCRATCH_DIR = tmp_path
    window = dict(title='Private Account', handle=1, process_id=2, left=100, top=200,
                  width=20, height=10, dpi=96)
    monkeypatch.setattr(ui, '_active_window', lambda: dict(window))
    monkeypatch.setattr(ui, '_virtual_screen_bounds', lambda: dict(left=0, top=0, width=800, height=600, right=800, bottom=600))
    monkeypatch.setattr(ui, '_monitor_topology', lambda: [])
    monkeypatch.setattr(ui, '_normalize_region', lambda r, **kw: (tuple(r) if r else None, False))
    monkeypatch.setattr(ui, '_pyautogui', lambda: object())
    monkeypatch.setattr(ui, '_capture_pixels', lambda *a: Image.new('RGB', (20, 10), 'red'))
    monkeypatch.setattr(ui, '_decide_next', lambda **kw: (_ for _ in ()).throw(AssertionError('implicit external Jev')))
    monkeypatch.setattr(ui, '_external_worker_call', lambda payload, **kw: {
        'status':'found', 'runtime':'dll', 'backend':'cpp',
        'center':{'x':5,'y':5},
        'targets':[dict(t, status='found', runtime='dll', backend='cpp', center={'x':5,'y':5})
                   for t in payload.get('targets', [])]})
    return ui, window


def test_omitted_image_captures_memory_and_returns_trusted_screen_coordinates(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    result = ui._locate_batch([{'id':'a','description':'Account settings tab'}], backend='cpp')
    assert result['targets'][0]['center'] == {'x':105,'y':205}
    assert result['targets'][0]['capture_metadata_provenance'] == 'trusted_runtime_registry'
    meta = ui._load_capture_meta(result['image_path'])
    assert meta['memory_only'] is True
    assert not list(tmp_path.iterdir())


def test_automatic_locate_integrates_prepare_without_caller_opt_in(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    calls = []
    monkeypatch.setattr(ui._SPEED.prefetch, 'submit', lambda payload, **kw:
                        calls.append((payload, kw)) or {'status':'queued'})
    result = ui._locate('Account settings tab', backend='cpp')
    assert len(calls) == 1
    assert calls[0][0]['image_path'] == result[0]['image_path']
    assert calls[0][1]['opt_in'] is True
    assert result[0]['center'] == {'x':105,'y':205}


def test_observe_default_integrates_memory_capture_and_resident_prepare(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    events = []
    monkeypatch.setattr(ui._SPEED.prefetch, 'submit', lambda payload, **kw:
                        events.append(('prepare', payload, kw)) or {'status':'queued'})
    original = ui._external_worker_call
    monkeypatch.setattr(ui, '_external_worker_call', lambda payload, **kw:
                        events.append(('locate', payload)) or original(payload, **kw))
    result = ui._observe_stage(targets=[{'id':'a','description':'Account settings tab'}])
    assert result['capture']['capture_transport'] == 'memory_rgb'
    assert events[0][0] == 'prepare'
    assert events[1][0] == 'locate'
    assert events[0][1]['image_path'] == events[1][1]['image_path']
    assert events[0][2]['captured_at'] == ui._load_capture_meta(result['capture']['image_path'])['captured_monotonic']
    assert not list(tmp_path.iterdir())


def test_find_click_refuses_pixels_changed_during_grounding(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    clicks = []
    original = ui._external_worker_call
    def locate(payload, **kw):
        monkeypatch.setattr(ui, '_capture_pixels', lambda *a: Image.new('RGB', (20, 10), 'blue'))
        return original(payload, **kw)
    monkeypatch.setattr(ui, '_external_worker_call', locate)
    monkeypatch.setattr(ui, '_click', lambda *a, **kw: clicks.append(a) or {'status':'ok'})
    result = ui._find_click('Account settings tab', backend='cpp')
    assert result['status'] == 'blocked'
    assert result['code'] == 'stale_capture'
    assert clicks == []


def test_find_click_refuses_window_switch_with_identical_pixels(monkeypatch, tmp_path):
    ui, window = setup_ui(monkeypatch, tmp_path)
    original = ui._external_worker_call
    def locate(payload, **kw):
        window['handle'] = 3
        return original(payload, **kw)
    monkeypatch.setattr(ui, '_external_worker_call', locate)
    monkeypatch.setattr(ui, '_click', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('unsafe click')))
    result = ui._find_click('Account settings tab', backend='cpp')
    assert result['status'] == 'blocked'
    assert result['code'] == 'stale_capture'


def test_automatic_prepare_discarded_after_scope_invalidation(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    queued = []
    monkeypatch.setattr(ui._SPEED.prefetch, 'submit', lambda payload, **kw:
                        queued.append(payload) or {'status':'queued'})
    ui._locate_batch([{'id':'a','description':'Account settings tab'}], backend='cpp')
    ui._SPEED.invalidate('navigation')
    monkeypatch.setattr(ui, '_external_worker_call', lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError('stale prepare sent')))
    import time
    result = ui._SPEED._prepare({**queued[0], '_prefetch_deadline':time.monotonic()+2})
    assert result['status'] == 'discarded'
    assert result['code'] == 'scope_invalidated'


def test_symbolic_action_default_refuses_changed_pixels(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    original = ui._external_worker_call
    def locate(payload, **kw):
        monkeypatch.setattr(ui, '_capture_pixels', lambda *a: Image.new('RGB', (20, 10), 'blue'))
        return original(payload, **kw)
    monkeypatch.setattr(ui, '_external_worker_call', locate)
    clicks = []
    monkeypatch.setattr(ui, '_click', lambda **kw: clicks.append(kw) or {'status':'ok'})
    result = ui._computer_use_batch(targets=[{'id':'a','description':'Account settings tab'}],
        backend='cpp', static_screen=True,
        steps=[{'action':'click','target_id':'a','target_hint':'Account settings tab',
                'safe_purpose':'navigate_view','risk':'non_destructive'}])
    assert result['status'] == 'blocked'
    assert result['executed_steps'] == 0
    assert clicks == []



def test_explicit_non_native_observe_keeps_file_transport(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    def locate(**kw):
        assert Path(kw['image_path']).exists()
        return {'status':'found','targets':[]}
    monkeypatch.setattr(ui, '_locate_batch', locate)
    result = ui._observe_stage(targets=[{'id':'a','description':'Settings tab'}], backend='internal')
    assert result['capture']['capture_transport'] == 'png_evidence'


def test_registered_guidance_prefers_automatic_pixels_for_known_targets():
    spec = importlib.util.spec_from_file_location('guidance_ui', ROOT / 'windows_computer_use.py')
    ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(ui)
    class Context:
        def __init__(self): self.tools=[]
        def register_tool(self, **kw): self.tools.append(kw)
    ctx=Context(); ui.register_tools(ctx)
    tools={t['name']:t for t in ctx.tools}
    for name in ['computer_use_observe_stage','computer_use_locate','computer_use_locate_batch',
                 'computer_use_find_click','computer_use_batch','computer_use_verify_target']:
        description=tools[name]['schema']['description'].lower()
        assert 'no separate capture' in description
    assert 'unknown' in tools['computer_use_capture_screen']['schema']['description'].lower()


def test_verification_acquires_new_memory_pixels_each_call(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    target={'id':'a','description':'Account settings heading'}
    first=ui._SPEED.verify_target(target, 'Private Account')
    second=ui._SPEED.verify_target(target, 'Private Account')
    assert first['status'] == second['status'] == 'verified'
    assert first['evidence']['capture']['image_path'] != second['evidence']['capture']['image_path']
    assert first['evidence']['capture']['capture_transport'] == 'memory_rgb'
    assert not list(tmp_path.iterdir())


def test_find_click_unchanged_private_screen_acts_with_internal_pixels(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    clicks=[]
    monkeypatch.setattr(ui, '_click', lambda *args, **kw: clicks.append(args) or {'status':'ok'})
    result=ui._find_click('Account settings tab', backend='cpp')
    assert result['status'] == 'ok'
    assert clicks == [(105,205)]
    assert not list(tmp_path.iterdir())


def test_find_drag_refuses_changed_pixels_before_gesture(monkeypatch, tmp_path):
    ui, _ = setup_ui(monkeypatch, tmp_path)
    original=ui._external_worker_call
    def locate(payload, **kw):
        monkeypatch.setattr(ui, '_capture_pixels', lambda *a: Image.new('RGB',(20,10),'blue'))
        return original(payload, **kw)
    monkeypatch.setattr(ui, '_external_worker_call', locate)
    gestures=[]
    monkeypatch.setattr(ui, '_drag_path', lambda *a, **kw: gestures.append(a) or {'status':'ok'})
    result=ui._find_drag('Source item', 'Destination item', backend='cpp')
    assert result['status'] == 'blocked'
    assert gestures == []


def test_auto_backend_uses_active_native_memory_pipeline(monkeypatch, tmp_path):
    ui, _=setup_ui(monkeypatch, tmp_path)
    monkeypatch.setenv('COMPUTER_USE_LOCATE_BACKEND','cpp')
    result=ui._locate('Account settings tab', backend='auto')
    assert ui._load_capture_meta(result[0]['image_path'])['memory_only'] is True
    assert not list(tmp_path.iterdir())


def test_automatic_prepare_rechecks_scope_after_worker_admission(monkeypatch, tmp_path):
    ui, _=setup_ui(monkeypatch,tmp_path)
    context=ui._grounding_window_fingerprint()
    ui._SPEED.invalidate('overlay')
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', None)
    monkeypatch.setattr(ui, '_start_persistent_external_worker', lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError('stale engine admission')))
    import time
    result=ui._worker_transaction({'_automatic_context':context}, None, time.monotonic()+2)
    assert result['status'] == 'discarded'
    assert result['code'] == 'scope_invalidated'


def test_symbolic_click_rechecks_after_hover_overlay(monkeypatch, tmp_path):
    ui, _=setup_ui(monkeypatch,tmp_path)
    def move(**kw):
        monkeypatch.setattr(ui,'_capture_pixels',lambda *a: Image.new('RGB',(20,10),'blue'))
        return {'status':'ok'}
    monkeypatch.setattr(ui,'_move',move)
    clicks=[]
    monkeypatch.setattr(ui,'_click',lambda **kw: clicks.append(kw) or {'status':'ok'})
    result=ui._computer_use_batch(targets=[{'id':'a','description':'Account settings tab'}],
        backend='cpp',static_screen=True,steps=[
            {'action':'move','risk':'non_destructive','x':110,'y':205},
            {'action':'click','target_id':'a','target_hint':'Account settings tab',
             'safe_purpose':'navigate_view','risk':'non_destructive'}])
    assert result['status'] == 'blocked'
    assert clicks == []


def test_native_action_refuses_cli_fallback_authority(monkeypatch, tmp_path):
    ui, _=setup_ui(monkeypatch,tmp_path)
    original=ui._external_worker_call
    def locate(payload,**kw):
        result=original(payload,**kw); result['runtime']='cli'
        return result
    monkeypatch.setattr(ui,'_external_worker_call',locate)
    clicks=[]
    monkeypatch.setattr(ui,'_click',lambda *a,**kw: clicks.append(a) or {'status':'ok'})
    result=ui._find_click('Account settings tab',backend='cpp')
    assert result['status'] == 'blocked'
    assert result['code'] == 'untrusted_grounding'
    assert clicks == []


def test_memory_native_failure_never_falls_back_to_encoded_file_or_cli(monkeypatch):
    spec=importlib.util.spec_from_file_location('memory_policy_worker',ROOT/'windows_computer_use_locate_worker.py')
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    monkeypatch.setattr(worker,'_get_cpp_dll_runtime',lambda _: None)
    monkeypatch.setattr(worker,'_cpp_detect',lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError('second engine/file fallback')))
    import pytest
    with pytest.raises(RuntimeError,match='raw_memory_required'):
        worker._cpp_detect_image(Image.new('RGB',(20,10),'red'),'target','hybrid','model','cli',
                                 allow_file_fallback=False)

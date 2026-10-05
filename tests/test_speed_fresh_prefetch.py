"""Integrated capture admission: no orchestration gap or freshness weakening."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui


def test_fresh_prefetch_captures_only_expected_window_then_submits(monkeypatch):
    class Process:
        def poll(self): return None
    calls = []
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    monkeypatch.setattr(ui, '_active_window', lambda: {'title':'Public Test','handle':1,'process_id':2})
    monkeypatch.setattr(ui, '_capture_screen', lambda **kw: calls.append(('capture',kw)) or {'status':'ok','image_path':'fresh'})
    monkeypatch.setattr(ui, '_load_capture_meta', lambda p: {'metadata_provenance':'trusted_runtime_registry','captured_monotonic':time.monotonic()})
    monkeypatch.setattr(ui._SPEED.prefetch, 'submit', lambda payload, **kw: calls.append(('submit',payload,kw)) or {'status':'queued'})
    result = ui._SPEED.prefetch_frame(opt_in=True, capture_fresh=True, window='Public Test')
    assert result['status'] == 'queued'
    assert result['capture']['image_path'] == 'fresh'
    assert calls[0] == ('capture',{'scope':'active_window','_materialize':False})
    assert calls[1][1]['image_path'] == 'fresh'
    assert calls[1][2]['opt_in'] is True


def test_fresh_prefetch_does_not_capture_wrong_window(monkeypatch):
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    monkeypatch.setattr(ui, '_active_window', lambda: {'title':'Private','handle':1,'process_id':2})
    monkeypatch.setattr(ui, '_capture_screen', lambda **kw: (_ for _ in ()).throw(AssertionError('capture')))
    result = ui._SPEED.prefetch_frame(opt_in=True, capture_fresh=True, window='Public Test')
    assert result['reason'] == 'wrong_window'


def test_fresh_prefetch_refuses_window_switch_before_submit(monkeypatch):
    class Process:
        def poll(self): return None
    windows=iter([{'title':'Public Test','handle':1,'process_id':2}, {'title':'Other','handle':3,'process_id':4}])
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    monkeypatch.setattr(ui, '_active_window', lambda: next(windows))
    monkeypatch.setattr(ui, '_capture_screen', lambda **kw: {'status':'ok','image_path':'fresh'})
    monkeypatch.setattr(ui._SPEED.prefetch, 'submit', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('submit')))
    result = ui._SPEED.prefetch_frame(opt_in=True, capture_fresh=True, window='Public Test')
    assert result['reason'] == 'wrong_window'


def test_fresh_prefetch_schema_exposes_single_call_window_guard():
    class Context:
        def __init__(self): self.tools=[]
        def register_tool(self, **kw): self.tools.append(kw)
    ctx=Context(); ui.register_tools(ctx)
    tool=next(t for t in ctx.tools if t['name']=='computer_use_prefetch_frame')
    props=tool['schema']['parameters']['properties']
    assert props['capture_fresh']['default'] is False
    assert 'window' in props

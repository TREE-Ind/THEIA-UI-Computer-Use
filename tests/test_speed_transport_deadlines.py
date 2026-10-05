import sys,time,threading,io
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui
from speed_prefetch import WorkerAdmission


def test_admission_deadline_no_unbounded_wait():
    a=WorkerAdmission()
    with a.enter():
        with pytest.raises(TimeoutError):
            with a.enter(True,deadline=time.monotonic()+.02): pass
    assert a.foreground==0 and not a.busy


def setup_worker(monkeypatch):
    proc=SimpleNamespace(stdin=io.StringIO(),poll=lambda:None)
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_PROC',proc)
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_PYTHON','python')
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_SIGNATURE',('same',))
    monkeypatch.setattr(ui,'_external_worker_signature',lambda _:('same',))
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_QUEUE',Queue())
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_QUARANTINE',None,raising=False)
    monkeypatch.setattr(ui,'_start_persistent_external_worker',lambda _: (_ for _ in ()).throw(AssertionError('speculative start')))
    monkeypatch.setattr(ui,'_dispose_external_worker_locked',lambda: (_ for _ in ()).throw(AssertionError('dispose')))
    return proc


def test_speculative_timeout_quarantines_without_dispose(monkeypatch):
    proc=setup_worker(monkeypatch)
    r=ui._call_persistent_external_worker({'_speculative':True,'_prefetch_deadline':time.monotonic()+.03},timeout=.03)
    assert r['code']=='worker_transport_timeout' and r['worker_restarted'] is False
    assert ui._EXTERNAL_WORKER_PROC is proc and ui._EXTERNAL_WORKER_QUARANTINE
    r=ui._call_persistent_external_worker({},timeout=.03)
    assert r['code']=='worker_transport_quarantined'


def test_transport_lock_deadline(monkeypatch):
    setup_worker(monkeypatch)
    with ui._EXTERNAL_WORKER_CALL_LOCK:
        start=time.monotonic()
        r=ui._call_persistent_external_worker({'_speculative':True,'_prefetch_deadline':start+.02},timeout=.02)
        assert time.monotonic()-start<.3
        assert r['code']=='worker_admission_timeout'

def test_capture_spends_observation_budget(monkeypatch):
    def capture(**kw):
        time.sleep(.03)
        return {'image_path':'public'}
    monkeypatch.setattr(ui,'_capture_screen',capture)
    monkeypatch.setattr(ui,'_locate_batch',lambda **kw: (_ for _ in ()).throw(AssertionError('budget exhausted before grounding')))
    monkeypatch.setattr(ui,'_result',lambda status='ok',**kw:dict(status=status,**kw))
    r=ui._observe_stage(targets=[{'id':'a','description':'Public'}],timeout_seconds=.01)
    assert r['code']=='capture_deadline' and r['native_call_cancelled'] is False

def test_speculative_invalid_json_quarantines(monkeypatch):
    setup_worker(monkeypatch)
    ui._EXTERNAL_WORKER_QUEUE.put('invalid')
    r=ui._call_persistent_external_worker({'_speculative':True,'_prefetch_deadline':time.monotonic()+1},timeout=.1)
    assert r['code']=='worker_transport_error' and not r['worker_restarted']

def test_worker_start_lock_bounded(monkeypatch):
    monkeypatch.setattr(ui,'_external_python_path',lambda _:sys.executable)
    with ui._EXTERNAL_WORKER_LOCK:
        r=ui._start_persistent_external_worker(deadline=time.monotonic()+.02)
        assert r['code']=='worker_startup_deadline'

def test_direct_warm_cannot_clear_quarantine(monkeypatch):
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_QUARANTINE','timeout')
    monkeypatch.setattr(ui,'_external_python_path',lambda _: (_ for _ in ()).throw(AssertionError('resolve or restart')))
    assert ui._start_persistent_external_worker()['code']=='worker_transport_quarantined'

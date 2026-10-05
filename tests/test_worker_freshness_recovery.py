"""Synthetic JSONL transport only: never loads native weights or captures UI."""
import io
import json
import threading
import time
from queue import Queue, Empty
from types import SimpleNamespace
import pytest
import windows_computer_use as ui


def worker(monkeypatch):
    q = Queue()
    proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', proc)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PYTHON', 'fixture')
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_SIGNATURE', ('same',))
    monkeypatch.setattr(ui, '_external_worker_signature', lambda _: ('same',))
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUEUE', q)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', None)
    monkeypatch.setattr(ui, '_start_persistent_external_worker', lambda *a, **kw: {'status':'ok'})
    return proc, q


def test_expired_prepare_response_is_drained_not_transport_quarantined(monkeypatch):
    proc, q = worker(monkeypatch)
    # A queue seam advances the freshness clock deterministically after write.
    clock = [10.0]
    monkeypatch.setattr(ui.time, 'monotonic', lambda: clock[0])
    def get(timeout):
        clock[0] = 10.1
        if timeout < .1:
            raise Empty
        request = json.loads(proc.stdin.getvalue().splitlines()[-1])
        return json.dumps({'request_id':request['request_id'], 'status':'prepared'})
    monkeypatch.setattr(q, 'get', get)
    result = ui._call_persistent_external_worker(
        {'action':'prepare_frame','_speculative':True,'_prefetch_deadline':10.05}, timeout=1)
    assert result['status'] == 'discarded'
    assert result['code'] == 'stale_frame'
    assert result['response_drained'] is True
    assert ui._EXTERNAL_WORKER_QUARANTINE is None
    result = ui._call_persistent_external_worker({'action':'warm'}, timeout=1)
    assert result['status'] == 'prepared'


def test_prepare_runtime_keeps_transport_budget_separate_from_freshness(monkeypatch):
    worker(monkeypatch)
    calls = []
    monkeypatch.setattr(ui, '_external_worker_call', lambda payload, **kw: calls.append(kw) or {'status':'prepared'})
    ui._SPEED._prepare({'_prefetch_deadline':time.monotonic()+.01})
    assert calls == [{}]


def test_quarantine_status_is_screenshot_free(monkeypatch):
    worker(monkeypatch)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', 'timeout')
    result = ui._worker_transport_status()
    assert result['quarantine_reason'] == 'timeout'
    assert result['native_call_cancelled'] is False
    assert result['recovery']['tool'] == 'computer_use_recover_worker'


def test_recovery_requires_authorization_and_confirmed_exit(monkeypatch):
    proc, _ = worker(monkeypatch)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', 'timeout')
    calls=[]
    proc.terminate=lambda: calls.append('terminate')
    proc.wait=lambda timeout: (_ for _ in ()).throw(ui.subprocess.TimeoutExpired('fixture',timeout))
    assert ui._recover_worker()['code'] == 'worker_recovery_authorization_required'
    assert calls == []
    assert ui._recover_worker(authorize=True, timeout_seconds=.1)['code'] == 'worker_exit_unconfirmed'
    assert ui._EXTERNAL_WORKER_PROC is proc
    assert ui._EXTERNAL_WORKER_QUARANTINE
    proc.wait=lambda timeout: 0
    proc.poll=lambda: 0
    result=ui._recover_worker(authorize=True, timeout_seconds=.1)
    assert result['status'] == 'ok'
    assert result['worker_restarted'] is False
    assert ui._EXTERNAL_WORKER_PROC is None
    assert ui._EXTERNAL_WORKER_QUARANTINE is None


def test_recovery_does_not_interrupt_admitted_transaction(monkeypatch):
    proc, _ = worker(monkeypatch)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', 'timeout')
    proc.terminate=lambda: (_ for _ in ()).throw(AssertionError('in-flight termination'))
    with ui._EXTERNAL_WORKER_CALL_LOCK:
        result=ui._recover_worker(authorize=True, timeout_seconds=.01)
    assert result['code'] == 'worker_recovery_busy'
    assert ui._EXTERNAL_WORKER_PROC is proc


def test_registered_tools_explain_one_local_call_and_expose_recovery():
    class Context:
        def __init__(self): self.tools = []
        def register_tool(self, **kw): self.tools.append(kw)
    ctx = Context()
    ui.register_tools(ctx)
    tools = {t['name']:t for t in ctx.tools}
    assert 'computer_use_worker_status' in tools
    assert 'computer_use_recover_worker' in tools
    for tool in tools.values():
        assert 'one local call per invocation' in tool['schema']['description']
    assert tools['computer_use_recover_worker']['schema']['parameters']['required'] == ['authorize']


@pytest.mark.parametrize('action', ['warm', 'locate'])
def test_auto_never_falls_back_to_second_engine_after_transport_block(monkeypatch, action):
    monkeypatch.setenv('COMPUTER_USE_LOCATE_BACKEND','auto')
    monkeypatch.setattr(ui, '_external_python_path', lambda _: 'fixture')
    monkeypatch.setattr(ui, '_external_worker_call', lambda *a, **kw:
                        {'status':'blocked','code':'worker_transport_quarantined'})
    monkeypatch.setattr(ui._locate_model,'load',lambda **kw:
                        (_ for _ in ()).throw(AssertionError('second engine fallback')))
    result=ui._warm(backend='auto') if action == 'warm' else ui._locate('fixture',image_path='fixture',backend='auto')[0]
    assert result['code'] == 'worker_transport_quarantined'


def test_nonpersistent_setting_cannot_bypass_quarantine(monkeypatch):
    worker(monkeypatch)
    monkeypatch.setenv('COMPUTER_USE_LOCATE_PERSISTENT','false')
    monkeypatch.setattr(ui,'_EXTERNAL_WORKER_QUARANTINE','timeout')
    monkeypatch.setattr(ui,'_run_external_locate_worker',lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError('second worker bypass')))
    result=ui._external_worker_call({'action':'warm'})
    assert result['code'] == 'worker_transport_quarantined'


@pytest.mark.parametrize('code,next_step', [
    ('worker_admission_timeout','inspect_worker_status_then_retry_fresh_stage_explicitly'),
    ('worker_recovery_busy','wait_for_owned_transaction_to_finish_then_handoff'),
    ('worker_exit_unconfirmed','retain_quarantine_and_inspect_owned_worker_exit'),
    ('worker_recovery_authorization_required','request_authorization_for_owned_worker_disposal')])
def test_worker_errors_have_actionable_guidance(code,next_step):
    from speed_errors import actionable
    result=actionable({'status':'blocked','code':code})
    assert result['next_step'] == next_step
    assert result['retryable'] is False


def test_transport_failure_logs_only_causal_telemetry(monkeypatch, caplog):
    _, q = worker(monkeypatch)
    monkeypatch.setattr(ui.time, 'monotonic', lambda: 10.0)
    monkeypatch.setattr(q, 'get', lambda **kw: (_ for _ in ()).throw(Empty))
    with caplog.at_level('WARNING'):
        result=ui._call_persistent_external_worker({'action':'prepare_frame', '_speculative':True,
            '_prefetch_deadline':11.0, 'description':'DO_NOT_LOG_PRIVATE_TEXT'}, timeout=1)
    assert result['code'] == 'worker_transport_timeout'
    assert 'theia_transport_failure' in caplog.text
    assert 'speculative=True' in caplog.text
    assert 'DO_NOT_LOG_PRIVATE_TEXT' not in caplog.text


def test_disposal_cannot_forget_worker_before_confirmed_exit(monkeypatch):
    proc, _ = worker(monkeypatch)
    proc.terminate=lambda: None
    proc.wait=lambda timeout: (_ for _ in ()).throw(ui.subprocess.TimeoutExpired('fixture',timeout))
    with pytest.raises(RuntimeError, match='worker_exit_unconfirmed'):
        ui._dispose_external_worker_locked()
    assert ui._EXTERNAL_WORKER_PROC is proc
    assert ui._EXTERNAL_WORKER_QUARANTINE == 'exit_unconfirmed'


def test_recovery_reaps_real_owned_non_native_process(monkeypatch):
    import subprocess, sys
    proc=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    worker(monkeypatch)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', proc)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', 'timeout')
    try:
        result=ui._recover_worker(authorize=True, timeout_seconds=5)
        assert result['worker_exit_confirmed'] is True
        assert proc.poll() is not None
        assert ui._EXTERNAL_WORKER_PROC is None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_quarantine_failure_has_structured_owned_worker_recovery(monkeypatch):
    worker(monkeypatch)
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_QUARANTINE', 'timeout')
    result=ui._call_persistent_external_worker({}, timeout=.1)
    assert result['quarantine_reason'] == 'timeout'
    assert result['recovery']['scope'] == 'owned_isolated_worker_only'
    assert result['native_call_cancelled'] is False

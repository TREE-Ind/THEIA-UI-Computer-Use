import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_latest_frame_prefetch_discards_superseded_without_capture():
    from speed_prefetch import LatestFramePrefetch
    entered, release = threading.Event(), threading.Event()
    calls = []
    def prepare(payload):
        calls.append(payload['image_path'])
        entered.set()
        release.wait(2)
        return {'status': 'prepared', 'runtime': 'dll'}
    queue = LatestFramePrefetch(prepare)
    assert queue.submit({'image_path': 'a'}, opt_in=False)['code'] == 'prefetch_opt_in_required'
    queue.submit({'image_path': 'a'}, opt_in=True)
    assert entered.wait(2)
    queue.submit({'image_path': 'b'}, opt_in=True)
    queue.submit({'image_path': 'c'}, opt_in=True)
    release.set()
    queue.join(3)
    assert calls == ['a', 'c']
    assert queue.status()['superseded'] >= 1
    assert queue.status()['latest_result']['status'] == 'prepared'


def test_prefetch_expires_before_native_prepare():
    from speed_prefetch import LatestFramePrefetch
    calls = []
    queue = LatestFramePrefetch(lambda p: calls.append(p))
    result = queue.submit({'image_path': 'old'}, opt_in=True, captured_at=time.monotonic()-10)
    assert result['code'] == 'stale_frame'
    assert calls == []


def test_inflight_frame_expires_before_result_can_be_published():
    from speed_prefetch import LatestFramePrefetch
    queue = LatestFramePrefetch(lambda p: (time.sleep(.03) or {'status':'prepared'}), ttl_seconds=.01)
    queue.submit({'image_path':'slow'},opt_in=True)
    queue.join(1)
    assert queue.status()['latest_result']['code'] == 'stale_frame'


def test_foreground_admission_beats_pending_speculative_work():
    from speed_prefetch import WorkerAdmission
    admission = WorkerAdmission()
    order = []
    with admission.enter():
        bg = threading.Thread(target=lambda: use(True))
        fg = threading.Thread(target=lambda: use(False))
        def use(speculative):
            with admission.enter(speculative): order.append('background' if speculative else 'foreground')
        bg.start(); fg.start()
        deadline = time.monotonic()+1
        while admission.foreground != 1 and time.monotonic() < deadline: time.sleep(.001)
        assert admission.foreground == 1
    fg.join(1); bg.join(1)
    assert order == ['foreground','background']

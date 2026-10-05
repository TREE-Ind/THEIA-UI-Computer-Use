import hashlib
import importlib.util
from multiprocessing import shared_memory
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_shared_frame_bypasses_png_decode_and_reuses_exact_pixels(monkeypatch):
    worker = load('frame_worker', 'windows_computer_use_locate_worker.py')
    rgb = Image.new('RGB', (20, 10), 'red').tobytes()
    segment = shared_memory.SharedMemory(create=True, size=len(rgb))
    segment.buf[:] = rgb
    frame = dict(name=segment.name, width=20, height=10, size=len(rgb), sha256=hashlib.sha256(rgb).hexdigest())
    stages = []
    def locate(payload):
        stage = worker._get_cpp_stage(payload['image_path'], None, 1024,
            identity=payload['image_identity'], frame_image=payload['_frame_image'])
        stages.append(stage)
        return {'status': 'found'}
    monkeypatch.setattr(worker, '_locate_batch', locate)
    monkeypatch.setattr(Image, 'open', lambda *a, **k: (_ for _ in ()).throw(AssertionError('PNG decode')))
    try:
        for path in ('first.png', 'second.png'):
            result = worker._handle(dict(action='locate_batch', backend='cpp', image_path=path,
                frame_transport=frame, request_id=path))
            assert result['status'] == 'found'
            assert result['capture_transport'] == 'shared_rgb'
        assert stages[0] is stages[1]
        assert stages[0]['image'].tobytes() == rgb
    finally:
        segment.close()
        segment.unlink()


def test_capture_transports_immutable_pixels_with_bounded_lifetime(monkeypatch, tmp_path):
    ui = load('frame_ui', 'windows_computer_use.py')
    ui.SCRATCH_DIR = tmp_path
    image = Image.new('RGB', (20, 10), 'red')
    monkeypatch.setattr(ui, '_pyautogui', lambda: object())
    monkeypatch.setattr(ui, '_normalize_region', lambda *a, **k: (None, False))
    monkeypatch.setattr(ui, '_virtual_screen_bounds', lambda: {'left': 0, 'top': 0, 'width': 20, 'height': 10})
    monkeypatch.setattr(ui, '_capture_pixels', lambda *a: image)
    shots = [ui._capture_screen() for _ in range(3)]
    image.paste('blue', (0, 0, 20, 10))
    names = []
    def call(payload, **kw):
        frame = payload['frame_transport']
        names.append(frame['name'])
        shm = shared_memory.SharedMemory(name=frame['name'])
        try:
            assert bytes(shm.buf[:frame['size']]) == Image.new('RGB', (20, 10), 'red').tobytes()
        finally:
            shm.close()
        return {'status': 'found'}
    monkeypatch.setattr(ui, '_call_persistent_external_worker', call)
    assert len(ui._CAPTURE_RGB_REGISTRY) == 2
    result = ui._external_worker_call({'action': 'locate_batch', 'backend': 'cpp', 'image_path': shots[-1]['image_path']})
    assert result['status'] == 'found'
    import pytest
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=names[0])


def test_jev_action_reuses_trusted_stage_without_second_locate(monkeypatch):
    ui = load('frame_jev_ui', 'windows_computer_use.py')
    state = {'step': 0}
    def capture(**kw):
        return {'sha256': str(state['step']), 'image_path': str(state['step']) + '.png', 'capture_region': [0, 0, 800, 600]}
    def observe(**kw):
        assert 0 < kw.get('timeout_seconds', 1000) <= 60
        return {'status': 'ok', 'capture': capture(), 'grounding': {'targets': [dict(t,
            status='found', runtime='dll', screen_coordinates_valid=True,
            capture_metadata_provenance='trusted_runtime_registry', center={'x': 100, 'y': 200}) for t in kw['targets']]}}
    monkeypatch.setattr(ui, '_active_window', lambda: {'title': 'Public Demo', 'handle': 17})
    monkeypatch.setattr(ui, '_observe_stage', observe)
    monkeypatch.setattr(ui, '_capture_screen', capture)
    def batch(**kw):
        assert not kw.get('targets'), 'redundant grounding request'
        assert kw['steps'][0]['x'] == 100
        assert kw['steps'][0]['y'] == 200
        state['step'] += 1
        return {'status': 'ok', 'executed_steps': 1}
    monkeypatch.setattr(ui, '_computer_use_batch', batch)
    result = ui._jev_loop(goal='Open help', window='Public Demo', public_context=True,
        stages=[{'candidates': [{'id': 'help', 'description': 'Help information button',
            'risk': 'non_destructive', 'safe_purpose': 'inspect', 'action': 'click'}]}],
        completion_target={'id': 'heading', 'description': 'Help heading'})
    assert result['status'] == 'completed'


def test_internal_capture_has_no_png_roundtrip(monkeypatch, tmp_path):
    ui = load('frame_memory_ui', 'windows_computer_use.py')
    ui.SCRATCH_DIR = tmp_path
    monkeypatch.setattr(ui, '_pyautogui', lambda: object())
    monkeypatch.setattr(ui, '_normalize_region', lambda *a, **k: (None, False))
    monkeypatch.setattr(ui, '_virtual_screen_bounds', lambda: {'left': 0, 'top': 0, 'width': 20, 'height': 10})
    monkeypatch.setattr(ui, '_capture_pixels', lambda *a: Image.new('RGB', (20, 10), 'red'))
    shot = ui._capture_screen(_materialize=False)
    assert not Path(shot['image_path']).exists()
    assert shot['capture_transport'] == 'memory_rgb'
    meta = ui._load_capture_meta(shot['image_path'])
    assert meta['metadata_provenance'] == 'trusted_runtime_registry'
    assert meta['sha256'] == shot['sha256']
    assert not list(tmp_path.iterdir())
    for _ in range(2):
        ui._capture_screen(_materialize=False)
    assert ui._load_capture_meta(shot['image_path']) is None


def test_jev_rejects_same_pixels_at_changed_screen_origin():
    import sys
    sys.path.insert(0, str(ROOT))
    from system_one_loop import run_loop
    from test_system_one_loop import harness, spec
    state, deps = harness()
    deps['capture'] = lambda: {'sha256': 'shot0', 'capture_region': [10, 0, 800, 600]}
    result = run_loop(goal='Open details', window='Public Demo', stages=spec(),
        completion_target={'id': 'done', 'description': 'Done panel'}, public_context=True, **deps)
    assert result['reason'] == 'stale_capture'
    assert state['actions'] == []


def test_worker_environment_isolated_from_parent_python_abi(monkeypatch):
    ui = load('frame_env_ui', 'windows_computer_use.py')
    monkeypatch.setenv('PYTHONPATH', 'foreign-python-site-packages')
    monkeypatch.setenv('PYTHONHOME', 'foreign-python-home')
    monkeypatch.setenv('COMPUTER_USE_LOCATE_BACKEND', 'cpp')
    env = ui._worker_subprocess_env()
    assert 'PYTHONPATH' not in env and 'PYTHONHOME' not in env
    assert env['COMPUTER_USE_LOCATE_BACKEND'] == 'cpp'


def test_completion_after_deadline_fails_closed(monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT))
    import system_one_loop as loop
    from test_system_one_loop import harness, spec
    _, deps = harness()
    clock = [0.0]
    original = deps['observe']
    def observe(targets):
        result = original(targets)
        if targets[0]['id'] == 'done':
            clock[0] = 61.0
        return result
    deps['observe'] = observe
    monkeypatch.setattr(loop.time, 'monotonic', lambda: clock[0])
    result = loop.run_loop(goal='Open details', window='Public Demo', stages=spec(),
        completion_target={'id': 'done', 'description': 'Done panel'}, public_context=True, **deps)
    assert result['status'] == 'escalate' and result['reason'] == 'deadline'

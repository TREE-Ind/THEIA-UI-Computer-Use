import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use_locate_worker as worker
from PIL import Image


def test_explicit_roi_widens_only_native_not_found(tmp_path, monkeypatch):
    image = tmp_path / 'frame.png'
    Image.new('RGB', (800, 600)).save(image)
    calls = []
    def detect(payload):
        calls.append(payload.copy())
        return {'status': 'not_found' if len(calls) < 3 else 'found', 'runtime': 'dll',
                'center': {'x': 400, 'y': 300}}
    monkeypatch.setattr(worker, '_locate_with_cpp', detect)
    result = worker._locate({'description': 'Details button', 'image_path': str(image),
                            'backend': 'cpp', 'region': [100, 100, 100, 100], 'roi_fallback': True,
                            'max_side': 1024})
    assert len(calls) == 3
    assert calls[0]['region'] == [100, 100, 100, 100]
    assert calls[1]['region'] == [50, 50, 200, 200]
    assert calls[2]['region'] is None
    assert all(c['max_side'] == 1024 for c in calls)
    assert result['roi_provenance']['source_size'] == [800, 600]


def test_invalid_roi_fails_before_inference(tmp_path, monkeypatch):
    image = tmp_path / 'frame.png'
    Image.new('RGB', (100, 100)).save(image)
    monkeypatch.setattr(worker, '_locate_with_cpp', lambda _: (_ for _ in ()).throw(AssertionError('GPU called')))
    result = worker._locate({'description': 'button', 'image_path': str(image), 'backend': 'cpp',
                            'region': [0, 0, 101, 20], 'roi_fallback': True})
    assert result['code'] == 'invalid_roi'

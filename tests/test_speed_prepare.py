import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use_locate_worker as worker
from PIL import Image


def test_prepare_action_uses_existing_runtime_without_decode(tmp_path, monkeypatch):
    image = tmp_path / 'frame.png'
    Image.new('RGB', (80, 60)).save(image)
    calls = []
    class Runtime:
        def prepare_rgb(self, *args, **kwargs): calls.append((args, kwargs))
    monkeypatch.setattr(worker, '_cpp_runtime_paths', lambda: ('cli', 'model'))
    monkeypatch.setattr(worker, '_get_cpp_dll_runtime', lambda _: Runtime())
    result = worker._handle({'action': 'prepare_frame', 'image_path': str(image), 'max_side': 1024})
    assert result['status'] == 'prepared'
    assert result['runtime'] == 'dll'
    assert len(calls) == 1


def test_speculative_prepare_never_cold_loads_an_engine(tmp_path, monkeypatch):
    image=tmp_path/'frame.png'; Image.new('RGB',(80,60)).save(image)
    monkeypatch.setattr(worker,'_CPP_DLL_RUNTIME',None)
    monkeypatch.setattr(worker,'_get_cpp_dll_runtime',lambda _: (_ for _ in ()).throw(AssertionError('cold load')))
    result=worker._handle({'action':'prepare_frame','image_path':str(image),'_speculative':True})
    assert result['code'] == 'resident_native_engine_required'

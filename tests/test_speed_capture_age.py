"""Freshness includes pixel acquisition, never resets after capture processing."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import windows_computer_use as ui
from speed_prefetch import LatestFramePrefetch


def test_capture_freshness_starts_before_pixel_acquisition(monkeypatch,tmp_path):
    clock=[10.0]
    monkeypatch.setattr(ui.time,'monotonic',lambda: clock[0])
    monkeypatch.setattr(ui,'SCRATCH_DIR',tmp_path)
    monkeypatch.setattr(ui,'_active_window',lambda: None)
    monkeypatch.setattr(ui,'_pyautogui',lambda: object())
    monkeypatch.setattr(ui,'_virtual_screen_bounds',lambda: {'left':0,'top':0,'width':10,'height':10})
    def pixels(*args):
        clock[0]+=2.1
        return Image.new('RGB',(10,10),'white')
    monkeypatch.setattr(ui,'_capture_pixels',pixels)
    capture=ui._capture_screen(_materialize=False)
    meta=ui._load_capture_meta(capture['image_path'])
    assert meta['captured_monotonic']==10.0
    queue=LatestFramePrefetch(lambda _: (_ for _ in ()).throw(AssertionError('expired prepare')))
    assert queue.submit({'image_path':capture['image_path']},opt_in=True,
        captured_at=meta['captured_monotonic'])['code']=='stale_frame'

import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_accessibility_candidates_preserve_metadata_never_invent_pixel_coordinates():
    from speed_accessibility import AccessibilityAdapter
    class Backend:
        def call_tool(self, name, args):
            assert name=='get_window_state' and args['include_screenshot'] is False
            return {'pid':7,'window_id':17,'snapshot_id':'s00000001','elements':[dict(element_index=1,label='Details',role='Button',frame=dict(x=10,y=20,w=80,h=30),enabled=True,selected=False,element_token='s00000001:1')]}
    result=AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    c=result['candidates'][0]
    assert c['bounds']==[10,20,80,30] and c['coordinate_space']=='driver_unmapped'
    assert c['visual_validation_required'] and 'center' not in c
    assert c['element_token']=='s00000001:1'


def test_accessibility_refuses_mismatched_element_owner():
    from speed_accessibility import AccessibilityAdapter
    class Backend:
        def call_tool(self,name,args):
            return {'pid':7,'window_id':17,'snapshot_id':'s00000001','elements':[dict(pid=99,window_id=18)]}
    assert AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)['candidates']==[]


def test_extensionless_windows_driver_is_discovered_without_install(monkeypatch, tmp_path):
    import speed_accessibility as ax
    driver = tmp_path / 'cua-driver'
    driver.write_bytes(b'MZ')
    monkeypatch.setenv('PATH', str(tmp_path))
    assert ax.discover_driver_command() == str(driver)


def test_missing_sdk_fails_closed_without_acquisition(monkeypatch):
    import speed_accessibility as ax
    import importlib.util
    import pytest
    monkeypatch.setattr(importlib.util,'find_spec',lambda _:None)
    with pytest.raises(RuntimeError,match='cua_sdk_not_installed_no_acquisition'):
        ax.installed_backend()

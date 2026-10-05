import sys, json, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui


def test_speed_tools_are_registered_with_explicit_prefetch_opt_in():
    class Ctx:
        def __init__(self): self.tools = []
        def register_tool(self, **kw): self.tools.append(kw)
    ctx = Ctx()
    ui.register_tools(ctx)
    tools = {t['name']: t for t in ctx.tools}
    assert {'computer_use_prefetch_frame','computer_use_accessibility_candidates',
            'computer_use_track_regions','computer_use_verify_target'} <= tools.keys()
    result = json.loads(tools['computer_use_prefetch_frame']['handler']({'image_path':'missing', 'opt_in':False}))
    assert result['code'] == 'prefetch_opt_in_required'


def test_layout_invalidation_epoch_changes_fingerprint(monkeypatch):
    monkeypatch.setattr(ui, '_active_window', lambda: None)
    monkeypatch.setattr(ui, '_virtual_screen_bounds', lambda: {'left':0, 'top':0, 'width':100, 'height':100})
    monkeypatch.setattr(ui, '_monitor_topology', lambda: [])
    before = ui._grounding_window_fingerprint()
    ui._SPEED.invalidate('scroll')
    after = ui._grounding_window_fingerprint()
    assert before != after


def test_geometry_reuse_rechecks_window_after_visual_capture(monkeypatch):
    fingerprints=iter([{'handle':1},{'handle':2}])
    monkeypatch.setattr(ui,'_grounding_window_fingerprint',lambda: next(fingerprints))
    monkeypatch.setattr(ui,'_verify_visual_guard',lambda _: {'matched':True})
    monkeypatch.setattr(ui,'_result',lambda status='ok',**kw: {'status':status,**kw})
    ui._GROUNDING_CACHE['race-test']={'window_fingerprint':{'handle':1},'visual_guard':{'anchors':[{}]}}
    entry,error=ui._grounding_cache_entry('race-test')
    assert entry is None and error['code']=='window_changed_during_verification'


def test_resident_prefetch_never_starts_a_new_worker(monkeypatch):
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', None)
    result = ui._SPEED.prefetch_frame(image_path='frame', opt_in=True)
    assert result['code'] == 'resident_worker_required'


def test_prefetch_rejects_sidecar_claimed_capture_time(monkeypatch):
    import time
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    monkeypatch.setattr(ui, '_load_capture_meta', lambda _: {'captured_monotonic':time.monotonic(),
                         'metadata_provenance':'verified_sidecar'})
    result=ui._SPEED.prefetch_frame(image_path='external',opt_in=True)
    assert result['code'] == 'trusted_fresh_frame_required'


def test_speculation_never_recycles_worker_on_source_change(monkeypatch):
    import time
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PYTHON', 'python')
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_SIGNATURE', ('old',))
    monkeypatch.setattr(ui, '_external_worker_signature', lambda _: ('new',))
    monkeypatch.setattr(ui, '_start_persistent_external_worker', lambda _: (_ for _ in ()).throw(AssertionError('restart')))
    result = ui._call_persistent_external_worker({'_speculative':True,
                      '_prefetch_deadline':time.monotonic()+1, 'action':'prepare_frame'})
    assert result['code'] == 'worker_reload_required'


def test_prefetch_refuses_nonpersistent_configuration(monkeypatch):
    class Process:
        def poll(self): return None
    monkeypatch.setattr(ui, '_EXTERNAL_WORKER_PROC', Process())
    monkeypatch.setenv('COMPUTER_USE_LOCATE_PERSISTENT', 'false')
    result = ui._SPEED.prefetch_frame(image_path='frame',opt_in=True)
    assert result['code'] == 'resident_worker_required'


def test_speed_schema_exposes_roi_and_checkpoint_controls():
    class Ctx:
        def __init__(self): self.tools = []
        def register_tool(self, **kw): self.tools.append(kw)
    ctx=Ctx(); ui.register_tools(ctx)
    tools={t['name']:t['schema']['parameters']['properties'] for t in ctx.tools}
    assert 'roi_fallback' in tools['computer_use_locate_batch']
    assert 'dynamic_regions' in tools['computer_use_remember_groundings']
    assert 'expected_target' in tools['computer_use_jev_loop']['stages']['items']['properties']


def test_manifest_declares_speed_tools():
    import yaml
    manifest=yaml.safe_load((Path(ui.__file__).parent/'plugin.yaml').read_text(encoding='utf-8'))
    assert {'computer_use_prefetch_frame','computer_use_accessibility_candidates',
            'computer_use_track_regions','computer_use_verify_target'} <= set(manifest['provides_tools'])


def test_remembered_control_uses_masked_context_guard(tmp_path, monkeypatch):
    from PIL import Image
    image = tmp_path / 'source.png'
    Image.new('RGB',(100,100),'white').save(image)
    monkeypatch.setattr(ui, '_locate_batch', lambda **kw: {'targets':[{'id':'a','description':'Toolbar button',
        'status':'found','center':{'x':20,'y':20},'screen_coordinates_valid':True}], 'image_path':str(image)})
    monkeypatch.setattr(ui, '_load_capture_meta', lambda _: {'screen_origin':{'x':0,'y':0},'capture_region':[0,0,100,100],
        'width':100,'height':100,'provenance':'trusted_runtime_registry'})
    monkeypatch.setattr(ui, '_grounding_window_fingerprint', lambda: {'handle':1})
    monkeypatch.setattr(ui, '_result', lambda status='ok', **kw: {'status':status,**kw})
    result = ui._remember_groundings('toolbar-test',[{'id':'a','description':'Toolbar button'}],
                                   image_path=str(image),dynamic_regions=[[0,40,100,60]])
    assert result['status'] == 'ok'
    assert ui._GROUNDING_CACHE['toolbar-test']['region_guard']['dynamic_regions'] == [[0,40,100,60]]


def test_grid_cache_conservatively_guards_complete_context(tmp_path, monkeypatch):
    from PIL import Image
    image=tmp_path/'grid.png'; Image.new('RGB',(100,100),'white').save(image)
    monkeypatch.setattr(ui,'_locate',lambda **kw: [{'status':'found','box':{'x1':10,'y1':10,'x2':90,'y2':90},
                         'screen_coordinates_valid':True,'image_path':str(image)}])
    monkeypatch.setattr(ui,'_load_capture_meta',lambda _: {'screen_origin':{'x':0,'y':0},'width':100,'height':100})
    monkeypatch.setattr(ui,'_grounding_window_fingerprint',lambda: {'handle':1})
    monkeypatch.setattr(ui,'_result',lambda status='ok',**kw: {'status':status,**kw})
    result=ui._calibrate_grid('grid-test','Public grid',4,4,image_path=str(image))
    assert result['status']=='ok'
    assert ui._GROUNDING_CACHE['grid-test']['region_guard']['dynamic_regions']==[]

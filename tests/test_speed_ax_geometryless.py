"""Firefox installed-driver structural nodes may omit frames; never promote them."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import speed_accessibility as ax
import pytest

@pytest.mark.parametrize('defect',['bad_token','duplicate_index','null_frame','empty_frame','partial_frame'])
def test_omission_does_not_weaken_snapshot_or_malformed_bounds_validation(defect):
    raw={'pid':7,'window_id':17,'snapshot_id':'s00000001','elements':[
        {'element_index':1,'element_token':'s00000001:1','role':'group'}]}
    node=raw['elements'][0]
    if defect=='bad_token': node['element_token']='wrong'
    if defect=='duplicate_index': raw['elements'].append(dict(node))
    if defect=='null_frame': node['frame']=None
    if defect=='empty_frame': node['frame']={}
    if defect=='partial_frame': node['frame']={'x':1,'y':2,'w':3}
    class Backend:
        def call_tool(self,*args): return raw
    result=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    assert result['status']=='blocked'
    assert result['code']=='cua_structured_contract_invalid'

def test_geometryless_structural_node_is_omitted_not_whole_snapshot_rejected():
    raw={'pid':7,'window_id':17,'snapshot_id':'s00000001','elements':[
        {'element_index':1,'element_token':'s00000001:1','role':'group'},
        {'element_index':2,'element_token':'s00000001:2','label':'Tutorial',
         'frame':{'x':1,'y':2,'w':30,'h':14}}]}
    class Backend:
        def call_tool(self,*args): return raw
    result=ax.AccessibilityAdapter(Backend()).candidates(pid=7,window_id=17,opt_in=True,public_context=True)
    assert result['status']=='ok'
    assert [c['id'] for c in result['candidates']]==['2']
    assert result['geometryless_elements_omitted']==1
    assert result['screenshot_requested'] is False
    assert result['candidates'][0]['visual_validation_required'] is True

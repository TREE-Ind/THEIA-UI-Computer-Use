import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from speed_errors import actionable

def test_stale_geometry_without_explicit_reason_is_not_backend_failure():
    source={'status':'stale','error':'cached grounding invalid because active window/screen geometry changed; recapture and recalibrate','cache_id':'test'}
    result=actionable(source,'_reuse_groundings')
    assert result['status']=='stale' and result['error']==source['error']
    assert result['code']=='stale_capture'
    assert result['next_step']=='recapture_and_reground'
    assert result['retryable'] is False

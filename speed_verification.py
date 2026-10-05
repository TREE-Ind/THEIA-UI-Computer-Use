"""Targeted semantic postcondition verification. Readiness is never a success predicate."""
import time


def verify(runtime, target, window, region=None, ready_pixel=None, max_duration_ms=10000):
    ui = runtime.ui
    loop = runtime.load('system_one_loop')
    if (not loop._safe_target(target) or not isinstance(window,str) or not window.strip() or
            type(max_duration_ms) is not int or not 100 <= max_duration_ms <= 30000):
        return {'status':'blocked','reason':'invalid_plan','semantic_verified':False}
    if ready_pixel is not None and (not isinstance(ready_pixel,list) or len(ready_pixel)!=6 or
            any(type(x) is not int for x in ready_pixel) or any(not 0<=x<=255 for x in ready_pixel[2:])):
        return {'status':'blocked','reason':'invalid_plan','semantic_verified':False}
    initial = ui['_active_window']()
    if not initial or not initial.get('handle') or window not in initial.get('title',''):
        return {'status':'escalate','reason':'wrong_window','semantic_verified':False}
    identity_keys = ('handle','process_id','dpi','left','top','width','height')
    identity = {key:initial.get(key) for key in identity_keys}
    deadline = time.monotonic()+max_duration_ms/1000
    def failure(reason, code=None):
        return {'status':'escalate','reason':reason,'code':code or reason,'semantic_verified':False}
    def current_window():
        current=ui['_active_window']()
        return (current and window in current.get('title','') and
                {key:current.get(key) for key in identity_keys} == identity)
    for attempt in range(4):
        if not current_window(): return failure('wrong_window')
        if time.monotonic() >= deadline: return failure('deadline')
        ready = (ready_pixel is None or ui['_pixel_matches'](
                    ready_pixel[0],ready_pixel[1],ready_pixel[2:5],ready_pixel[5]).get('matches') is True)
        if ready:
            observed=ui['_observe_stage'](targets=[target],scope='region' if region is not None else 'active_window',
                        region=region,mode='exact',backend='cpp',device='cuda',output_type='point',max_side=1024,
                        timeout_seconds=max(.001,deadline-time.monotonic()))
            if time.monotonic() >= deadline: return failure('deadline')
            if not current_window(): return failure('wrong_window')
            state=loop._grounding_state(observed,[target['id']])
            if state=='unsafe': return failure('untrusted_grounding')
            if state=='ready':
                bounds=observed['capture'].get('capture_region')
                center=observed['grounding']['targets'][0]['center']
                if (not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or
                        any(type(v) is not int for v in bounds) or bounds[2]<=0 or bounds[3]<=0 or
                        type(center.get('x')) is not int or type(center.get('y')) is not int or
                        not bounds[0]<=center['x']<bounds[0]+bounds[2] or
                        not bounds[1]<=center['y']<bounds[1]+bounds[3]):
                    return failure('untrusted_grounding')
                return {'status':'verified','semantic_verified':True,'target_id':target['id'],
                        'evidence':observed,'attempts':attempt+1,'pixels_changed_is_success':False}
        time.sleep(min(.1,max(0,deadline-time.monotonic())))
    return failure('completion_unverified', 'target_missing' if ready else 'readiness_not_met')

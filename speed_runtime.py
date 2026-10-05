"""Plugin-local integrated speed tools and state; no profile or core mutations."""
import os
import time
import threading
import functools

class SpeedRuntime:
    def __init__(self, ui, load):
        self.ui, self.load = ui, load
        self.epoch = 0
        self.reason = None
        self.lock = threading.Lock()
        prefetch = load('speed_prefetch')
        self.admission = prefetch.WorkerAdmission()
        self.prefetch = prefetch.LatestFramePrefetch(self._prepare)
        self.trackers = {}
        self.adapter = None
        self.adapter_lock = threading.Lock()

    def invalidate(self, reason):
        with self.lock:
            self.epoch += 1
            self.reason = reason

    def _prepare(self, payload):
        context = payload.get('_automatic_context')
        if context is not None and context != self.ui['_grounding_window_fingerprint']():
            return {'status':'discarded', 'code':'scope_invalidated'}
        if os.getenv('COMPUTER_USE_LOCATE_PERSISTENT', 'true').lower() in {'0','false','no','off'}:
            return {'status': 'blocked', 'code': 'resident_worker_required'}
        proc = self.ui.get('_EXTERNAL_WORKER_PROC')
        if proc is None or proc.poll() is not None:
            return {'status': 'blocked', 'code': 'resident_worker_required'}
        # The two-second TTL is checked at admission and after response drain.
        # It cannot cancel prepare_rgb once the serialized native call starts.
        return self.ui['_external_worker_call'](payload)

    def prefetch_frame(self, image_path=None, opt_in=False, status_only=False, capture_fresh=False, window=None, _context=None):
        if status_only:
            return self.prefetch.status()
        if opt_in is not True:
            return {'status': 'blocked', 'code': 'prefetch_opt_in_required', 'next_step': 'explicitly_opt_in_existing_frame'}
        if os.getenv('COMPUTER_USE_LOCATE_PERSISTENT', 'true').lower() in {'0','false','no','off'}:
            return {'status': 'blocked', 'code': 'resident_worker_required'}
        proc = self.ui.get('_EXTERNAL_WORKER_PROC')
        if proc is None or proc.poll() is not None:
            return {'status': 'blocked', 'code': 'resident_worker_required', 'next_step': 'warm_native_backend_explicitly'}
        capture = None
        if capture_fresh is True:
            if image_path or not isinstance(window, str) or not window.strip():
                return {'status':'blocked', 'code':'fresh_capture_window_required'}
            active = self.ui['_active_window']()
            if not active or window not in active.get('title', ''):
                return {'status':'escalate', 'reason':'wrong_window'}
            identity = (active.get('process_id'), active.get('handle'))
            capture = self.ui['_capture_screen'](scope='active_window', _materialize=False)
            now = self.ui['_active_window']()
            if not now or (now.get('process_id'), now.get('handle')) != identity:
                return {'status':'escalate', 'reason':'wrong_window'}
            if capture.get('status') != 'ok':
                return capture
            image_path = capture['image_path']
        meta = self.ui['_load_capture_meta'](image_path)
        if not meta or meta.get('metadata_provenance') != 'trusted_runtime_registry' or not meta.get('captured_monotonic'):
            return {'status': 'blocked', 'code': 'trusted_fresh_frame_required', 'next_step': 'explicitly_capture_intended_window'}
        result = self.prefetch.submit({'action': 'prepare_frame', 'backend': 'cpp',
                                      'image_path': image_path, 'max_side': 1024,
                                      **({'_automatic_context':_context} if _context is not None else {})},
                                     opt_in=True, captured_at=meta['captured_monotonic'])
        if capture is not None:
            result = {**result, 'capture':capture, 'capture_to_submit_ms':round((time.monotonic()-meta['captured_monotonic'])*1000, 3)}
        return result

    def prepare_capture(self, capture, backend='cpp'):
        """Fuse fresh acquisition and preparation admission, entirely locally.

        A cold worker prepares in the foreground locate request. Speculation
        never launches/recycles an engine, and its two-second deadline remains
        anchored before acquisition. This is not action authority.
        """
        if backend != 'cpp' or capture.get('capture_transport') != 'memory_rgb':
            return {'status':'skipped', 'code':'foreground_prepare'}
        return self.prefetch_frame(image_path=capture.get('image_path'), opt_in=True,
                                   _context=self.ui['_grounding_window_fingerprint']())

    def validate_action_frame(self, image_path, fingerprint, points):
        """Fresh exact full-capture comparison; no age or ROI shortcut authorizes input."""
        try:
            if fingerprint != self.ui['_grounding_window_fingerprint']():
                return False
            meta = self.ui['_load_capture_meta'](image_path)
            if not meta or meta.get('metadata_provenance') != 'trusted_runtime_registry':
                return False
            bounds = meta['capture_region']
            if any(type(x) is not int or type(y) is not int or
                   not bounds[0] <= x < bounds[0]+bounds[2] or
                   not bounds[1] <= y < bounds[1]+bounds[3] for x, y in points):
                return False
            # Retain the original bytes before the bounded registry may evict it.
            import hashlib
            original = hashlib.sha256(self._image(image_path).tobytes()).digest()
            fresh = self.ui['_capture_screen'](scope='region', region=bounds, _materialize=False)
            matched = original == hashlib.sha256(self._image(fresh['image_path']).tobytes()).digest()
            return matched and fingerprint == self.ui['_grounding_window_fingerprint']()
        except Exception:
            return False

    def _image(self, path):
        Image = self.ui['_pil_image']()
        key = os.path.abspath(str(path))
        meta = self.ui['_load_capture_meta'](path)
        with self.ui['_CAPTURE_RGB_LOCK']:
            pixels = self.ui['_CAPTURE_RGB_REGISTRY'].get(key)
        if meta and pixels:
            return Image.frombytes('RGB', (meta['width'], meta['height']), pixels)
        with Image.open(path) as image:
            return image.convert('RGB')

    def track_regions(self, image_path, regions, tracker_id='default', invalidate_event=None):
        if invalidate_event is not None:
            if invalidate_event not in {'scroll','navigation','overlay','window','dpi','layout'}:
                return {'status':'blocked', 'code':'invalid_invalidation_event'}
            self.invalidate(invalidate_event)
        if tracker_id not in self.trackers:
            if len(self.trackers) >= 16:
                self.trackers.pop(next(iter(self.trackers)))
            self.trackers[tracker_id] = self.load('speed_regions').RegionTracker()
        result = self.trackers[tracker_id].observe(self._image(image_path), regions,
                    fingerprint=self.ui['_grounding_window_fingerprint'](), epoch=self.epoch)
        return {**result, 'tracker_id': tracker_id, 'image_path': image_path,
                'coordinate_space': 'immutable_source_image', 'invalidation_epoch': self.epoch}

    def accessibility_candidates(self, window, hybrid=False, target=None, region=None, opt_in=False, public_context=False):
        if opt_in is not True or public_context is not True:
            return {"status":"blocked","code":"public_context_opt_in_required"}
        active = self.ui['_active_window']()
        if not active or not window or window not in active.get('title', ''):
            return {'status': 'escalate', 'reason': 'wrong_window'}
        identity = (active.get('process_id'), active.get('handle'))
        module = self.load('speed_accessibility')
        with self.adapter_lock:
            if self.adapter is None:
                self.adapter = module.AccessibilityAdapter(module.installed_backend())
            result = self.adapter.candidates(pid=identity[0], window_id=identity[1], opt_in=opt_in, public_context=public_context)
        now = self.ui['_active_window']()
        if not now or (now.get('process_id'), now.get('handle')) != identity:
            return {'status': 'escalate', 'reason': 'wrong_window'}
        # Hybrid returns independent authoritative visual evidence. Never promotes AX bounds to pixels.
        if hybrid:
            if not isinstance(target, dict) or set(target) != {'id','description'}:
                return {'status':'blocked', 'code':'hybrid_target_required'}
            result['visual_validation'] = self.ui['_observe_stage'](targets=[target],
                                        scope='region' if region else 'active_window', region=region,
                                        backend='cpp', mode='exact', output_type='point', max_side=1024)
        return result



    def verify_target(self, target, window, region=None, ready_pixel=None, max_duration_ms=10000):
        return self.load('speed_verification').verify(self, target, window, region, ready_pixel, max_duration_ms)

    def extend_schema(self, name, properties):
        import copy
        properties = copy.deepcopy(properties)
        region = {'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4,
                  'description':'ROI in immutable SOURCE IMAGE coordinates, never screen coordinates'}
        target = {'type':'object','properties':{'id':{'type':'string'},'description':{'type':'string'}},
                  'required':['id','description'], 'additionalProperties':False}
        if name in {'computer_use_locate','computer_use_locate_batch','computer_use_find_click'}:
            properties['region'] = region
            properties['roi_fallback'] = {'type':'boolean','default':False,
                'description':'Opt-in not_found widening; any untrusted native crop found requires full-context confirmation even when false. Score=1 never certifies hit correctness. Retains max_side and source provenance; automatic trusted ROI remains disabled.'}
        if name == 'computer_use_remember_groundings':
            properties['dynamic_regions'] = {'type':'array','maxItems':16,'items':region,
                'description':'Declared source-image content-only regions. Must not intersect retained controls. Any other pixel change invalidates geometry.'}
        if name == 'computer_use_jev_loop':
            stage = properties['stages']['items']['properties']
            stage.update(expected_target=target, wait_for_target=target,
                         wait_timeout_ms={'type':'integer','minimum':100,'maximum':10000},
                         ready_pixel={'type':'array','items':{'type':'integer'},'minItems':6,'maxItems':6,
                                      'description':'[screen_x,screen_y,R,G,B,tolerance], readiness only, never success'})
        return properties

    def register(self, register):
        target = {'type':'object', 'properties':{'id':{'type':'string'},'description':{'type':'string'}},
                  'required':['id','description']}
        region = {'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4}
        register('computer_use_prefetch_frame', 'Opt-in preparation on the SAME resident GPU worker; never launches an engine or decodes. capture_fresh=true captures the explicitly expected active window and queues preparation within this call; otherwise requires an existing trusted frame. One pending frame, foreground priority, unchanged 2-second stale discard. status_only reads telemetry.',
                 {'image_path':{'type':'string'},'opt_in':{'type':'boolean','default':False},
                  'capture_fresh':{'type':'boolean','default':False},'window':{'type':'string'},
                  'status_only':{'type':'boolean','default':False}}, [], self.prefetch_frame)
        register('computer_use_track_regions','Read exact region dirty hashes on an existing immutable frame. Unchanged regions NEVER authorize full-frame embedding reuse. Geometry still requires current visual validation; explicit invalidation events discard region stability.',
                 {'image_path':{'type':'string'},'regions':{'type':'object'},'tracker_id':{'type':'string'},
                  'invalidate_event':{'type':'string','enum':['scroll','navigation','overlay','window','dpi','layout']}},
                 ['image_path','regions'],self.track_regions)
        register('computer_use_accessibility_candidates','Read candidate metadata via installed default Hermes CUA public backend. Explicit expected active-window title required. No UIA duplicate or actions; unmapped logical bounds are NOT click coordinates. hybrid optionally obtains independent fresh native visual evidence for one supplied target.',
                 {'window':{'type':'string'},'opt_in':{'type':'boolean','default':False},'public_context':{'type':'boolean','default':False},'hybrid':{'type':'boolean','default':False},'target':target,'region':region},
                 ['window'],self.accessibility_candidates)
        register('computer_use_verify_target','Bounded targeted native semantic verification in the expected active window. Optional pixel readiness saves grounding calls but NEVER establishes success. Stops on untrusted backend, window change or deadline.',
                 {'target':target,'window':{'type':'string'},'region':region,
                  'ready_pixel':{'type':'array','items':{'type':'integer'},'minItems':6,'maxItems':6},
                  'max_duration_ms':{'type':'integer','minimum':100,'maximum':30000,'default':10000}},
                 ['target','window'],self.verify_target)

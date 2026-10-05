"""Conservative ROI policy; scores alone are never semantic correctness evidence."""
import copy
import hashlib
import math
import time


class TrustedRoiSession:
    """Source-only experimental seam, NOT a caller-serialized trust certificate.

    An internal verifier must independently return the visible target's source
    bounds from full context. Never connect it to a model score or JSON boolean.
    Exact RGB + geometry/epoch + inference options bind that witness to the next
    fresh frame. Only one witness is retained; no pixels/labels are exported.
    """
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.witness = None

    def _fresh(self, acquired):
        return (type(acquired) in (int, float) and math.isfinite(acquired)
                and 0 <= self.clock() - acquired <= 2)

    @staticmethod
    def _identity(payload, image, identity):
        return (copy.deepcopy(identity), copy.deepcopy({k: v for k, v in payload.items()
                if k not in {'_frame_image', 'image_path', 'region', 'roi_fallback'}}),
                image.size, hashlib.sha256(image.convert('RGB').tobytes()).digest())

    @staticmethod
    def _hit(result, bounds):
        point = result.get('center', {})
        x, y, w, h = bounds
        return (result.get('backend') == 'cpp' and result.get('runtime') == 'dll'
                and result.get('status') == 'found' and isinstance(point, dict)
                and type(point.get('x')) is int and type(point.get('y')) is int
                and x <= point['x'] < x + w and y <= point['y'] < y + h)

    def remember(self, payload, image, identity, acquired, result, region, *, verify):
        self.witness = None
        roi_plan(region, image.size)
        if (payload.get('backend') != 'cpp' or payload.get('region') is not None
                or not self._fresh(acquired) or not isinstance(identity, dict)
                or not {'hwnd', 'dpi', 'origin', 'epoch'} <= identity.keys()):
            return False
        before = self._identity(payload, image, identity)
        try:
            bounds = verify(image, payload['description'], copy.deepcopy(result))
            roi_plan(bounds, image.size)
        except (ValueError, TypeError, KeyError):
            return False
        x, y, w, h = region
        bx, by, bw, bh = bounds
        if (not self._fresh(acquired) or before != self._identity(payload, image, identity)
                or not self._hit(result, bounds) or not
                (x <= bx and y <= by and bx + bw <= x + w and by + bh <= y + h)):
            return False
        self.witness = (before, list(region), list(bounds))
        return True

    def locate(self, payload, image, identity, acquired, detect, *, enabled=False):
        if payload.get('region') is not None:
            roi_plan(payload['region'], image.size)
        witness = self.witness
        reason = 'disabled'
        if enabled is True:
            reason = 'missing_or_changed_witness'
            if (witness and self._fresh(acquired)
                    and witness[0] == self._identity(payload, image, identity)):
                result = detect({**payload, '_frame_image': image, 'region': witness[1]})
                if (self._fresh(acquired) and self._hit(result, witness[2])
                        and witness[0] == self._identity(payload, image, identity)):
                    return {**result, 'trusted_roi': {
                        'gate': 'exact_frame_independent_semantic_witness',
                        'full_context_inference': False, 'region': witness[1]}}
                reason = 'crop_hit_or_freshness_gate_failed'
        result = detect({**payload, '_frame_image': image, 'region': None})
        return {**result, 'trusted_roi': {'gate': reason, 'full_context_inference': True}}


def roi_plan(region, size, widen=False):
    width, height = size
    if (not isinstance(region, (tuple, list)) or len(region) != 4 or
            any(type(v) is not int for v in region)):
        raise ValueError('ROI must contain four integer source-image coordinates')
    x, y, w, h = region
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError('ROI must be positive and entirely inside the immutable source image')
    result = [list(region)]
    if widen:
        x1, y1 = max(0, x - w // 2), max(0, y - h // 2)
        x2, y2 = min(width, x + w + w // 2), min(height, y + h + h // 2)
        expanded = [x1, y1, x2 - x1, y2 - y1]
        if expanded != result[0] and expanded != [0, 0, width, height]:
            result.append(expanded)
        result.append(None)
    return result


def locate_roi(payload, detect):
    from PIL import Image
    image = payload.get('_frame_image')
    if image is None:
        with Image.open(payload['image_path']) as source:
            size = source.size
    else:
        size = image.size
    try:
        regions = roi_plan(payload['region'], size, payload.get('roi_fallback') is True)
    except ValueError as exc:
        return {'status': 'error', 'code': 'invalid_roi', 'error': str(exc),
                'next_step': 'supply_source_image_roi', 'retryable': False}
    attempts = []
    for region in regions:
        result = detect({**payload, 'region': region})
        attempts.append({'region': region, 'status': result.get('status')})
        if result.get('status') != 'not_found' or result.get('runtime') != 'dll':
            break
    # Native score/found on an excluded-target crop is not correctness evidence.
    # Untrusted explicit crops retain full-context native grounding authority.
    confirmed = region is not None and result.get('status') == 'found' and result.get('runtime') == 'dll'
    if confirmed:
        region = None
        result = detect({**payload, 'region': None})
        attempts.append({'region': None, 'status': result.get('status')})
    return {**result, 'roi_provenance': {
            'next_step': 'inspect_full_context_no_click_on_uncertainty',
            'broader_context_confirmation': confirmed,
            'coordinate_space': 'immutable_source_image',
            'source_size': list(size), 'selected_region': region, 'attempts': attempts,
            'detail_max_side': payload.get('max_side', 1024)}}

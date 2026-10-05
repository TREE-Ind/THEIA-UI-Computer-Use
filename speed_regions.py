"""Exact region dirty tracking: reusable geometry is not reusable visual embeddings."""
import hashlib
import threading

def _masked_digest(image, regions):
    masked = image.convert('RGB').copy()
    for x,y,w,h in regions:
        masked.paste((0,0,0), (x,y,x+w,y+h))
    return hashlib.sha256(masked.tobytes()).hexdigest()


def geometry_guard(image, origin, targets, dynamic_regions):
    # Declared content may change, but NEVER exclude a retained control's bounds.
    if not isinstance(dynamic_regions, list) or len(dynamic_regions) > 16:
        raise ValueError('at most sixteen dynamic regions required')
    for region in dynamic_regions:
        if (not isinstance(region, list) or len(region) != 4 or any(type(v) is not int for v in region)):
            raise ValueError('invalid dynamic region')
        x,y,w,h = region
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width or y+h > image.height:
            raise ValueError('dynamic region outside source')
    ox,oy = origin
    for target in targets.values():
        center = target['center']
        box = target.get('box') or {'x1':center['x']-16,'y1':center['y']-16,
                                     'x2':center['x']+16,'y2':center['y']+16}
        x1,y1,x2,y2 = box['x1']-ox,box['y1']-oy,box['x2']-ox,box['y2']-oy
        if not (0 <= center['x']-ox < image.width and 0 <= center['y']-oy < image.height):
            raise ValueError('control outside source')
        for x,y,w,h in dynamic_regions:
            if x1 < x+w and x2 > x and y1 < y+h and y2 > y:
                raise ValueError('retained control intersects dynamic content')
    return {'version':1, 'size':list(image.size), 'origin':list(origin),
            'dynamic_regions':dynamic_regions, 'sha256':_masked_digest(image,dynamic_regions)}


def check_geometry_guard(image, guard):
    return (list(image.size) == guard['size'] and
            _masked_digest(image, guard['dynamic_regions']) == guard['sha256'])


class RegionTracker:
    def __init__(self):
        self.previous = None
        self.lock = threading.Lock()

    def observe(self, image, regions, *, fingerprint, epoch):
        if not isinstance(regions, dict) or not 1 <= len(regions) <= 16:
            raise ValueError('one to sixteen named regions required')
        hashes = {}
        for name, region in regions.items():
            if (not isinstance(region, (list, tuple)) or len(region) != 4 or
                    any(type(v) is not int for v in region)):
                raise ValueError('invalid region coordinates')
            x, y, w, h = region
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width or y+h > image.height:
                raise ValueError('region outside immutable source')
            hashes[name] = hashlib.sha256(image.crop((x, y, x+w, y+h)).convert('RGB').tobytes()).hexdigest()
        current = {'hashes': hashes, 'regions': regions.copy(), 'size': image.size,
                   'fingerprint': fingerprint, 'epoch': epoch}
        with self.lock:
            old, self.previous = self.previous, current
        invalidated = not old or any(old[k] != current[k] for k in ('regions', 'size', 'fingerprint', 'epoch'))
        unchanged = [] if invalidated else [k for k in hashes if hashes[k] == old['hashes'].get(k)]
        return {'status': 'ok', 'dirty_regions': [k for k in hashes if k not in unchanged],
                'unchanged_regions': unchanged, 'invalidated': invalidated,
                'full_frame_embeddings_reusable': False, 'geometry_requires_visual_guard': True,
                'region_sha256': hashes}

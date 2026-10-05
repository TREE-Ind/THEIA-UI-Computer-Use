import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import speed_grounding as policy
import pytest


def native_hit(x=25, y=25):
    return {'status': 'found', 'backend': 'cpp', 'runtime': 'dll',
            'center': {'x': x, 'y': y}, 'score': 1}


def test_trusted_unchanged_verified_geometry_needs_only_crop_inference():
    cls = getattr(policy, 'TrustedRoiSession', None)
    assert callable(cls), 'missing trusted ROI policy'
    clock = [10.0]
    session = cls(clock=lambda: clock[0])
    image = Image.new('RGB', (100, 100), 'white')
    payload = {'description': 'Details button', 'backend': 'cpp', 'max_side': 1024}
    identity = {'hwnd': 10, 'dpi': 96, 'origin': [0, 0], 'epoch': 1}
    assert session.remember(payload, image, identity, 10, native_hit(), [10, 10, 30, 30],
                            verify=lambda image, description, hit: [20, 20, 10, 10])
    calls = []
    def detect(p):
        calls.append(p.get('region'))
        return native_hit()
    result = session.locate(payload, image, identity, 10, detect, enabled=True)
    assert calls == [[10, 10, 30, 30]]
    assert result['trusted_roi']['gate'] == 'exact_frame_independent_semantic_witness'
    assert result['trusted_roi']['full_context_inference'] is False
    calls.clear()
    session.locate(payload, image, identity, 10, detect)
    assert calls == [None]  # default remains off


def fixture_session():
    clock = [10.0]
    session = policy.TrustedRoiSession(clock=lambda: clock[0])
    image = Image.new('RGB', (100, 100), 'white')
    payload = {'description': 'Details button', 'backend': 'cpp', 'max_side': 1024}
    identity = {'hwnd': 10, 'dpi': 96, 'origin': [0, 0], 'epoch': 1}
    assert session.remember(payload, image, identity, 10, native_hit(), [10, 10, 30, 30],
                            verify=lambda *args: [20, 20, 10, 10])
    return session, clock, image, payload, identity


def test_changed_pixels_during_crop_cannot_use_witness():
    session, clock, image, payload, identity = fixture_session()
    calls = []
    def detect(p):
        calls.append(p['region'])
        if p['region']:
            image.putpixel((50, 50), (0, 0, 0))
        return native_hit()
    result = session.locate(payload, image, identity, 10, detect, enabled=True)
    assert calls == [[10, 10, 30, 30], None]
    assert result['trusted_roi']['full_context_inference'] is True


def test_untrusted_crop_found_is_confirmed_in_broader_context():
    calls = []
    def detect(payload):
        calls.append(payload['region'])
        return {'status': 'found' if payload['region'] else 'not_found',
                'runtime': 'dll', 'backend': 'cpp', 'score': 1,
                'center': {'x': 25, 'y': 25}}
    result = policy.locate_roi({'_frame_image': Image.new('RGB', (100, 100)),
                               'region': [0, 0, 50, 50]}, detect)
    assert calls == [[0, 0, 50, 50], None]
    assert result['status'] == 'not_found'
    assert result['roi_provenance']['broader_context_confirmation'] is True
    assert result['roi_provenance']['next_step'] == 'inspect_full_context_no_click_on_uncertainty'


def test_registered_source_schema_warns_crop_found_is_not_correctness():
    from speed_runtime import SpeedRuntime
    schema = SpeedRuntime.extend_schema(None, 'computer_use_locate', {})
    assert 'full-context confirmation' in schema['roi_fallback']['description']


@pytest.mark.parametrize('change', ['overlay', 'scroll', 'dpi', 'window', 'origin',
                                     'query', 'settings', 'stale', 'future'])
def test_uncertainty_skips_speculative_crop(change):
    session, clock, image, payload, identity = fixture_session()
    if change == 'overlay': image.putpixel((99, 99), (0, 0, 0))
    elif change == 'scroll': identity['epoch'] += 1
    elif change == 'dpi': identity['dpi'] = 144
    elif change == 'window': identity['hwnd'] = 11
    elif change == 'origin': identity['origin'] = [10, 10]
    elif change == 'query': payload['description'] = 'Other button'
    elif change == 'settings': payload['max_side'] = 640
    elif change == 'stale': clock[0] = 12.01
    elif change == 'future': clock[0] = 9
    calls = []
    result = session.locate(payload, image, identity, 10,
                            lambda p: calls.append(p['region']) or native_hit(), enabled=True)
    assert calls == [None]
    assert result['trusted_roi']['full_context_inference'] is True


@pytest.mark.parametrize('result', [native_hit(35, 35), native_hit(-1, 25),
    {**native_hit(), 'backend': 'external'}, {**native_hit(), 'runtime': 'cli'},
    {**native_hit(), 'center': {'x': float('nan'), 'y': 25}},
    {**native_hit(), 'status': 'not_found'}])
def test_native_score_does_not_replace_verified_hit_gate(result):
    session, clock, image, payload, identity = fixture_session()
    calls = []
    def detect(p):
        calls.append(p['region'])
        return result if p['region'] else native_hit()
    hit = session.locate(payload, image, identity, 10, detect, enabled=True)
    assert calls == [[10, 10, 30, 30], None]
    assert hit['trusted_roi']['full_context_inference'] is True


@pytest.mark.parametrize('bounds', [True, None, [0, 0, 101, 100],
                                     [50, 50, 10, 10], [0, 0, 5, 5]])
def test_verifier_must_independently_supply_visible_matching_target_bounds(bounds):
    session, clock, image, payload, identity = fixture_session()
    assert not session.remember(payload, image, identity, 10, native_hit(), [10, 10, 30, 30],
                                verify=lambda *args: bounds)
    assert session.witness is None


@pytest.mark.parametrize('region', [[0, 0, 101, 20], [0, 0, 0, 20], [-1, 0, 10, 10],
                                   [True, 0, 10, 10], [0., 0, 10, 10], [0, 0, 10]])
def test_malformed_proposal_never_reaches_gpu(region):
    session, clock, image, payload, identity = fixture_session()
    with pytest.raises(ValueError):
        session.locate({**payload, 'region': region}, image, identity, 10,
                       lambda p: pytest.fail('GPU called'), enabled=True)


def test_independent_verification_cannot_hide_acquisition_age():
    session, clock, image, payload, identity = fixture_session()
    def verify(*args):
        clock[0] = 12.01
        return [20, 20, 10, 10]
    assert not session.remember(payload, image, identity, 10, native_hit(), [10, 10, 30, 30], verify=verify)


def test_trust_metadata_does_not_export_pixels_or_target_text():
    session, clock, image, payload, identity = fixture_session()
    result = session.locate(payload, image, identity, 10, lambda p: native_hit(), enabled=True)
    assert set(result['trusted_roi']) == {'gate', 'region', 'full_context_inference'}


@pytest.mark.parametrize('center', [None, [], '25,25', {'x': True, 'y': 25}])
def test_malformed_native_center_is_uncertainty_not_exception(center):
    session, clock, image, payload, identity = fixture_session()
    calls = []
    def detect(p):
        calls.append(p['region'])
        return {**native_hit(), 'center': center} if p['region'] else native_hit()
    result = session.locate(payload, image, identity, 10, detect, enabled=True)
    assert calls == [[10, 10, 30, 30], None]
    assert result['trusted_roi']['full_context_inference'] is True


def test_crop_coordinates_need_only_hit_correctness_not_exact_full_coordinate_equality():
    session, clock, image, payload, identity = fixture_session()
    result = session.locate(payload, image, identity, 10, lambda p: native_hit(27, 28), enabled=True)
    assert result['center'] == {'x': 27, 'y': 28}
    assert result['trusted_roi']['full_context_inference'] is False

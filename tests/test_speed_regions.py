import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image


def test_region_dirty_tracking_never_claims_full_frame_embedding_reuse():
    from speed_regions import RegionTracker
    tracker = RegionTracker()
    first = Image.new('RGB', (128, 128), 'white')
    regions = {'toolbar': [0, 0, 128, 32], 'content': [0, 32, 128, 96]}
    tracker.observe(first, regions, fingerprint={'handle': 1}, epoch=0)
    changed = first.copy()
    changed.paste('black', (0, 64, 64, 128))
    result = tracker.observe(changed, regions, fingerprint={'handle': 1}, epoch=0)
    assert result['unchanged_regions'] == ['toolbar']
    assert result['dirty_regions'] == ['content']
    assert result['full_frame_embeddings_reusable'] is False
    invalid = tracker.observe(changed, regions, fingerprint={'handle': 1}, epoch=1)
    assert invalid['unchanged_regions'] == []
    assert invalid['invalidated'] is True

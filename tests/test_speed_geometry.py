import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image


def test_geometry_guard_allows_declared_content_only_changes_but_rejects_overlay():
    from speed_regions import geometry_guard, check_geometry_guard
    first = Image.new('RGB',(100,100),'white')
    controls = {'button':{'center':{'x':20,'y':20},'box':{'x1':10,'y1':10,'x2':30,'y2':30}}}
    guard = geometry_guard(first, (0,0), controls, [[0,40,100,60]])
    changed = first.copy(); changed.paste('black',(0,40,100,100))
    assert check_geometry_guard(changed, guard)
    changed.putpixel((50,20),(0,0,0))
    assert not check_geometry_guard(changed, guard)


def test_geometry_inside_dynamic_region_is_never_reused():
    import pytest
    from speed_regions import geometry_guard
    with pytest.raises(ValueError, match='dynamic'):
        geometry_guard(Image.new('RGB',(100,100)), (0,0),
                       {'a':{'center':{'x':50,'y':50}}}, [[0,40,100,60]])

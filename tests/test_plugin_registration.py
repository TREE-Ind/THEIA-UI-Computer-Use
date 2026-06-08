import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class FakeCtx:
    def __init__(self):
        self.tools = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

def test_plugin_registers_expected_tools():
    import windows_computer_use
    ctx = FakeCtx()
    windows_computer_use.register_tools(ctx)
    names = {t["name"] for t in ctx.tools}
    assert "computer_use_capture_screen" in names
    assert "computer_use_locate" in names
    assert "computer_use_find_click" in names
    assert "computer_use_release_all" in names
    assert len(names) >= 20
    assert all(t["toolset"] == "windows_computer_use" for t in ctx.tools)

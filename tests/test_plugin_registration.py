import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class FakeCtx:
    def __init__(self):
        self.tools = []
        self.skills = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs)
    def register_skill(self, name, path):
        self.skills.append((name, Path(path)))

def test_tool_module_registers_expected_tools():
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

def test_plugin_entrypoint_registers_tools_and_bundled_skill(monkeypatch, tmp_path):
    # Avoid mutating the real Hermes profile during plugin import smoke tests.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    spec = importlib.util.spec_from_file_location(
        "hermes_windows_computer_use_plugin",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    ctx = FakeCtx()
    module.register(ctx)

    names = {t["name"] for t in ctx.tools}
    assert "computer_use_capture_screen" in names
    assert "computer_use_get_active_window" in names
    assert len(names) >= 20
    assert ctx.skills
    skill_name, skill_path = ctx.skills[0]
    assert skill_name == "windows-computer-use"
    assert skill_path.name == "SKILL.md"
    assert skill_path.exists()

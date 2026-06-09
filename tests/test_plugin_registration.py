import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

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

def load_plugin_module(name="hermes_windows_computer_use_plugin"):
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

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
    assert any(t["name"] == "computer_use_warm" and "auto-bootstraps" in t["description"] for t in ctx.tools)


def test_manifest_advertises_cross_platform_pyautogui_support():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert {"windows", "macos", "linux"}.issubset(set(manifest["platforms"]))
    assert "pyautogui>=0.9.54" in manifest["pip_dependencies"]
    assert "pywin32>=306; platform_system == 'Windows'" in manifest["pip_dependencies"]

def test_manifest_declares_official_plugin_surfaces():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert manifest["kind"] == "standalone"
    assert "computer_use_locate" in manifest["provides_tools"]
    assert "computer_use_find_click" in manifest["provides_tools"]
    assert (ROOT / "skills" / "windows-computer-use" / "SKILL.md").exists()

def test_requirement_check_allows_pyautogui_desktop_platforms(monkeypatch):
    import windows_computer_use

    for platform_name in ("win32", "darwin", "linux"):
        monkeypatch.setattr(windows_computer_use.sys, "platform", platform_name)
        assert windows_computer_use.check_windows_computer_use_requirements() is True

    monkeypatch.setattr(windows_computer_use.sys, "platform", "freebsd")
    assert windows_computer_use.check_windows_computer_use_requirements() is False

def test_plugin_entrypoint_registers_tools_and_bundled_skill(monkeypatch, tmp_path):
    # Avoid mutating the real Hermes profile during plugin import smoke tests.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("THEIA_AUTO_INSTALL_LOCATE_WORKER", "false")
    module = load_plugin_module()

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

def test_locate_worker_bootstrap_starts_outside_hermes_venv(monkeypatch):
    module = load_plugin_module("hermes_windows_computer_use_plugin_locate_bootstrap")
    calls = []
    monkeypatch.setenv("THEIA_AUTO_INSTALL_LOCATE_WORKER", "true")
    monkeypatch.setenv("THEIA_LOCATE_TORCH", "cpu")

    class FakePopen:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)
    module._start_locate_worker_bootstrap()

    import time
    deadline = time.time() + 1
    while not calls and time.time() < deadline:
        time.sleep(0.01)
    assert calls
    command, kwargs = calls[0]

    assert command[0] == sys.executable
    assert command[1].endswith("setup_locate_worker.py")
    assert "--torch" in command
    assert "cpu" in command
    assert kwargs["stdout"] == subprocess.DEVNULL

def test_locate_tool_auto_bootstraps_when_worker_missing(monkeypatch):
    import windows_computer_use

    monkeypatch.setattr(windows_computer_use, "_external_python_path", lambda explicit=None: None)
    monkeypatch.setattr(windows_computer_use, "_start_locate_worker_bootstrap", lambda: {"status": "installing", "python": "worker-python"})

    result = windows_computer_use._warm()

    assert result["status"] == "installing"
    assert result["backend"] == "external"
    assert "basic desktop controls" in result["fallback"]

def test_basic_dependency_auto_install_uses_uv_when_missing(monkeypatch):
    module = load_plugin_module("hermes_windows_computer_use_plugin_auto_install")
    calls = []

    monkeypatch.setattr(module, "_missing_basic_dependencies", lambda: ["pyautogui"])
    monkeypatch.setattr(module.shutil, "which", lambda name: "uv" if name == "uv" else None)

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module._install_basic_dependencies_if_missing()

    assert calls
    assert calls[0][:3] == ["uv", "pip", "install"]
    assert "--python" in calls[0]
    assert "requirements-basic.txt" in calls[0][-1]

def test_basic_dependency_auto_install_respects_opt_out(monkeypatch):
    module = load_plugin_module("hermes_windows_computer_use_plugin_auto_install_opt_out")
    calls = []
    monkeypatch.setenv("THEIA_AUTO_INSTALL_BASIC_DEPS", "false")
    monkeypatch.setattr(module, "_missing_basic_dependencies", lambda: ["pyautogui"])
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: calls.append(a))

    module._install_basic_dependencies_if_missing()

    assert calls == []

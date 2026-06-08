"""Hermes Windows Computer Use plugin.

Registers the ``windows_computer_use`` toolset from a standalone Hermes
plugin and makes the bundled skill available in the active Hermes profile.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_NAME = "hermes-windows-computer-use"
_BASIC_DEPENDENCY_MODULES = {
    "pyautogui": "pyautogui",
    "PIL": "pillow",
    "pygetwindow": "pygetwindow",
}
if os.name == "nt":
    _BASIC_DEPENDENCY_MODULES["win32gui"] = "pywin32"


def _truthy_env(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _missing_basic_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name, package_name in _BASIC_DEPENDENCY_MODULES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return sorted(set(missing))


def _install_basic_dependencies_if_missing() -> None:
    """Best-effort install of THEIA's lightweight runtime dependencies.

    Hermes' plugin installer clones/enables plugins but does not currently run
    plugin requirements files or post-install scripts. To keep GitHub installs
    easy for new users, THEIA self-heals missing *basic* desktop-control deps
    on first plugin load. Heavy LocateAnything/CUDA dependencies are never
    installed here; those stay isolated in the optional external worker.

    Set THEIA_AUTO_INSTALL_BASIC_DEPS=false to disable this behavior.
    """
    if not _truthy_env("THEIA_AUTO_INSTALL_BASIC_DEPS", "true"):
        return
    missing = _missing_basic_dependencies()
    if not missing:
        return

    requirements = Path(__file__).resolve().parent / "requirements-basic.txt"
    if not requirements.exists():
        return

    commands: list[list[str]] = []
    uv = shutil.which("uv")
    if uv:
        commands.append([uv, "pip", "install", "--python", sys.executable, "-r", str(requirements)])
    commands.append([sys.executable, "-m", "pip", "install", "-r", str(requirements)])

    last_error = ""
    for command in commands:
        try:
            proc = subprocess.run(
                command,
                cwd=str(Path(__file__).resolve().parent),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if proc.returncode == 0:
            return
        last_error = (proc.stderr or proc.stdout or "").strip()[-1000:]

    print(
        "[THEIA] Basic dependency auto-install failed. "
        f"Missing: {', '.join(missing)}. "
        "Run `python -m pip install -r requirements-basic.txt` from the plugin "
        f"directory. Last error: {last_error}",
        file=sys.stderr,
    )

def _install_skill_if_missing() -> None:
    """Copy bundled SKILL.md docs into the active Hermes profile if absent.

    This is intentionally non-destructive: existing user-modified skill docs
    are left untouched. Users can run scripts/install_skill.py --force if
    they explicitly want to replace them from the plugin copy.
    """
    try:
        from hermes_constants import get_hermes_home
    except Exception:
        return
    source = Path(__file__).resolve().parent / "skills" / "windows-computer-use"
    if not source.exists():
        return
    target = Path(get_hermes_home()) / "skills" / "desktop" / "windows-computer-use"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)

def _load_tool_module():
    """Load the sibling tool module under both package and direct loaders."""
    try:
        from . import windows_computer_use  # type: ignore
        return windows_computer_use
    except Exception:
        import importlib.util
        import sys
        module_path = Path(__file__).resolve().parent / "windows_computer_use.py"
        module_name = f"{PLUGIN_NAME.replace('-', '_')}_tool"
        existing = sys.modules.get(module_name)
        if existing is not None:
            return existing
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

def _register_bundled_skill(ctx) -> None:
    """Register the bundled operator skill using the Hermes plugin API.

    Hermes exposes plugin skills as namespaced skills, e.g.
    ``skill_view(\"plugin:skill\")``. The non-destructive profile copy remains
    as a compatibility convenience for users who expect the unqualified
    ``windows-computer-use`` skill to appear after install.
    """
    source = Path(__file__).resolve().parent / "skills" / "windows-computer-use"
    skill_md = source / "SKILL.md"
    if not skill_md.exists() or not hasattr(ctx, "register_skill"):
        return
    ctx.register_skill("windows-computer-use", skill_md)


def register(ctx):
    _register_bundled_skill(ctx)
    _install_skill_if_missing()
    _install_basic_dependencies_if_missing()
    windows_computer_use = _load_tool_module()
    windows_computer_use.register_tools(ctx)

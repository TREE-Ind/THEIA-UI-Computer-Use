"""Hermes Windows Computer Use plugin.

Registers the ``windows_computer_use`` toolset from a standalone Hermes
plugin and makes the bundled skill available in the active Hermes profile.
"""
from __future__ import annotations

import shutil
from pathlib import Path

PLUGIN_NAME = "hermes-windows-computer-use"

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

def register(ctx):
    _install_skill_if_missing()
    windows_computer_use = _load_tool_module()
    windows_computer_use.register_tools(ctx)

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def check(name: str, ok: bool, detail: str = "") -> dict:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}{': ' + detail if detail else ''}")
    return {"name": name, "ok": ok, "detail": detail}

def import_ok(module: str) -> tuple[bool, str]:
    try:
        __import__(module)
        return True, "imported"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

class FakeCtx:
    def __init__(self):
        self.tools = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs["name"])


def install_basic_requirements() -> tuple[bool, str]:
    req = ROOT / "requirements-basic.txt"
    if not req.exists():
        return False, f"missing {req}"
    commands = []
    uv = shutil.which("uv")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if uv:
        commands.append([uv, "pip", "install", "--python", sys.executable, "-r", str(req)])
    commands.append([sys.executable, "-m", "pip", "install", "-r", str(req)])
    if not in_venv:
        commands.append([sys.executable, "-m", "pip", "install", "--user", "-r", str(req)])
    last = ""
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=180)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            continue
        if proc.returncode == 0:
            return True, " ".join(command)
        last = (proc.stderr or proc.stdout or "").strip()[-1000:]
    return False, last


def run_locate_setup(install: bool = False) -> tuple[bool, str]:
    script = ROOT / "scripts" / "setup_locate_worker.py"
    if not script.exists():
        return False, f"missing {script}"
    command = [sys.executable, str(script)]
    if not install:
        command.append("--status")
    proc = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=3600)
    detail = (proc.stdout or proc.stderr or "").strip()[-2000:]
    return proc.returncode == 0, detail


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate THEIA Computer Use plugin")
    parser.add_argument("--install-basic", action="store_true", help="install lightweight basic dependencies before checking")
    parser.add_argument("--install-locate", action="store_true", help="install/repair the isolated LocateAnything worker venv before checking")
    parser.add_argument("--locate", action="store_true", help="also test LocateAnything worker availability")
    parser.add_argument("--json", action="store_true", help="print JSON summary at end")
    args = parser.parse_args()

    results = []
    if args.install_basic:
        ok, detail = install_basic_requirements()
        results.append(check("install basic dependencies", ok, detail))

    if args.install_locate:
        ok, detail = run_locate_setup(install=True)
        results.append(check("install LocateAnything worker", ok, detail))

    supported_os = sys.platform.startswith(("win32", "darwin", "linux"))
    results.append(check("OS is supported desktop", supported_os, f"os.name={os.name}, sys.platform={sys.platform}, platform={platform.platform()}"))
    results.append(check("plugin.yaml exists", (ROOT / "plugin.yaml").exists(), str(ROOT / "plugin.yaml")))
    results.append(check("root __init__.py exists", (ROOT / "__init__.py").exists(), str(ROOT / "__init__.py")))
    results.append(check("tool module exists", (ROOT / "windows_computer_use.py").exists(), str(ROOT / "windows_computer_use.py")))
    results.append(check("worker exists", (ROOT / "windows_computer_use_locate_worker.py").exists(), str(ROOT / "windows_computer_use_locate_worker.py")))
    results.append(check("bundled skill exists", (ROOT / "skills" / "theia-ui-computer-use" / "SKILL.md").exists()))

    ctx = FakeCtx()
    try:
        import windows_computer_use
        windows_computer_use.register_tools(ctx)
        results.append(check("tool registration", len(ctx.tools) >= 20, f"{len(ctx.tools)} tools"))
    except Exception as exc:
        results.append(check("tool registration", False, f"{type(exc).__name__}: {exc}"))

    for mod in ["pyautogui", "PIL", "pygetwindow"]:
        ok, detail = import_ok(mod)
        results.append(check(f"dependency {mod}", ok, detail))

    if supported_os:
        try:
            import pyautogui
            pos = pyautogui.position()
            results.append(check("PyAutoGUI mouse position", True, str(pos)))
        except Exception as exc:
            results.append(check("PyAutoGUI mouse position", False, f"{type(exc).__name__}: {exc}"))

    if args.locate:
        ok, detail = run_locate_setup(install=False)
        results.append(check("LocateAnything worker status", ok, detail))
        py = os.getenv("COMPUTER_USE_LOCATE_PYTHON")
        if py:
            results.append(check("COMPUTER_USE_LOCATE_PYTHON set", True, py))
            proc = subprocess.run([py, str(ROOT / "windows_computer_use_locate_worker.py")], input=json.dumps({"action": "status"}), text=True, capture_output=True, timeout=30)
            ok = proc.returncode == 0 and bool(proc.stdout.strip())
            results.append(check("external worker status", ok, (proc.stdout or proc.stderr)[-500:]))

    if args.json:
        print(json.dumps({"ok": all(r["ok"] for r in results), "results": results}, indent=2))
    return 0 if all(r["ok"] for r in results if not r["name"].startswith("dependency")) else 1

if __name__ == "__main__":
    raise SystemExit(main())

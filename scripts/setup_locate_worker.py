from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_NAME = "locate-worker-status.json"
LOCK_NAME = "locate-worker-install.lock"


def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return Path(get_hermes_home())
    except Exception:
        return Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes")


def default_target() -> Path:
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes" / "theia-ui-computer-use" / "locate-worker" / ".venv"
    return hermes_home() / "theia-ui-computer-use" / "locate-worker" / ".venv"


def venv_python(target: Path) -> Path:
    if os.name == "nt":
        return target / "Scripts" / "python.exe"
    return target / "bin" / "python"


def run(command: list[str], cwd: Path | None = None, timeout: int = 1800) -> dict:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def import_ok(py: Path, module: str) -> bool:
    proc = subprocess.run(
        [str(py), "-c", f"import {module}"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    return proc.returncode == 0


def has_nvidia_gpu() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        return subprocess.run([nvidia_smi, "-L"], capture_output=True, text=True, timeout=10).returncode == 0
    except Exception:
        return False


def resolve_torch_flavor(flavor: str) -> str:
    flavor = (flavor or "auto").lower()
    if flavor != "auto":
        return flavor
    if platform.system() == "Darwin":
        return "default"
    return "cu121" if has_nvidia_gpu() else "cpu"


def torch_command(py: Path, flavor: str) -> list[str] | None:
    if flavor == "skip":
        return None
    base = [str(py), "-m", "pip", "install", "torch", "torchvision"]
    if flavor == "cpu" and platform.system() != "Darwin":
        return base + ["--index-url", "https://download.pytorch.org/whl/cpu"]
    if flavor in {"cu121", "cu124", "cu126"}:
        return base + ["--index-url", f"https://download.pytorch.org/whl/{flavor}"]
    return base


def write_status(target: Path, payload: dict) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / STATUS_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def install(target: Path, torch_flavor: str = "auto", force: bool = False) -> dict:
    target = target.resolve()
    status_path = target / STATUS_NAME
    lock_path = target.parent / LOCK_NAME
    target.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists() and not force:
        payload = {
            "status": "in_progress",
            "target": str(target),
            "python": str(venv_python(target)),
            "lock": str(lock_path),
        }
        write_status(target, payload)
        return payload

    py = venv_python(target)
    if py.exists() and not force and import_ok(py, "torch") and import_ok(py, "transformers"):
        payload = {"status": "ready", "target": str(target), "python": str(py), "already_installed": True}
        write_status(target, payload)
        return payload

    commands: list[dict] = []
    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
        if force and target.exists():
            shutil.rmtree(target)
        if not py.exists():
            venv.EnvBuilder(with_pip=True, clear=False).create(str(target))

        commands.append(run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]))
        if commands[-1]["returncode"] != 0:
            raise RuntimeError("pip bootstrap failed")

        resolved_flavor = resolve_torch_flavor(torch_flavor)
        cmd = torch_command(py, resolved_flavor)
        if cmd and not import_ok(py, "torch"):
            commands.append(run(cmd, timeout=3600))
            if commands[-1]["returncode"] != 0:
                raise RuntimeError(f"torch install failed for flavor {resolved_flavor}")

        commands.append(run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements-locate.txt")], timeout=3600))
        if commands[-1]["returncode"] != 0:
            raise RuntimeError("LocateAnything dependencies install failed")

        checks = {
            "torch": import_ok(py, "torch"),
            "transformers": import_ok(py, "transformers"),
            "PIL": import_ok(py, "PIL"),
        }
        ok = all(checks.values())
        payload = {
            "status": "ready" if ok else "error",
            "target": str(target),
            "python": str(py),
            "torch_flavor": resolve_torch_flavor(torch_flavor),
            "checks": checks,
            "commands": commands,
        }
        write_status(target, payload)
        return payload
    except Exception as exc:
        payload = {
            "status": "error",
            "target": str(target),
            "python": str(py),
            "error": f"{type(exc).__name__}: {exc}",
            "commands": commands,
        }
        write_status(target, payload)
        return payload
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def status(target: Path) -> dict:
    target = target.resolve()
    py = venv_python(target)
    status_path = target / STATUS_NAME
    data = {}
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"status_file": str(status_path)}
    ready = py.exists() and import_ok(py, "torch") and import_ok(py, "transformers")
    data.update({"ready": ready, "target": str(target), "python": str(py), "python_exists": py.exists()})
    if ready:
        data.setdefault("status", "ready")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up THEIA's isolated LocateAnything worker venv")
    parser.add_argument("--target", type=Path, default=default_target())
    parser.add_argument("--torch", choices=["auto", "cpu", "default", "cu121", "cu124", "cu126", "skip"], default=os.getenv("THEIA_LOCATE_TORCH", "auto"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    payload = status(args.target) if args.status else install(args.target, args.torch, args.force)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"ready", "in_progress"} or payload.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())

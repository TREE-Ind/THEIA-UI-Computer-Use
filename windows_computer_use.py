"""Windows desktop control toolset for Hermes Agent.

Flat top-level module so tools.registry auto-discovery imports it and module-scope
registry.register(...) calls make the toolset visible. Heavy visual-grounding deps
(torch/transformers/LocateAnything) are imported lazily so broken ML packages do
not hide the entire toolset from `hermes tools list`.

Important operational rule: do not mutate the Hermes runtime/venv from this
module. CUDA/PyTorch setup must be handled outside the live agent process.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, List, Optional, Tuple

try:
    from tools.registry import registry  # fallback for direct development imports
except Exception:  # pragma: no cover
    registry = None

def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path.home() / ".hermes"


LOG_DIR = _hermes_home() / "skills" / "desktop-computer-use" / "logs"
SCRATCH_DIR = _hermes_home() / "skills" / "desktop-computer-use" / "scratch"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("windows_computer_use")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = logging.FileHandler(LOG_DIR / "computer_use.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)

DRY_RUN = os.getenv("COMPUTER_USE_DRY_RUN", "false").strip().lower() in {"1", "true", "yes", "on"}


def _json(result: Any) -> str:
    return json.dumps(result, default=str)


def _wrap(fn):
    def _handler(args: Dict[str, Any], **_: Any) -> str:
        try:
            return _json(fn(**(args or {})))
        except Exception as exc:
            logger.exception("%s failed", getattr(fn, "__name__", fn))
            return _json({"status": "error", "error": str(exc), "error_type": type(exc).__name__, "dry_run": DRY_RUN})
    return _handler


def check_windows_computer_use_requirements() -> bool:
    """Keep the toolset visible on Windows even if optional deps are broken.

    Optional dependencies are imported inside individual operations and return
    JSON errors there. This prevents PyTorch/CUDA/Pillow breakage from hiding
    the entire Windows toolset after updates or partial installs.
    """
    return os.name == "nt"


def _pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = float(os.getenv("COMPUTER_USE_PYAUTOGUI_PAUSE", "0.05"))
    return pyautogui


def _pil_image():
    from PIL import Image
    return Image


def _active_window() -> Optional[Dict[str, Any]]:
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if not win:
            return None
        return {"title": win.title, "left": win.left, "top": win.top, "width": win.width, "height": win.height}
    except Exception:
        return None


def _position() -> Dict[str, int]:
    p = _pyautogui().position()
    return {"x": int(p.x), "y": int(p.y)}


def _screen_size() -> Dict[str, int]:
    size = _pyautogui().size()
    return {"width": int(size.width), "height": int(size.height)}


def _result(status: str = "ok", **extra: Any) -> Dict[str, Any]:
    data = {"status": status, "dry_run": DRY_RUN, "active_window": _active_window()}
    data.update(extra)
    return data


def _ensure_on_screen(x: int, y: int) -> None:
    pg = _pyautogui()
    if not pg.onScreen(int(x), int(y)):
        size = _screen_size()
        raise ValueError(f"coordinate ({int(x)}, {int(y)}) is off-screen for {size['width']}x{size['height']}")


def _maybe_point(x: Optional[int], y: Optional[int]) -> Optional[Tuple[int, int]]:
    if x is None and y is None:
        return None
    if x is None or y is None:
        raise ValueError("x and y must be provided together")
    _ensure_on_screen(int(x), int(y))
    return int(x), int(y)


def _tween(name: Optional[str]):
    pg = _pyautogui()
    key = (name or "linear").strip()
    allowed = {
        "linear": pg.linear,
        "easeInQuad": pg.easeInQuad,
        "easeOutQuad": pg.easeOutQuad,
        "easeInOutQuad": pg.easeInOutQuad,
        "easeInCubic": pg.easeInCubic,
        "easeOutCubic": pg.easeOutCubic,
        "easeInOutCubic": pg.easeInOutCubic,
        "easeInQuart": pg.easeInQuart,
        "easeOutQuart": pg.easeOutQuart,
        "easeInOutQuart": pg.easeInOutQuart,
        "easeInQuint": pg.easeInQuint,
        "easeOutQuint": pg.easeOutQuint,
        "easeInOutQuint": pg.easeInOutQuint,
        "easeInSine": pg.easeInSine,
        "easeOutSine": pg.easeOutSine,
        "easeInOutSine": pg.easeInOutSine,
        "easeInExpo": pg.easeInExpo,
        "easeOutExpo": pg.easeOutExpo,
        "easeInOutExpo": pg.easeInOutExpo,
        "easeInCirc": pg.easeInCirc,
        "easeOutCirc": pg.easeOutCirc,
        "easeInOutCirc": pg.easeInOutCirc,
        "easeInElastic": pg.easeInElastic,
        "easeOutElastic": pg.easeOutElastic,
        "easeInOutElastic": pg.easeInOutElastic,
        "easeInBack": pg.easeInBack,
        "easeOutBack": pg.easeOutBack,
        "easeInOutBack": pg.easeInOutBack,
        "easeInBounce": pg.easeInBounce,
        "easeOutBounce": pg.easeOutBounce,
        "easeInOutBounce": pg.easeInOutBounce,
    }
    if key not in allowed:
        raise ValueError(f"unsupported tween {key!r}; use one of {sorted(allowed)}")
    return allowed[key]


def _normalize_region(region: Optional[Any]) -> Optional[Tuple[int, int, int, int]]:
    if region is None:
        return None
    if isinstance(region, dict):
        vals = [region.get(k) for k in ("x", "y", "width", "height")]
    else:
        vals = list(region)
    if len(vals) != 4:
        raise ValueError("region must be [x, y, width, height] or {x,y,width,height}")
    x, y, w, h = [int(v) for v in vals]
    if w <= 0 or h <= 0:
        raise ValueError("region width/height must be positive")
    _ensure_on_screen(x, y)
    _ensure_on_screen(x + w - 1, y + h - 1)
    return x, y, w, h


def _capture_screen(display_index: int = 0, question: Optional[str] = None, region: Optional[Any] = None, all_screens: bool = False, **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    normalized_region = _normalize_region(region)
    screenshot = pg.screenshot(region=normalized_region, allScreens=bool(all_screens))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = SCRATCH_DIR / f"screen_{timestamp}.png"
    screenshot.save(path)
    return _result(
        image_path=str(path),
        width=screenshot.width,
        height=screenshot.height,
        display_index=display_index,
        question=question,
        region=list(normalized_region) if normalized_region else None,
        all_screens=bool(all_screens),
    )


def _move(x: int, y: int, duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    _ensure_on_screen(int(x), int(y))
    before = _position()
    if not DRY_RUN:
        pg.moveTo(int(x), int(y), duration=float(duration), tween=_tween(tween))
    after = _position()
    return _result(before_position=before, after_position=after, x=int(x), y=int(y), duration=float(duration), tween=tween)


def _move_relative(dx: int, dy: int, duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    before = _position()
    dest_x, dest_y = before["x"] + int(dx), before["y"] + int(dy)
    _ensure_on_screen(dest_x, dest_y)
    if not DRY_RUN:
        pg.moveRel(int(dx), int(dy), duration=float(duration), tween=_tween(tween))
    after = _position()
    return _result(before_position=before, after_position=after, dx=int(dx), dy=int(dy), duration=float(duration), tween=tween)


def _click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1, interval: float = 0.0, duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    point = _maybe_point(x, y)
    before = _position()
    if not DRY_RUN:
        if point:
            pg.click(x=point[0], y=point[1], button=button, clicks=int(clicks), interval=float(interval), duration=float(duration), tween=_tween(tween))
        else:
            pg.click(button=button, clicks=int(clicks), interval=float(interval))
    after = _position()
    return _result(before_position=before, after_position=after, x=point[0] if point else None, y=point[1] if point else None, button=button, clicks=int(clicks), interval=float(interval), duration=float(duration), tween=tween)


def _double_click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", interval: float = 0.0, duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    return _click(x=x, y=y, button=button, clicks=2, interval=interval, duration=duration, tween=tween)


def _type(text: str, interval: float = 0.0, **_: Any) -> Dict[str, Any]:
    before = _position()
    if not DRY_RUN:
        _pyautogui().write(str(text), interval=float(interval))
    after = _position()
    return _result(before_position=before, after_position=after, chars=len(str(text)))


def _press(keys: Any, presses: int = 1, interval: float = 0.0, **_: Any) -> Dict[str, Any]:
    before = _position()
    key_list = keys if isinstance(keys, list) else [keys]
    key_list = [str(k) for k in key_list]
    if not DRY_RUN:
        if len(key_list) == 1:
            _pyautogui().press(key_list[0], presses=int(presses), interval=float(interval))
        else:
            for _i in range(int(presses)):
                _pyautogui().press(key_list, interval=float(interval))
    after = _position()
    return _result(before_position=before, after_position=after, keys=key_list, presses=int(presses), interval=float(interval))


def _key_down(key: str, **_: Any) -> Dict[str, Any]:
    before = _position()
    if not DRY_RUN:
        _pyautogui().keyDown(str(key))
    after = _position()
    return _result(before_position=before, after_position=after, key=str(key), action="key_down")


def _key_up(key: str, **_: Any) -> Dict[str, Any]:
    before = _position()
    if not DRY_RUN:
        _pyautogui().keyUp(str(key))
    after = _position()
    return _result(before_position=before, after_position=after, key=str(key), action="key_up")


def _hotkey(keys: List[str], interval: float = 0.0, **_: Any) -> Dict[str, Any]:
    before = _position()
    if not DRY_RUN:
        _pyautogui().hotkey(*[str(k) for k in keys], interval=float(interval))
    after = _position()
    return _result(before_position=before, after_position=after, keys=keys, interval=float(interval))


def _scroll(clicks: int, x: Optional[int] = None, y: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    """Scroll the Windows mouse wheel.

    Positive clicks scroll up; negative clicks scroll down. Uses native Win32
    wheel events by default because pyautogui.scroll() can be a no-op in some
    Windows/Electron targets. Set COMPUTER_USE_SCROLL_BACKEND=pyautogui or both
    to override.
    """
    pg = _pyautogui()
    before = _position()
    target = {"x": int(x), "y": int(y)} if x is not None and y is not None else None
    backend = os.getenv("COMPUTER_USE_SCROLL_BACKEND", "win32").strip().lower()
    native_sent = False
    pyautogui_sent = False
    if not DRY_RUN:
        if target:
            pg.moveTo(target["x"], target["y"])
            time.sleep(0.05)
        amount = int(clicks)
        if backend in {"pyautogui", "both"}:
            pg.scroll(amount)
            pyautogui_sent = True
        if os.name == "nt" and backend in {"win32", "native", "both"}:
            import ctypes
            MOUSEEVENTF_WHEEL = 0x0800
            WHEEL_DELTA = 120
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, amount * WHEEL_DELTA, 0)
            native_sent = True
        elif not pyautogui_sent:
            pg.scroll(amount)
            pyautogui_sent = True
    after = _position()
    return _result(
        before_position=before,
        after_position=after,
        clicks=int(clicks),
        x=target["x"] if target else None,
        y=target["y"] if target else None,
        backend=backend,
        native_sent=native_sent,
        pyautogui_sent=pyautogui_sent,
    )


def _mouse_down(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    point = _maybe_point(x, y)
    before = _position()
    if not DRY_RUN:
        if point:
            pg.mouseDown(x=point[0], y=point[1], button=button, duration=float(duration), tween=_tween(tween))
        else:
            pg.mouseDown(button=button)
    after = _position()
    return _result(before_position=before, after_position=after, x=point[0] if point else None, y=point[1] if point else None, button=button, action="mouse_down")


def _mouse_up(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", duration: float = 0.0, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    point = _maybe_point(x, y)
    before = _position()
    if not DRY_RUN:
        if point:
            pg.mouseUp(x=point[0], y=point[1], button=button, duration=float(duration), tween=_tween(tween))
        else:
            pg.mouseUp(button=button)
    after = _position()
    return _result(before_position=before, after_position=after, x=point[0] if point else None, y=point[1] if point else None, button=button, action="mouse_up")


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.3, button: str = "left", tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    _ensure_on_screen(int(x1), int(y1))
    _ensure_on_screen(int(x2), int(y2))
    before = _position()
    if not DRY_RUN:
        pg.moveTo(int(x1), int(y1))
        pg.dragTo(int(x2), int(y2), duration=float(duration), button=button, tween=_tween(tween))
    after = _position()
    return _result(before_position=before, after_position=after, from_xy=[int(x1), int(y1)], to_xy=[int(x2), int(y2)], button=button, duration=float(duration), tween=tween)


def _drag_relative(dx: int, dy: int, duration: float = 0.3, button: str = "left", tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    before = _position()
    dest_x, dest_y = before["x"] + int(dx), before["y"] + int(dy)
    _ensure_on_screen(dest_x, dest_y)
    if not DRY_RUN:
        pg.dragRel(int(dx), int(dy), duration=float(duration), button=button, tween=_tween(tween))
    after = _position()
    return _result(before_position=before, after_position=after, dx=int(dx), dy=int(dy), button=button, duration=float(duration), tween=tween)


def _drag_path(points: List[Dict[str, int]], button: str = "left", duration_per_segment: float = 0.1, tween: str = "linear", **_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    if not points or len(points) < 2:
        raise ValueError("points must contain at least two {x,y} coordinates")
    normalized = []
    for p in points:
        x, y = int(p["x"]), int(p["y"])
        _ensure_on_screen(x, y)
        normalized.append({"x": x, "y": y})
    before = _position()
    if not DRY_RUN:
        pg.moveTo(normalized[0]["x"], normalized[0]["y"])
        pg.mouseDown(button=button)
        try:
            for p in normalized[1:]:
                pg.moveTo(p["x"], p["y"], duration=float(duration_per_segment), tween=_tween(tween))
        finally:
            pg.mouseUp(button=button)
    after = _position()
    return _result(before_position=before, after_position=after, points=normalized, button=button, duration_per_segment=float(duration_per_segment), tween=tween)


def _release_all(**_: Any) -> Dict[str, Any]:
    pg = _pyautogui()
    before = _position()
    mouse_buttons = ["left", "middle", "right"]
    keys = ["shift", "ctrl", "alt", "win", "cmd"]
    if not DRY_RUN:
        for b in mouse_buttons:
            try:
                pg.mouseUp(button=b)
            except Exception:
                pass
        for k in keys:
            try:
                pg.keyUp(k)
            except Exception:
                pass
    after = _position()
    return _result(before_position=before, after_position=after, released_mouse_buttons=mouse_buttons, released_keys=keys)


def _pixel(x: int, y: int, **_: Any) -> Dict[str, Any]:
    _ensure_on_screen(int(x), int(y))
    rgb = _pyautogui().pixel(int(x), int(y))
    return _result(x=int(x), y=int(y), rgb=[int(rgb[0]), int(rgb[1]), int(rgb[2])])


def _pixel_matches(x: int, y: int, rgb: List[int], tolerance: int = 0, **_: Any) -> Dict[str, Any]:
    _ensure_on_screen(int(x), int(y))
    expected = tuple(int(v) for v in rgb[:3])
    actual = _pyautogui().pixel(int(x), int(y))
    matched = _pyautogui().pixelMatchesColor(int(x), int(y), expected, tolerance=int(tolerance))
    return _result(x=int(x), y=int(y), expected_rgb=list(expected), actual_rgb=[int(actual[0]), int(actual[1]), int(actual[2])], tolerance=int(tolerance), matches=bool(matched))


def _set_dry_run(dry_run: bool) -> Dict[str, Any]:
    global DRY_RUN
    DRY_RUN = bool(dry_run)
    return _result(dry_run=DRY_RUN)


def _get_active_window(**_: Any) -> Dict[str, Any]:
    return _result(screen=_screen_size())


def _focus_window(title: str, exact: bool = False, **_: Any) -> Dict[str, Any]:
    try:
        import pygetwindow as gw
    except Exception as exc:
        return _result("error", error=f"pygetwindow unavailable: {exc}")
    wins = gw.getWindowsWithTitle(title)
    if not wins and not exact:
        all_wins = gw.getAllWindows()
        needle = title.lower()
        wins = [w for w in all_wins if needle in (w.title or "").lower()]
    if not wins:
        return _result("not_found", title=title)
    win = wins[0]
    if not DRY_RUN:
        if getattr(win, "isMinimized", False):
            win.restore()
        win.activate()
        time.sleep(0.2)
    return _result(title=getattr(win, "title", title), bounds={"left": win.left, "top": win.top, "width": win.width, "height": win.height})


def _open_app(command: str, **_: Any) -> Dict[str, Any]:
    if not command:
        return _result("error", error="command is required")
    if not DRY_RUN:
        subprocess.Popen(command, shell=True)
        time.sleep(0.5)
    return _result(command=command)



def _worker_script_path() -> Path:
    return Path(__file__).with_name("windows_computer_use_locate_worker.py")


def _external_python_path(explicit: Optional[str] = None) -> Optional[str]:
    candidates: List[str] = []
    for value in [explicit, os.getenv("COMPUTER_USE_LOCATE_PYTHON")]:
        if value:
            candidates.append(str(value))
    # Safe defaults: only use already-existing interpreters outside Hermes' venv.
    candidates.extend([r"C:\Python312\python.exe", r"C:\Python311\python.exe"])
    current = Path(sys.executable).resolve()
    for candidate in candidates:
        try:
            p = Path(candidate)
            if p.exists() and p.resolve() != current:
                return str(p)
        except Exception:
            continue
    return None


_EXTERNAL_WORKER_PROC = None
_EXTERNAL_WORKER_PYTHON = None
_EXTERNAL_WORKER_QUEUE = None
_EXTERNAL_WORKER_LOCK = threading.Lock()


def _start_persistent_external_worker(python: Optional[str] = None) -> Dict[str, Any]:
    global _EXTERNAL_WORKER_PROC, _EXTERNAL_WORKER_PYTHON, _EXTERNAL_WORKER_QUEUE
    external_python = _external_python_path(python)
    if not external_python:
        return {"status": "error", "backend": "external", "error": "No external Python configured/found. Set COMPUTER_USE_LOCATE_PYTHON to an isolated CUDA-capable interpreter outside the Hermes venv."}
    worker = _worker_script_path()
    if not worker.exists():
        return {"status": "error", "backend": "external", "error": f"Locate worker script not found: {worker}", "python": external_python}
    with _EXTERNAL_WORKER_LOCK:
        if _EXTERNAL_WORKER_PROC is not None and _EXTERNAL_WORKER_PROC.poll() is None and _EXTERNAL_WORKER_PYTHON == external_python:
            return {"status": "ok", "backend": "external", "python": external_python, "worker": str(worker), "persistent": True}
        if _EXTERNAL_WORKER_PROC is not None and _EXTERNAL_WORKER_PROC.poll() is None:
            try:
                _EXTERNAL_WORKER_PROC.terminate()
            except Exception:
                pass
        try:
            proc = subprocess.Popen(
                [external_python, str(worker), "--server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
            )
        except Exception as exc:
            return {"status": "error", "backend": "external", "error": str(exc), "python": external_python, "worker": str(worker)}
        q = Queue()
        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                q.put(line)
        threading.Thread(target=_reader, daemon=True).start()
        _EXTERNAL_WORKER_PROC = proc
        _EXTERNAL_WORKER_PYTHON = external_python
        _EXTERNAL_WORKER_QUEUE = q
        return {"status": "ok", "backend": "external", "python": external_python, "worker": str(worker), "persistent": True}


def _call_persistent_external_worker(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    started = _start_persistent_external_worker(python)
    if started.get("status") == "error":
        return started
    proc = _EXTERNAL_WORKER_PROC
    q = _EXTERNAL_WORKER_QUEUE
    if proc is None or proc.stdin is None or q is None or proc.poll() is not None:
        return {"status": "error", "backend": "external", "error": "persistent external worker is not running", "start": started}
    try:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        line = q.get(timeout=float(timeout or os.getenv("COMPUTER_USE_LOCATE_WORKER_TIMEOUT", "300")))
        data = json.loads(line)
        data.setdefault("backend", "external")
        data.setdefault("python", _EXTERNAL_WORKER_PYTHON)
        data["persistent"] = True
        return data
    except Empty:
        return {"status": "error", "backend": "external", "error": "persistent external worker timed out", "python": _EXTERNAL_WORKER_PYTHON, "persistent": True}
    except Exception as exc:
        return {"status": "error", "backend": "external", "error": str(exc), "python": _EXTERNAL_WORKER_PYTHON, "persistent": True}


def _external_worker_call(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    persistent = os.getenv("COMPUTER_USE_LOCATE_PERSISTENT", "true").strip().lower() not in {"0", "false", "no", "off"}
    if persistent:
        return _call_persistent_external_worker(payload, python=python, timeout=timeout)
    return _run_external_locate_worker(payload, python=python, timeout=timeout)


def _run_external_locate_worker(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    external_python = _external_python_path(python)
    if not external_python:
        return {"status": "error", "backend": "external", "error": "No external Python configured/found. Set COMPUTER_USE_LOCATE_PYTHON to an isolated CUDA-capable interpreter outside the Hermes venv."}
    worker = _worker_script_path()
    if not worker.exists():
        return {"status": "error", "backend": "external", "error": f"Locate worker script not found: {worker}", "python": external_python}
    try:
        proc = subprocess.run(
            [external_python, str(worker)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=float(timeout or os.getenv("COMPUTER_USE_LOCATE_WORKER_TIMEOUT", "300")),
            env=os.environ.copy(),
        )
    except Exception as exc:
        return {"status": "error", "backend": "external", "error": str(exc), "python": external_python, "worker": str(worker)}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    try:
        data = json.loads(stdout) if stdout else {"status": "error", "error": "external worker produced no stdout"}
    except Exception as exc:
        data = {"status": "error", "error": f"external worker returned non-JSON stdout: {exc}", "stdout_tail": stdout[-1000:]}
    data.setdefault("backend", "external")
    data.setdefault("python", external_python)
    data["worker_returncode"] = proc.returncode
    if stderr:
        data["stderr_tail"] = stderr[-1000:]
    if proc.returncode != 0 and data.get("status") != "error":
        data["status"] = "error"
        data["error"] = f"external worker exited with code {proc.returncode}"
    return data


def _locate_backend_preference(backend: Optional[str] = None) -> str:
    value = backend or os.getenv("COMPUTER_USE_LOCATE_BACKEND", "auto")
    return str(value).strip().lower()


def _locate_payload_options(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "task", "output_type", "strategy", "region", "max_side", "refine_max_side",
        "max_new_tokens", "generation_mode", "temperature", "top_p",
        "repetition_penalty", "do_sample", "verbose", "dtype",
        "refine_area_ratio", "refine_pad", "point_refine_radius", "prompt_style",
    ]
    return {k: kwargs[k] for k in keys if k in kwargs and kwargs[k] is not None}


class _LocateModel:
    def __init__(self) -> None:
        self.model = None
        self.processor = None
        self.torch = None
        self.device = None

    def unload(self) -> None:
        try:
            if self.torch is not None and hasattr(self.torch, "cuda"):
                self.torch.cuda.empty_cache()
        except Exception:
            pass
        self.model = None
        self.processor = None
        self.device = None

    def load(self, device: Optional[str] = None) -> Dict[str, Any]:
        requested = None if device in {None, "", "auto"} else str(device)
        if self.model is not None:
            if requested is None or requested == self.device:
                return {"status": "already_loaded", "device": self.device}
            self.unload()
        try:
            import torch
            from transformers import AutoModel, AutoProcessor
        except Exception as exc:
            return {"status": "error", "error": f"torch/transformers unavailable: {exc}"}
        cuda_available = bool(torch.cuda.is_available())
        if requested == "cuda" and not cuda_available:
            return {"status": "error", "error": "CUDA requested but torch.cuda.is_available() is false in this Hermes runtime", "torch": torch.__version__, "cuda_available": cuda_available}
        resolved = requested or ("cuda" if cuda_available else "cpu")
        model_id = os.getenv("COMPUTER_USE_LOCATE_MODEL", "nvidia/LocateAnything-3B")
        try:
            dtype = torch.float16 if resolved == "cuda" else torch.float32
            self.processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
            self.model = AutoModel.from_pretrained(model_id, torch_dtype=dtype, trust_remote_code=True).to(resolved).eval()
            self.torch = torch
            self.device = resolved
            return {"status": "loaded", "device": resolved, "model": model_id, "torch": torch.__version__, "cuda_available": cuda_available, "cuda_version": getattr(torch.version, "cuda", None)}
        except Exception as exc:
            self.unload()
            return {"status": "error", "error": str(exc), "device": resolved, "torch": torch.__version__, "cuda_available": cuda_available}


_locate_model = _LocateModel()


def _warm(device: Optional[str] = None, backend: Optional[str] = None, python: Optional[str] = None, **_: Any) -> Dict[str, Any]:
    pref = _locate_backend_preference(backend)
    if pref in {"external", "worker"}:
        return _external_worker_call({"action": "warm", "device": device, "model_id": os.getenv("COMPUTER_USE_LOCATE_MODEL")}, python=python)
    if pref == "auto" and _external_python_path(python):
        external = _external_worker_call({"action": "warm", "device": device, "model_id": os.getenv("COMPUTER_USE_LOCATE_MODEL")}, python=python, timeout=90)
        if external.get("status") in {"loaded", "already_loaded"}:
            return external
    internal = _locate_model.load(device=device)
    internal.setdefault("backend", "internal")
    return internal


def _parse_box(text: str, image_size: Tuple[int, int]) -> Optional[Tuple[int, int, int, int]]:
    m = re.search(r"<box>(.*?)</box>", text, re.DOTALL)
    body = m.group(1) if m else text
    nums = [int(n) for n in re.findall(r"-?\d+", body)]
    if len(nums) < 4:
        return None
    x1, y1, x2, y2 = nums[:4]
    width, height = image_size
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1000:
        x1 = round(x1 / 1000 * width)
        x2 = round(x2 / 1000 * width)
        y1 = round(y1 / 1000 * height)
        y2 = round(y2 / 1000 * height)
    return int(x1), int(y1), int(x2), int(y2)


def _locate(description: str, image_path: Optional[str] = None, threshold: float = 0.3, device: Optional[str] = None, backend: Optional[str] = None, python: Optional[str] = None, **_: Any) -> List[Dict[str, Any]]:
    if not image_path:
        image_path = _capture_screen()["image_path"]
    pref = _locate_backend_preference(backend)
    model_id = os.getenv("COMPUTER_USE_LOCATE_MODEL")
    if pref in {"external", "worker"}:
        return [_external_worker_call({
            "action": "locate",
            "description": description,
            "image_path": image_path,
            "threshold": threshold,
            "device": device,
            "model_id": model_id,
            "max_side": int(os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "640")),
            "max_new_tokens": int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")),
            **_locate_payload_options(_),
        }, python=python)]
    if pref == "auto" and _external_python_path(python):
        external = _external_worker_call({
            "action": "locate",
            "description": description,
            "image_path": image_path,
            "threshold": threshold,
            "device": device,
            "model_id": model_id,
            "max_side": int(os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "640")),
            "max_new_tokens": int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")),
            **_locate_payload_options(_),
        }, python=python)
        if external.get("status") in {"found", "not_found"}:
            return [external]
        # Auto mode can fall back to internal. Explicit external mode returns the external error above.
    load = _locate_model.load(device=device)
    if load.get("status") == "error":
        return [{"status": "error", "backend": "internal", "error": load.get("error"), "load": load}]
    Image = _pil_image()
    image = Image.open(image_path).convert("RGB")
    original_width, original_height = image.size
    infer_image = image.copy()
    max_side = int(os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "640"))
    if max(infer_image.size) > max_side:
        infer_image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    prompt = f"<image-1> Locate the region that matches the following description: {description}."
    try:
        inputs = _locate_model.processor(text=prompt, images=[infer_image], return_tensors="pt")
        dev = next(_locate_model.model.parameters()).device
        inputs = {k: v.to(dev) if hasattr(v, "to") else v for k, v in inputs.items()}
        with _locate_model.torch.no_grad():
            generated = _locate_model.model.generate(**inputs, tokenizer=_locate_model.processor.tokenizer, use_cache=True, max_new_tokens=int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")))
        if isinstance(generated, str):
            text = generated
        else:
            text = _locate_model.processor.batch_decode(generated, skip_special_tokens=False)[0]
        box = _parse_box(text, infer_image.size)
        if not box:
            return [{"status": "not_found", "backend": "internal", "description": description, "raw": text, "image_path": image_path, "device": _locate_model.device}]
        x1, y1, x2, y2 = box
        sx = original_width / infer_image.width
        sy = original_height / infer_image.height
        x1, x2 = round(x1 * sx), round(x2 * sx)
        y1, y2 = round(y1 * sy), round(y2 * sy)
        return [{
            "status": "found", "backend": "internal", "description": description, "image_path": image_path,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "center": {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2},
            "raw": text, "score": 1.0, "threshold": threshold, "device": _locate_model.device,
        }]
    except Exception as exc:
        logger.exception("locate failed")
        return [{"status": "error", "backend": "internal", "error": str(exc), "description": description, "image_path": image_path, "device": _locate_model.device}]

def _find_click(description: str, image_path: Optional[str] = None, button: str = "left", **kwargs: Any) -> Dict[str, Any]:
    hits = _locate(description=description, image_path=image_path, **kwargs)
    if not hits or hits[0].get("status") != "found":
        return _result("not_found", description=description, locate=hits)
    center = hits[0]["center"]
    clicked = _click(center["x"], center["y"], button=button)
    clicked["locate"] = hits[0]
    return clicked


# ---- Schemas and plugin registration -----------------------------------------

def _schema(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required or []}}

_COMMON_CHECK = check_windows_computer_use_requirements
_TOOLSET = "windows_computer_use"
_PLUGIN_CTX = None

def _register(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]], handler) -> None:
    schema = _schema(name, description, properties, required)
    wrapped = _wrap(handler)
    if _PLUGIN_CTX is not None:
        _PLUGIN_CTX.register_tool(
            name=name,
            toolset=_TOOLSET,
            schema=schema,
            handler=wrapped,
            check_fn=_COMMON_CHECK,
            requires_env=[],
            description=description,
            emoji="🖱️",
        )
        return
    if registry is None:
        raise RuntimeError("Hermes tools.registry is unavailable and no PluginContext was provided")
    registry.register(
        name=name,
        toolset=_TOOLSET,
        schema=schema,
        handler=wrapped,
        check_fn=_COMMON_CHECK,
        requires_env=[],
        description=description,
        emoji="🖱️",
    )

def register_tools(ctx=None) -> None:
    """Register all windows_computer_use tools with Hermes.

    Hermes plugins call this with PluginContext so tools are tracked as
    plugin-provided. Passing no ctx is supported only for local development.
    """
    global _PLUGIN_CTX
    old_ctx = _PLUGIN_CTX
    _PLUGIN_CTX = ctx
    try:
        _register("computer_use_capture_screen", "Capture the Windows desktop screenshot and return an image path.", {"display_index": {"type": "integer", "default": 0}, "question": {"type": "string"}, "region": {"description": "Optional [x, y, width, height] capture region", "type": "array", "items": {"type": "integer"}}, "all_screens": {"type": "boolean", "default": False}}, [], _capture_screen)
        _register("computer_use_warm", "Load LocateAnything-3B lazily. Supports isolated external CUDA worker via COMPUTER_USE_LOCATE_PYTHON; never installs or mutates the Hermes venv.", {"device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}}, [], _warm)
        _register("computer_use_locate", "Locate a UI element on the Windows desktop using LocateAnything-3B visual grounding. Preferred for Windows UI grounding; supports isolated external CUDA worker, point/box output, and coarse-refine strategy.", {"description": {"type": "string"}, "image_path": {"type": "string"}, "threshold": {"type": "number", "default": 0.3}, "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point", "description": "Use point for click targets; box for region bounds"}, "task": {"type": "string", "enum": ["gui", "single", "multi", "text", "detect_text"], "default": "gui"}, "strategy": {"type": "string", "enum": ["auto", "direct", "point_refine", "refine", "coarse_refine"], "default": "direct"}, "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [x,y,width,height] crop in screenshot coordinates"}, "max_side": {"type": "integer", "default": 640}, "refine_max_side": {"type": "integer", "default": 1024}, "point_refine_radius": {"type": "integer", "default": 360}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}, "prompt_style": {"type": "string", "enum": ["direct", "chat_template"], "default": "direct"}, "do_sample": {"type": "boolean", "default": False}, "dtype": {"type": "string", "enum": ["bfloat16", "float16", "float32", "bf16", "fp16", "fp32"], "default": "bfloat16"}}, ["description"], _locate)
        _register("computer_use_find_click", "Locate a described UI element and click its point/center. Preferred for Windows UI grounding; supports isolated external CUDA worker and point output.", {"description": {"type": "string"}, "image_path": {"type": "string"}, "threshold": {"type": "number", "default": 0.3}, "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point", "description": "Use point for click targets; box for region bounds"}, "task": {"type": "string", "enum": ["gui", "single", "multi", "text", "detect_text"], "default": "gui"}, "strategy": {"type": "string", "enum": ["auto", "direct", "point_refine", "refine", "coarse_refine"], "default": "direct"}, "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [x,y,width,height] crop in screenshot coordinates"}, "max_side": {"type": "integer", "default": 640}, "refine_max_side": {"type": "integer", "default": 1024}, "point_refine_radius": {"type": "integer", "default": 360}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}, "prompt_style": {"type": "string", "enum": ["direct", "chat_template"], "default": "direct"}, "do_sample": {"type": "boolean", "default": False}, "dtype": {"type": "string", "enum": ["bfloat16", "float16", "float32", "bf16", "fp16", "fp32"], "default": "bfloat16"}, "button": {"type": "string", "default": "left"}}, ["description"], _find_click)
        _register("computer_use_move", "Move the Windows mouse cursor to an absolute coordinate without clicking.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, ["x", "y"], _move)
        _register("computer_use_move_relative", "Move the Windows mouse cursor by a relative offset without clicking.", {"dx": {"type": "integer"}, "dy": {"type": "integer"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, ["dx", "dy"], _move_relative)
        _register("computer_use_click", "Click a Windows desktop coordinate, or the current cursor position when x/y are omitted.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "clicks": {"type": "integer", "default": 1}, "interval": {"type": "number", "default": 0.0}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _click)
        _register("computer_use_double_click", "Double-click a Windows desktop coordinate, or the current cursor position when x/y are omitted.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "interval": {"type": "number", "default": 0.0}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _double_click)
        _register("computer_use_mouse_down", "Press and hold a mouse button at an optional coordinate. Pair with computer_use_mouse_up or computer_use_release_all.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _mouse_down)
        _register("computer_use_mouse_up", "Release a mouse button at an optional coordinate.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _mouse_up)
        _register("computer_use_type", "Type text into the focused Windows application.", {"text": {"type": "string"}, "interval": {"type": "number", "default": 0.0}}, ["text"], _type)
        _register("computer_use_press", "Press one or more keyboard keys, with optional repeat count and interval.", {"keys": {"description": "A key string or list of key strings", "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "presses": {"type": "integer", "default": 1}, "interval": {"type": "number", "default": 0.0}}, ["keys"], _press)
        _register("computer_use_key_down", "Hold down a keyboard key until computer_use_key_up or computer_use_release_all is called.", {"key": {"type": "string"}}, ["key"], _key_down)
        _register("computer_use_key_up", "Release a keyboard key previously held down.", {"key": {"type": "string"}}, ["key"], _key_up)
        _register("computer_use_hotkey", "Press a Windows hotkey sequence, e.g. ['ctrl','s']; keys go down in order and up in reverse order.", {"keys": {"type": "array", "items": {"type": "string"}}, "interval": {"type": "number", "default": 0.0}}, ["keys"], _hotkey)
        _register("computer_use_scroll", "Scroll at the current mouse position or optional coordinate. Uses native Win32 wheel events by default on Windows.", {"clicks": {"type": "integer"}, "x": {"type": "integer"}, "y": {"type": "integer"}}, ["clicks"], _scroll)
        _register("computer_use_drag", "Drag from one Windows desktop coordinate to another while holding a mouse button down.", {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}, "duration": {"type": "number", "default": 0.3}, "button": {"type": "string", "default": "left"}, "tween": {"type": "string", "default": "linear"}}, ["x1", "y1", "x2", "y2"], _drag)
        _register("computer_use_drag_relative", "Drag from the current cursor position by a relative offset while holding a mouse button down.", {"dx": {"type": "integer"}, "dy": {"type": "integer"}, "duration": {"type": "number", "default": 0.3}, "button": {"type": "string", "default": "left"}, "tween": {"type": "string", "default": "linear"}}, ["dx", "dy"], _drag_relative)
        _register("computer_use_drag_path", "Drag through multiple absolute points while holding a mouse button down; useful for sliders, selection boxes, drawing, and finicky UI gestures.", {"points": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}, "minItems": 2}, "button": {"type": "string", "default": "left"}, "duration_per_segment": {"type": "number", "default": 0.1}, "tween": {"type": "string", "default": "linear"}}, ["points"], _drag_path)
        _register("computer_use_release_all", "Safety release for common held mouse buttons and modifier keys after manual hold gestures.", {}, [], _release_all)
        _register("computer_use_pixel", "Read the RGB color of a screen pixel at x,y for lightweight visual verification.", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"], _pixel)
        _register("computer_use_pixel_matches", "Check whether a screen pixel matches an expected RGB color within tolerance.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "rgb": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3}, "tolerance": {"type": "integer", "default": 0}}, ["x", "y", "rgb"], _pixel_matches)
        _register("computer_use_open_app", "Open a Windows application or command.", {"command": {"type": "string"}}, ["command"], _open_app)
        _register("computer_use_focus_window", "Focus a Windows window by title.", {"title": {"type": "string"}, "exact": {"type": "boolean", "default": False}}, ["title"], _focus_window)
        _register("computer_use_get_active_window", "Return active window and screen information.", {}, [], _get_active_window)
        _register("computer_use_set_dry_run", "Enable or disable dry-run mode for Windows computer-use actions.", {"dry_run": {"type": "boolean"}}, ["dry_run"], _set_dry_run)
    finally:
        _PLUGIN_CTX = old_ctx

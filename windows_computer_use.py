"""Cross-platform desktop control toolset for Hermes Agent.

Flat top-level module so tools.registry auto-discovery imports it and module-scope
registry.register(...) calls make the toolset visible. Heavy visual-grounding deps
(torch/transformers/LocateAnything) are imported lazily so broken ML packages do
not hide the entire toolset from `hermes tools list`.

Important operational rule: do not mutate the Hermes runtime/venv from this
module. CUDA/PyTorch setup must be handled outside the live agent process.
"""
from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import re
import ast
import subprocess
import sys
import threading
import time
import uuid
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
    """Keep the toolset visible on supported desktop OSes.

    PyAutoGUI supports Windows, macOS, and Linux. Optional dependencies are
    imported inside individual operations and return JSON errors there. This
    prevents PyTorch/CUDA/Pillow breakage from hiding the entire toolset after
    updates or partial installs.
    """
    return sys.platform.startswith(("win32", "darwin", "linux"))


def _pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = float(os.getenv("COMPUTER_USE_PYAUTOGUI_PAUSE", "0.05"))
    return pyautogui


def _pil_image():
    from PIL import Image
    return Image


def _win32_window_metadata(handle: Optional[int]) -> Dict[str, Any]:
    if os.name != "nt" or not handle:
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(int(handle))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        dpi = int(user32.GetDpiForWindow(hwnd)) if hasattr(user32, "GetDpiForWindow") else None
        rect = wintypes.RECT()
        client_bounds = None
        if user32.GetClientRect(hwnd, ctypes.byref(rect)):
            point = wintypes.POINT(rect.left, rect.top)
            if user32.ClientToScreen(hwnd, ctypes.byref(point)):
                client_bounds = {
                    "left": int(point.x), "top": int(point.y),
                    "width": int(rect.right - rect.left), "height": int(rect.bottom - rect.top),
                }
        return {
            "handle": int(handle), "process_id": int(process_id.value),
            "dpi": dpi, "client_bounds": client_bounds,
        }
    except Exception:
        logger.exception("failed to query active Win32 window metadata")
        return {"handle": int(handle)}


def _active_window() -> Optional[Dict[str, Any]]:
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if not win:
            return None
        handle = getattr(win, "_hWnd", None)
        result = {
            "title": win.title, "left": int(win.left), "top": int(win.top),
            "width": int(win.width), "height": int(win.height),
        }
        result.update(_win32_window_metadata(handle))
        return result
    except Exception:
        return None


def _position() -> Dict[str, int]:
    p = _pyautogui().position()
    return {"x": int(p.x), "y": int(p.y)}


def _screen_size() -> Dict[str, int]:
    size = _pyautogui().size()
    return {"width": int(size.width), "height": int(size.height)}


def _virtual_screen_bounds() -> Dict[str, int]:
    """Return the complete desktop rectangle, including negative monitor origins."""
    if os.name == "nt":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
            top = int(user32.GetSystemMetrics(77))    # SM_YVIRTUALSCREEN
            width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
            height = int(user32.GetSystemMetrics(79)) # SM_CYVIRTUALSCREEN
            if width > 0 and height > 0:
                return {
                    "left": left, "top": top, "width": width, "height": height,
                    "right": left + width, "bottom": top + height,
                }
        except Exception:
            logger.exception("failed to query Win32 virtual desktop metrics")
    primary = _screen_size()
    return {
        "left": 0, "top": 0, "width": primary["width"], "height": primary["height"],
        "right": primary["width"], "bottom": primary["height"],
    }


def _result(status: str = "ok", **extra: Any) -> Dict[str, Any]:
    data = {"status": status, "dry_run": DRY_RUN, "active_window": _active_window()}
    data.update(extra)
    return data


def _ensure_on_screen(x: int, y: int) -> None:
    bounds = _virtual_screen_bounds()
    px, py = int(x), int(y)
    if not (bounds["left"] <= px < bounds["right"] and bounds["top"] <= py < bounds["bottom"]):
        raise ValueError(
            f"coordinate ({px}, {py}) is off the virtual desktop "
            f"[{bounds['left']},{bounds['top']},{bounds['right']},{bounds['bottom']})"
        )


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


def _normalize_region(
    region: Optional[Any], *, return_clipped: bool = False,
) -> Any:
    if region is None:
        return (None, False) if return_clipped else None
    if isinstance(region, dict):
        vals = [region.get(k) for k in ("x", "y", "width", "height")]
    else:
        vals = list(region)
    if len(vals) != 4:
        raise ValueError("region must be [x, y, width, height] or {x,y,width,height}")
    x, y, w, h = [int(v) for v in vals]
    if w <= 0 or h <= 0:
        raise ValueError("region width/height must be positive")
    bounds = _virtual_screen_bounds()
    x1 = max(x, bounds["left"])
    y1 = max(y, bounds["top"])
    x2 = min(x + w, bounds["right"])
    y2 = min(y + h, bounds["bottom"])
    if x2 <= x1 or y2 <= y1:
        raise ValueError(
            "capture region does not intersect the virtual desktop "
            f"[{bounds['left']},{bounds['top']},{bounds['right']},{bounds['bottom']})"
        )
    normalized = (x1, y1, x2 - x1, y2 - y1)
    clipped = normalized != (x, y, w, h)
    return (normalized, clipped) if return_clipped else normalized


def _capture_pixels(pg: Any, region: Optional[Tuple[int, int, int, int]], all_screens: bool, virtual: Dict[str, int]) -> Any:
    """Capture pixels with screen-coordinate semantics on a Win32 virtual desktop."""
    if os.name != "nt" or (region is None and not all_screens):
        return pg.screenshot(region=region, allScreens=bool(all_screens))
    Image = _pil_image()
    canvas = pg.screenshot(region=None, allScreens=True)
    expected_size = (int(virtual["width"]), int(virtual["height"]))
    actual_size = (int(canvas.width), int(canvas.height))
    if actual_size != expected_size:
        # PyAutoGUI coordinates are logical desktop pixels. Normalize a DPI-
        # scaled ImageGrab bitmap to the same coordinate space before cropping.
        canvas = canvas.resize(expected_size, Image.Resampling.LANCZOS)
    if region is None:
        return canvas
    x, y, width, height = region
    left = int(x) - int(virtual["left"])
    top = int(y) - int(virtual["top"])
    return canvas.crop((left, top, left + int(width), top + int(height)))


_CAPTURE_META_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _capture_screen(display_index: int = 0, question: Optional[str] = None, region: Optional[Any] = None, all_screens: bool = False, scope: str = "primary", **_: Any) -> Dict[str, Any]:
    scope = str(scope or "primary").strip().lower()
    allowed_scopes = {"primary", "virtual_desktop", "active_window", "active_client", "region"}
    if scope not in allowed_scopes:
        raise ValueError(f"scope must be one of {sorted(allowed_scopes)}")
    if all_screens and (scope != "primary" or region is not None):
        raise ValueError("all_screens is a deprecated alias and cannot be combined with scope or region")
    if region is not None and scope in {"active_window", "active_client", "virtual_desktop"}:
        raise ValueError("region cannot be combined with active_window, active_client, or virtual_desktop scope")
    if scope == "region" and region is None:
        raise ValueError("scope='region' requires region")
    if scope in {"active_window", "active_client"}:
        window = _active_window()
        if not window:
            raise RuntimeError("no active window is available for scoped capture")
        bounds = window.get("client_bounds") if scope == "active_client" else None
        bounds = bounds or {"left": window["left"], "top": window["top"], "width": window["width"], "height": window["height"]}
        region = [bounds["left"], bounds["top"], bounds["width"], bounds["height"]]
    if scope == "virtual_desktop":
        all_screens = True
    elif all_screens:
        scope = "virtual_desktop"
    elif region is not None and scope == "primary":
        scope = "region"
    pg = _pyautogui()
    normalized_region, region_clipped = _normalize_region(region, return_clipped=True)
    virtual = _virtual_screen_bounds()
    screenshot = _capture_pixels(pg, normalized_region, bool(all_screens), virtual)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = SCRATCH_DIR / f"screen_{timestamp}.png"
    screenshot.save(path)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    if normalized_region:
        capture_region = list(normalized_region)
    elif all_screens:
        capture_region = [virtual["left"], virtual["top"], virtual["width"], virtual["height"]]
    else:
        capture_region = [0, 0, int(screenshot.width), int(screenshot.height)]
    screen_origin = {"x": int(capture_region[0]), "y": int(capture_region[1])}
    meta = {
        "image_path": str(path),
        "width": int(screenshot.width),
        "height": int(screenshot.height),
        "screen_origin": screen_origin,
        "capture_region": capture_region,
        "virtual_screen": virtual,
        "region_clipped": bool(region_clipped),
        "scope": scope,
        "immutable": True,
        "sha256": digest.hexdigest(),
        "file_size": int(stat.st_size),
        "file_mtime_ns": int(stat.st_mtime_ns),
    }
    registry_key = os.path.abspath(str(path))
    _CAPTURE_META_REGISTRY[registry_key] = dict(meta)
    while len(_CAPTURE_META_REGISTRY) > 128:
        _CAPTURE_META_REGISTRY.pop(next(iter(_CAPTURE_META_REGISTRY)))
    try:
        with open(f"{path}.meta.json", "w", encoding="utf-8") as mf:
            json.dump(meta, mf)
    except Exception:
        logger.exception("failed to write capture meta for %s", path)
    return _result(
        image_path=str(path),
        width=screenshot.width,
        height=screenshot.height,
        display_index=display_index,
        question=question,
        region=list(normalized_region) if normalized_region else None,
        all_screens=bool(all_screens),
        screen_origin=screen_origin,
        capture_region=capture_region,
        virtual_screen=virtual,
        region_clipped=bool(region_clipped),
        scope=scope,
        immutable=True,
        sha256=digest.hexdigest(),
    )


_TASKBAR_CAPTURE_RE = re.compile(r"\b(taskbar|system tray|notification area|start button|windows search|clock on the taskbar)\b", re.IGNORECASE)


def _capture_for_grounding(descriptions: Any = None, region: Optional[Any] = None) -> Dict[str, Any]:
    """Prefer a high-resolution active-window ROI unless the target is desktop chrome."""
    if region is not None:
        return _capture_screen(scope="region", region=region)
    if isinstance(descriptions, (list, tuple)):
        text = " ".join(str(item) for item in descriptions)
    else:
        text = str(descriptions or "")
    if _TASKBAR_CAPTURE_RE.search(text):
        return _capture_screen(scope="primary")
    if _active_window():
        return _capture_screen(scope="active_window")
    return _capture_screen(scope="primary")


def _observe_stage(
    targets: Optional[List[Dict[str, str]]] = None,
    scope: str = "active_window",
    region: Optional[Any] = None,
    mode: str = "exact",
    backend: Optional[str] = "cpp",
    device: Optional[str] = "cuda",
    timeout_seconds: Optional[float] = None,
    **options: Any,
) -> Dict[str, Any]:
    """Capture one immutable stage and optionally ground all targets against it."""
    started = time.perf_counter()
    capture_started = time.perf_counter()
    capture = _capture_screen(scope=scope, region=region)
    capture_ms = (time.perf_counter() - capture_started) * 1000.0
    grounding = None
    grounding_ms = 0.0
    if targets:
        locate_started = time.perf_counter()
        grounding = _locate_batch(
            targets=targets,
            image_path=capture["image_path"],
            mode=mode,
            backend=backend,
            device=device,
            timeout_seconds=timeout_seconds,
            **options,
        )
        grounding_ms = (time.perf_counter() - locate_started) * 1000.0
    return _result(
        "ok",
        stage_static=True,
        capture=capture,
        grounding=grounding,
        timing={
            "capture_ms": round(capture_ms, 3),
            "grounding_ms": round(grounding_ms, 3),
            "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        },
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
    """Scroll the desktop mouse wheel.

    Positive clicks scroll up; negative clicks scroll down. Uses native Win32
    wheel events by default because pyautogui.scroll() can be a no-op in some
    Windows/Electron targets. Set COMPUTER_USE_SCROLL_BACKEND=pyautogui or both
    to override.
    """
    pg = _pyautogui()
    before = _position()
    target = {"x": int(x), "y": int(y)} if x is not None and y is not None else None
    backend_default = "win32" if os.name == "nt" else "pyautogui"
    backend = os.getenv("COMPUTER_USE_SCROLL_BACKEND", backend_default).strip().lower()
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


def _drag_path(points: List[Dict[str, int]], button: str = "left", duration_per_segment: float = 0.1, tween: str = "linear", hold_after_down: float = 0.08, **_: Any) -> Dict[str, Any]:
    if not points or len(points) < 2:
        raise ValueError("points must contain at least two {x,y} coordinates")
    before = _position()
    drag_info = _perform_drag_path(points, button=button, duration_per_segment=float(duration_per_segment), hold_after_down=float(hold_after_down))
    after = _position()
    return _result(
        before_position=before,
        after_position=after,
        points=drag_info.get("points", points),
        button=button,
        duration_per_segment=float(duration_per_segment),
        tween=tween,
        hold_after_down=float(hold_after_down),
        drag_backend=drag_info.get("backend"),
    )


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


_BATCH_ACTIONS = {"move", "move_relative", "click", "double_click", "type", "press", "scroll", "focus_window", "wait"}
_BATCH_NAVIGATION_KEYS = {"tab", "home", "end", "pageup", "pagedown", "left", "right", "up", "down", "escape"}
_BATCH_HIGH_IMPACT_RE = re.compile(
    r"\b(delete|remove|reset|erase|clear all|empty trash|destroy|wipe|uninstall|submit|send|post|publish|share|"
    r"purchase|buy|pay|checkout|order|transfer|withdraw|confirm|approve|authorize|sign[ -]?in|log[ -]?in|"
    r"sign[ -]?out|log[ -]?out|password|passcode|otp|verification code|two[ -]?factor|security|privacy|"
    r"permission|allow|grant|close|trash|discard|archive|upload|download|overwrite|replace|save|rename|"
    r"move file|restore|install|export|import)\b",
    re.IGNORECASE,
)

_BATCH_SAFE_PURPOSE_RE = {
    "navigate_view": re.compile(r"\b(tab|sidebar|panel|view|section|page|breadcrumb|workspace)\b", re.IGNORECASE),
    "focus_input": re.compile(r"\b(search|filter|query|text|input|field|composer)\b", re.IGNORECASE),
    "expand_collapse": re.compile(r"\b(expand|collapse|disclosure|accordion|details)\b", re.IGNORECASE),
    "choose_option": re.compile(r"\b(dropdown|selector|option|theme|layout|sort|choice)\b", re.IGNORECASE),
    "inspect": re.compile(r"\b(preview|info|information|help|tooltip|details)\b", re.IGNORECASE),
    "select_item": re.compile(r"\b(row|item|card|session|conversation|document|entry)\b", re.IGNORECASE),
}
_BATCH_TWEENS = {"linear", "easeInQuad", "easeOutQuad", "easeInOutQuad", "easeInCubic", "easeOutCubic", "easeInOutCubic"}
_BATCH_FIELDS = {
    "move": {"action", "risk", "x", "y", "duration", "tween"},
    "move_relative": {"action", "risk", "dx", "dy", "duration", "tween"},
    "click": {"action", "risk", "x", "y", "button", "clicks", "interval", "duration", "tween", "target_hint", "target_id", "resolved_target_id", "safe_purpose"},
    "double_click": {"action", "risk", "x", "y", "button", "interval", "duration", "tween", "target_hint", "target_id", "resolved_target_id", "safe_purpose"},
    "type": {"action", "risk", "text", "field_hint", "interval"},
    "press": {"action", "risk", "keys", "presses", "interval"},
    "scroll": {"action", "risk", "clicks", "x", "y"},
    "focus_window": {"action", "risk", "title", "exact"},
    "wait": {"action", "risk", "duration_ms"},
}


def _batch_number(value: Any, *, minimum: float, maximum: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and minimum <= float(value) <= maximum


def _batch_coordinate_pair(step: Dict[str, Any], x_key: str = "x", y_key: str = "y") -> Optional[str]:
    x, y = step.get(x_key), step.get(y_key)
    if not isinstance(x, int) or isinstance(x, bool) or not isinstance(y, int) or isinstance(y, bool):
        return f"requires integer {x_key}/{y_key} coordinates"
    try:
        _ensure_on_screen(x, y)
    except ValueError as exc:
        return str(exc)
    return None


def _batch_block_reason(step: Any, index: int, allow_symbolic: bool = False) -> Optional[str]:
    """Validate one explicitly non-destructive batch step before any action runs."""
    if not isinstance(step, dict):
        return f"step {index} must be an object"
    action = str(step.get("action", "")).strip().lower()
    if action not in _BATCH_ACTIONS:
        return f"step {index} action {action!r} is not allowed in computer_use_batch"
    if step.get("risk") != "non_destructive":
        return f"step {index} must explicitly set risk to 'non_destructive'"
    unknown = set(step) - _BATCH_FIELDS[action]
    if unknown:
        return f"step {index} contains unsupported fields for {action}: {sorted(unknown)}"
    if "duration" in step and not _batch_number(step["duration"], minimum=0, maximum=10):
        return f"step {index} duration must be a finite number from 0 through 10"
    if "interval" in step and not _batch_number(step["interval"], minimum=0, maximum=2):
        return f"step {index} interval must be a finite number from 0 through 2"
    if "tween" in step and str(step["tween"]) not in _BATCH_TWEENS:
        return f"step {index} tween is unsupported"
    if action == "move":
        reason = _batch_coordinate_pair(step)
        if reason:
            return f"step {index} {reason}"
    elif action == "move_relative":
        if not isinstance(step.get("dx"), int) or isinstance(step.get("dx"), bool) or not isinstance(step.get("dy"), int) or isinstance(step.get("dy"), bool):
            return f"step {index} requires integer dx/dy offsets"
        if abs(int(step["dx"])) > 10000 or abs(int(step["dy"])) > 10000:
            return f"step {index} relative offsets exceed the safe bound"
    if action in {"click", "double_click"}:
        if str(step.get("button", "left")).lower() != "left":
            return f"step {index} only supports left clicks in a safe batch"
        hint = str(step.get("target_hint", "")).strip()
        if not hint:
            return f"step {index} requires target_hint describing the visible safe target"
        if _BATCH_HIGH_IMPACT_RE.search(hint):
            return f"step {index} target_hint appears high-impact and is blocked: {hint!r}"
        safe_purpose = str(step.get("safe_purpose", "")).strip()
        purpose_pattern = _BATCH_SAFE_PURPOSE_RE.get(safe_purpose)
        if purpose_pattern is None:
            return f"step {index} requires safe_purpose from {sorted(_BATCH_SAFE_PURPOSE_RE)}"
        if not purpose_pattern.search(hint):
            return f"step {index} target_hint does not match declared safe_purpose {safe_purpose!r}"
        has_coordinates = step.get("x") is not None and step.get("y") is not None
        has_target = bool(str(step.get("target_id", "")).strip())
        if not has_coordinates and not (allow_symbolic and has_target):
            return f"step {index} click actions require explicit x/y or a preflight target_id"
        if has_coordinates and has_target:
            return f"step {index} must use either x/y or target_id, not both"
        if has_coordinates:
            reason = _batch_coordinate_pair(step)
            if reason:
                return f"step {index} {reason}"
        click_count = step.get("clicks", 1)
        if action == "click" and (not isinstance(click_count, int) or isinstance(click_count, bool) or click_count != 1):
            return f"step {index} click action only permits one click; use double_click when appropriate"
    elif action == "type":
        text = step.get("text")
        field_hint = str(step.get("field_hint", "")).strip()
        if not isinstance(text, str) or len(text) > 10000:
            return f"step {index} type action requires a string of at most 10000 characters"
        if not field_hint:
            return f"step {index} requires field_hint describing the non-sensitive field"
        if _BATCH_HIGH_IMPACT_RE.search(field_hint) or _BATCH_HIGH_IMPACT_RE.search(str(text)):
            return f"step {index} type action appears credential or high-impact related and is blocked"
    elif action == "press":
        keys = step.get("keys")
        key_list = keys if isinstance(keys, list) else [keys]
        normalized = [str(key).strip().lower() for key in key_list if key is not None]
        if not normalized or any(key not in _BATCH_NAVIGATION_KEYS for key in normalized):
            return f"step {index} press action only permits navigation keys: {sorted(_BATCH_NAVIGATION_KEYS)}"
        if not isinstance(step.get("presses", 1), int) or isinstance(step.get("presses", 1), bool) or not 1 <= int(step.get("presses", 1)) <= 10:
            return f"step {index} presses must be an integer between 1 and 10"
    elif action == "scroll":
        if not isinstance(step.get("clicks"), int) or isinstance(step.get("clicks"), bool) or not -20 <= int(step["clicks"]) <= 20 or step["clicks"] == 0:
            return f"step {index} scroll clicks must be a non-zero integer between -20 and 20"
        if (step.get("x") is None) != (step.get("y") is None):
            return f"step {index} scroll x and y must be provided together"
        if step.get("x") is not None:
            reason = _batch_coordinate_pair(step)
            if reason:
                return f"step {index} {reason}"
    elif action == "focus_window":
        if not isinstance(step.get("title"), str) or not step["title"].strip() or len(step["title"]) > 512:
            return f"step {index} focus_window action requires title"
        if "exact" in step and not isinstance(step["exact"], bool):
            return f"step {index} focus_window exact must be boolean"
    elif action == "wait":
        duration_ms = step.get("duration_ms")
        if not _batch_number(duration_ms, minimum=0, maximum=10_000):
            return f"step {index} wait duration_ms must be between 0 and 10000"
    return None


def _batch_step_args(action: str, step: Dict[str, Any]) -> Dict[str, Any]:
    """Strip batch-only metadata and irrelevant fields before dispatching a primitive."""
    allowed = {
        "move": {"x", "y", "duration", "tween"},
        "move_relative": {"dx", "dy", "duration", "tween"},
        "click": {"x", "y", "button", "clicks", "interval", "duration", "tween"},
        "double_click": {"x", "y", "button", "interval", "duration", "tween"},
        "type": {"text", "interval"},
        "press": {"keys", "presses", "interval"},
        "scroll": {"clicks", "x", "y"},
        "focus_window": {"title", "exact"},
        "wait": {"duration_ms"},
    }
    return {key: value for key, value in step.items() if key in allowed[action]}


def _batch_step_summary(step: Dict[str, Any]) -> Dict[str, Any]:
    """Return an auditable summary without echoing typed text back to the model."""
    action = str(step.get("action", "")).strip().lower()
    summary: Dict[str, Any] = {"action": action, "risk": "non_destructive"}
    if action in {"click", "double_click"}:
        summary.update({"x": int(step["x"]), "y": int(step["y"]), "target_hint": str(step["target_hint"])})
        if step.get("target_id"):
            summary["target_id"] = str(step["target_id"])
        elif step.get("resolved_target_id"):
            summary["resolved_target_id"] = str(step["resolved_target_id"])
    elif action == "type":
        summary.update({"chars": len(str(step["text"])), "field_hint": str(step["field_hint"])})
    elif action == "press":
        summary["keys"] = step.get("keys")
    elif action == "wait":
        summary["duration_ms"] = float(step["duration_ms"])
    return summary


def _batch_sequence_block_reason(steps: List[Dict[str, Any]]) -> Optional[str]:
    """Require fresh pixels after any action that can invalidate observed state."""
    invalidating = {"click", "double_click", "type", "press", "scroll", "focus_window", "wait"}
    for index, step in enumerate(steps):
        action = str(step.get("action", "")).strip().lower()
        if action not in invalidating:
            continue
        later = steps[index + 1:]
        if action != "wait":
            # A trailing wait may settle this stage; the next action still needs
            # a new observation and belongs in the next stage.
            later = [item for item in later if str(item.get("action", "")).strip().lower() != "wait"]
        if later:
            return f"step {index} action {action!r} can invalidate coordinates; start a fresh stage before the next action"
    return None


def _batch_step_max_seconds(step: Dict[str, Any]) -> float:
    action = str(step.get("action", "")).strip().lower()
    if action == "wait":
        return float(step.get("duration_ms", 0)) / 1000.0
    if action == "type":
        return len(str(step.get("text", ""))) * float(step.get("interval", 0)) + 0.25
    if action == "press":
        return int(step.get("presses", 1)) * float(step.get("interval", 0)) + 0.25
    if action in {"click", "double_click"}:
        clicks = 2 if action == "double_click" else int(step.get("clicks", 1))
        return float(step.get("duration", 0)) + clicks * float(step.get("interval", 0)) + 0.25
    if action in {"move", "move_relative"}:
        return float(step.get("duration", 0)) + 0.25
    return 0.5


_MAX_DYNAMIC_STAGES = 8
_MAX_DYNAMIC_STEPS = 48


def _dynamic_stage_block_reason(stage: Any, stage_index: int) -> Optional[str]:
    if not isinstance(stage, dict):
        return f"stage {stage_index} must be an object"
    steps = stage.get("steps", [])
    targets = stage.get("targets", [])
    scope = str(stage.get("scope") or "active_window")
    if scope not in {"primary", "virtual_desktop", "active_window", "active_client", "region"}:
        return f"stage {stage_index} has unsupported capture scope {scope!r}"
    if scope == "region" and stage.get("region") is None:
        return f"stage {stage_index} scope='region' requires region"
    if stage.get("region") is not None and scope in {"virtual_desktop", "active_window", "active_client"}:
        return f"stage {stage_index} region conflicts with scope {scope!r}"
    if str(stage.get("locate_mode") or "exact") not in {"exact", "auto", "one_pass"}:
        return f"stage {stage_index} locate_mode must be exact, auto, or one_pass"
    if not isinstance(stage.get("locate_options", {}), dict):
        return f"stage {stage_index} locate_options must be an object"
    if not isinstance(steps, list) or len(steps) > 12:
        return f"stage {stage_index} steps must be a list of at most 12 safe actions"
    if steps and stage.get("static_screen") is not True:
        return f"stage {stage_index} must set static_screen=true for its bounded action sequence"
    if not isinstance(targets, list) or len(targets) > 16:
        return f"stage {stage_index} targets must be a list of at most 16 items"
    target_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            return f"stage {stage_index} target must be an object"
        target_id = str(target.get("id", "")).strip()
        description = str(target.get("description", "")).strip()
        if not target_id or not description:
            return f"stage {stage_index} every target requires a non-empty id and description"
        if target_id in target_ids:
            return f"stage {stage_index} target ids must be unique"
        if _BATCH_HIGH_IMPACT_RE.search(description):
            return f"stage {stage_index} target description appears high-impact and is blocked: {description!r}"
        target_ids.add(target_id)
    for step_index, step in enumerate(steps):
        reason = _batch_block_reason(step, step_index, allow_symbolic=bool(targets))
        if reason:
            return f"stage {stage_index}: {reason}"
        target_id = str(step.get("target_id", "")).strip() if isinstance(step, dict) else ""
        if target_id:
            if str(step.get("action", "")).strip().lower() not in {"click", "double_click"}:
                return f"stage {stage_index} symbolic target_id is only allowed for click actions"
            if target_id not in target_ids:
                return f"stage {stage_index} references unknown target_id {target_id!r}"
            description = next(str(item["description"]) for item in targets if str(item["id"]) == target_id)
            purpose_pattern = _BATCH_SAFE_PURPOSE_RE[str(step["safe_purpose"])]
            if not purpose_pattern.search(description):
                return f"stage {stage_index} target {target_id!r} does not match declared safe_purpose"
    sequence_reason = _batch_sequence_block_reason(steps)
    if sequence_reason:
        return f"stage {stage_index}: {sequence_reason}"
    return None


def _dynamic_workflow(
    stages: List[Dict[str, Any]],
    stop_on_failure: bool = True,
    max_duration_ms: int = 120000,
    **_: Any,
) -> Dict[str, Any]:
    """Run bounded safe stages, recapturing and independently grounding every stage."""
    if not isinstance(stages, list) or not stages:
        return _result("error", error="stages must be a non-empty list", executed_stages=0, captures=0)
    if len(stages) > _MAX_DYNAMIC_STAGES:
        return _result("error", error=f"dynamic workflow accepts at most {_MAX_DYNAMIC_STAGES} stages", executed_stages=0, captures=0)
    if not isinstance(max_duration_ms, int) or not 1000 <= max_duration_ms <= 120000:
        return _result("error", error="max_duration_ms must be an integer from 1000 through 120000", executed_stages=0, captures=0)
    total_steps = sum(len(stage.get("steps", [])) for stage in stages if isinstance(stage, dict) and isinstance(stage.get("steps", []), list))
    if total_steps > _MAX_DYNAMIC_STEPS:
        return _result("error", error=f"dynamic workflow accepts at most {_MAX_DYNAMIC_STEPS} total actions", executed_stages=0, captures=0)

    # Whole-workflow safety preflight completes before the first screenshot or action.
    for stage_index, stage in enumerate(stages):
        reason = _dynamic_stage_block_reason(stage, stage_index)
        if reason:
            return _result("blocked", error=reason, blocked_stage=stage_index, planned_stages=len(stages), executed_stages=0, captures=0)

    started = time.monotonic()
    deadline = started + max_duration_ms / 1000.0
    completed: List[Dict[str, Any]] = []
    captures = 0
    executed_actions = 0
    for stage_index, stage in enumerate(stages):
        if time.monotonic() >= deadline:
            return _result("stopped", error="dynamic workflow exceeded max_duration_ms", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=len(completed), executed_actions=executed_actions, captures=captures, stages=completed)
        targets = list(stage.get("targets") or [])
        try:
            observe = _observe_stage(
                targets=targets,
                scope=str(stage.get("scope") or "active_window"),
                region=stage.get("region"),
                mode=str(stage.get("locate_mode") or "exact"),
                backend=stage.get("backend") or "cpp",
                device=stage.get("device") or "cuda",
                timeout_seconds=max(0.001, deadline - time.monotonic()),
                **_locate_payload_options(dict(stage.get("locate_options") or {})),
            )
        except Exception as exc:
            return _result("stopped", error=f"stage {stage_index} observation failed: {exc}", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=len(completed), executed_actions=executed_actions, captures=captures, stages=completed)
        captures += 1
        if observe.get("status") != "ok":
            completed.append({"index": stage_index, "status": "error", "observation": observe})
            return _result("stopped", error=f"stage {stage_index} observation returned {observe.get('status')}", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=len(completed) - 1, executed_actions=executed_actions, captures=captures, stages=completed)
        if time.monotonic() >= deadline:
            completed.append({"index": stage_index, "status": "timeout", "observation": observe})
            return _result("stopped", error="dynamic workflow exceeded max_duration_ms before actions", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=len(completed) - 1, executed_actions=executed_actions, captures=captures, stages=completed)
        grounding = observe.get("grounding")
        target_results = {
            str(item.get("id")): item
            for item in (grounding or {}).get("targets", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        missing = [
            str(target["id"]) for target in targets
            if target_results.get(str(target["id"]), {}).get("status") != "found"
            or not target_results.get(str(target["id"]), {}).get("center")
            or target_results.get(str(target["id"]), {}).get("screen_coordinates_valid") is not True
        ]
        if missing:
            completed.append({"index": stage_index, "status": "not_found", "observation": observe, "missing_targets": missing})
            return _result("stopped", error=f"stage {stage_index} grounding failed for targets: {', '.join(missing)}", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=stage_index, executed_actions=executed_actions, captures=captures, stages=completed)

        resolved_steps: List[Dict[str, Any]] = []
        resolved_targets: Dict[str, Dict[str, int]] = {}
        for raw_step in stage.get("steps", []):
            step = dict(raw_step)
            target_id = str(step.pop("target_id", "")).strip()
            if target_id:
                center = target_results[target_id]["center"]
                resolved = {"x": int(center["x"]), "y": int(center["y"])}
                resolved_targets[target_id] = resolved
                step.update(resolved)
                step["resolved_target_id"] = target_id
            resolved_steps.append(step)
        batch = _computer_use_batch(resolved_steps, stop_on_failure=stop_on_failure, deadline=deadline) if resolved_steps else _result("ok", planned_steps=0, executed_steps=0, steps=[])
        executed_actions += int(batch.get("executed_steps", 0))
        completed.append({
            "index": stage_index,
            "status": batch.get("status"),
            "observation": observe,
            "resolved_targets": resolved_targets,
            "batch": batch,
        })
        if batch.get("status") != "ok" and stop_on_failure:
            return _result("stopped", error=f"stage {stage_index} action batch returned {batch.get('status')}", stopped_stage=stage_index, planned_stages=len(stages), executed_stages=stage_index, executed_actions=executed_actions, captures=captures, stages=completed)
    return _result("ok", planned_stages=len(stages), executed_stages=len(completed), executed_actions=executed_actions, captures=captures, duration_ms=round((time.monotonic() - started) * 1000.0, 1), stages=completed)


def _computer_use_batch(
    steps: List[Dict[str, Any]],
    stop_on_failure: bool = True,
    targets: Optional[List[Dict[str, str]]] = None,
    image_path: Optional[str] = None,
    locate_mode: str = "exact",
    static_screen: bool = False,
    backend: Optional[str] = None,
    python: Optional[str] = None,
    deadline: Optional[float] = None,
    **locate_options: Any,
) -> Dict[str, Any]:
    """Execute a short, prevalidated sequence of explicitly non-destructive GUI actions.

    The preflight is intentionally all-or-nothing: if any requested step is unsafe
    or malformed, nothing is executed.  This avoids a batch partly running before
    a later high-impact operation is discovered.
    """
    if not isinstance(steps, list) or not steps:
        return _result("error", error="steps must be a non-empty list")
    if len(steps) > 12:
        return _result("error", error="computer_use_batch accepts at most 12 steps")
    symbolic = bool(targets)
    if symbolic and not static_screen:
        return _result(
            "blocked",
            error="symbolic targets require static_screen=true to acknowledge that all coordinates remain valid for the complete batch",
            planned_steps=len(steps),
            executed_steps=0,
        )
    target_specs: Dict[str, Dict[str, str]] = {}
    if targets is not None:
        if not isinstance(targets, list) or not targets:
            return _result("error", error="targets must be a non-empty list when provided")
        for target in targets:
            if not isinstance(target, dict):
                return _result("error", error="every target must be an object")
            target_id = str(target.get("id", "")).strip()
            description = str(target.get("description", "")).strip()
            if not target_id or not description:
                return _result("error", error="every target requires non-empty id and description")
            if target_id in target_specs:
                return _result("error", error="target ids must be unique")
            if _BATCH_HIGH_IMPACT_RE.search(description):
                return _result(
                    "blocked",
                    error=f"symbolic target description appears high-impact and is blocked: {description!r}",
                    planned_steps=len(steps), executed_steps=0,
                )
            target_specs[target_id] = {"id": target_id, "description": description}
    for index, step in enumerate(steps):
        reason = _batch_block_reason(step, index, allow_symbolic=symbolic)
        if reason:
            return _result("blocked", error=reason, blocked_step=index, planned_steps=len(steps), executed_steps=0)
        target_id = str(step.get("target_id", "")).strip() if isinstance(step, dict) else ""
        if target_id and target_id not in target_specs:
            return _result(
                "blocked", error=f"step {index} references unknown target_id {target_id!r}",
                blocked_step=index, planned_steps=len(steps), executed_steps=0,
            )
        if target_id:
            purpose_pattern = _BATCH_SAFE_PURPOSE_RE[str(step["safe_purpose"])]
            if not purpose_pattern.search(target_specs[target_id]["description"]):
                return _result(
                    "blocked", error=f"step {index} target description does not match declared safe_purpose",
                    blocked_step=index, planned_steps=len(steps), executed_steps=0,
                )
    sequence_reason = _batch_sequence_block_reason(steps)
    if sequence_reason:
        return _result("blocked", error=sequence_reason, planned_steps=len(steps), executed_steps=0)

    locate_result: Optional[Dict[str, Any]] = None
    resolved_targets: Dict[str, Dict[str, int]] = {}
    resolved_steps = [dict(step) for step in steps]
    if symbolic:
        remaining_timeout = None if deadline is None else deadline - time.monotonic()
        if remaining_timeout is not None and remaining_timeout <= 0:
            return _result("stopped", error="batch deadline expired before grounding", planned_steps=len(steps), executed_steps=0)
        locate_result = _locate_batch(
            targets=list(target_specs.values()),
            image_path=image_path,
            mode=locate_mode,
            backend=backend,
            python=python,
            timeout_seconds=remaining_timeout,
            **locate_options,
        )
        target_results = {
            str(item.get("id")): item
            for item in locate_result.get("targets") or []
            if isinstance(item, dict) and item.get("id") is not None
        }
        referenced = {str(step.get("target_id")) for step in steps if step.get("target_id")}
        missing = [
            target_id for target_id in sorted(referenced)
            if target_results.get(target_id, {}).get("status") != "found"
            or not target_results.get(target_id, {}).get("center")
            or target_results.get(target_id, {}).get("screen_coordinates_valid") is not True
        ]
        if missing:
            return _result(
                "not_found",
                error=f"symbolic preflight failed for targets: {', '.join(missing)}",
                planned_steps=len(steps), executed_steps=0,
                locate_batch=locate_result,
            )
        for target_id in referenced:
            center = target_results[target_id]["center"]
            resolved_targets[target_id] = {"x": int(center["x"]), "y": int(center["y"])}
        for step in resolved_steps:
            target_id = str(step.get("target_id", "")).strip()
            if target_id:
                step.update(resolved_targets[target_id])

    handlers = {
        "move": _move,
        "move_relative": _move_relative,
        "click": _click,
        "double_click": _double_click,
        "type": _type,
        "press": _press,
        "scroll": _scroll,
        "focus_window": _focus_window,
    }
    started = time.monotonic()
    results: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(resolved_steps):
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or _batch_step_max_seconds(raw_step) > remaining:
                return _result(
                    "stopped", error="batch deadline expired before the next action", stopped_at=index,
                    planned_steps=len(steps), executed_steps=len(results),
                    duration_ms=round((time.monotonic() - started) * 1000, 1), steps=results,
                    resolved_targets=resolved_targets, locate_batch=locate_result,
                )
        step = dict(raw_step)
        action = str(step.pop("action")).strip().lower()
        step = _batch_step_args(action, step)
        summary = _batch_step_summary(raw_step)
        try:
            if action == "wait":
                duration_ms = float(step.pop("duration_ms"))
                if not DRY_RUN:
                    time.sleep(duration_ms / 1000)
                result = _result(duration_ms=duration_ms, action="wait")
            else:
                result = handlers[action](**step)
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "error_type": type(exc).__name__, "dry_run": DRY_RUN}
        results.append({"index": index, "step": summary, "result": result})
        if result.get("status") != "ok" and stop_on_failure:
            return _result(
                "stopped",
                error=f"step {index} returned {result.get('status')}",
                stopped_at=index,
                planned_steps=len(steps),
                executed_steps=len(results),
                duration_ms=round((time.monotonic() - started) * 1000, 1),
                steps=results,
                resolved_targets=resolved_targets,
                locate_batch=locate_result,
            )
    return _result(
        planned_steps=len(steps),
        executed_steps=len(results),
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        stop_on_failure=bool(stop_on_failure),
        steps=results,
        resolved_targets=resolved_targets,
        locate_batch=locate_result,
    )


_CODE_ACTIONS = {
    "move": {"x", "y", "duration", "tween"},
    "move_relative": {"dx", "dy", "duration", "tween"},
    "click": {"x", "y", "target_hint", "safe_purpose", "duration", "tween"},
    "double_click": {"x", "y", "target_hint", "safe_purpose", "duration", "tween"},
    "type": {"text", "field_hint", "interval"},
    "press": {"keys", "presses", "interval"},
    "scroll": {"clicks", "x", "y"},
    "focus_window": {"title", "exact"},
    "wait": {"duration_ms"},
}
_MAX_CODE_STEPS = 48


def _literal_code_value(node: ast.AST) -> Any:
    """Accept only literal call arguments; code never receives Python objects."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError("arguments must be literal strings, numbers, booleans, lists, or dicts") from exc


def _compile_safe_code_statements(statements: List[ast.stmt], multiplier: int = 1) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for statement in statements:
        if isinstance(statement, ast.For):
            if not isinstance(statement.target, ast.Name) or statement.target.id != "_" or not isinstance(statement.iter, ast.Call):
                raise ValueError("only 'for _ in range(<literal>)' loops are allowed")
            call = statement.iter
            if not isinstance(call.func, ast.Name) or call.func.id != "range" or call.keywords:
                raise ValueError("only 'for _ in range(<literal>)' loops are allowed")
            if len(call.args) != 1:
                raise ValueError("range requires exactly one non-negative literal count")
            count = _literal_code_value(call.args[0])
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("range requires exactly one non-negative literal count")
            if multiplier * count > _MAX_CODE_STEPS:
                raise ValueError(f"code expands to more than {_MAX_CODE_STEPS} safe steps")
            steps.extend(_compile_safe_code_statements(statement.body, multiplier * count))
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise ValueError("only safe action calls and bounded range loops are allowed")
        call = statement.value
        if not isinstance(call.func, ast.Name) or call.func.id not in _CODE_ACTIONS:
            raise ValueError(f"unsupported action; allowed: {sorted(_CODE_ACTIONS)}")
        if call.args:
            raise ValueError("safe action calls use keyword arguments only")
        action = call.func.id
        kwargs: Dict[str, Any] = {}
        for keyword in call.keywords:
            if keyword.arg is None or keyword.arg not in _CODE_ACTIONS[action]:
                raise ValueError(f"{action} received an unsupported argument")
            if keyword.arg in kwargs:
                raise ValueError(f"{action} received duplicate argument {keyword.arg!r}")
            kwargs[keyword.arg] = _literal_code_value(keyword.value)
        step = {"action": action, "risk": "non_destructive", **kwargs}
        steps.extend([dict(step) for _ in range(multiplier)])
        if len(steps) > _MAX_CODE_STEPS:
            raise ValueError(f"code expands to more than {_MAX_CODE_STEPS} safe steps")
    return steps


def _computer_use_execute_code(code: str, static_screen: bool = False, stop_on_failure: bool = True) -> Dict[str, Any]:
    """Execute a restricted, preflighted THEIA action program for fixed safe UI stages.

    This is deliberately not arbitrary Python. The AST accepts only calls to the
    same non-destructive primitives as ``computer_use_batch`` and bounded literal
    ``for _ in range(n)`` loops. The complete expanded plan is validated before
    dispatching it in 12-step batch chunks, eliminating agent round trips without
    offering imports, file/network access, eval, assignments, or arbitrary code.
    """
    if not static_screen:
        return _result(
            "blocked",
            error="computer_use_execute_code requires static_screen=true; use staged captures for any layout-changing action",
            executed_steps=0,
        )
    if not isinstance(code, str) or not code.strip():
        return _result("error", error="code must be a non-empty safe action program")
    try:
        tree = ast.parse(code, mode="exec")
        steps = _compile_safe_code_statements(tree.body)
    except (SyntaxError, ValueError) as exc:
        return _result("blocked", error=f"unsafe or invalid THEIA code: {exc}", executed_steps=0)
    if not steps:
        return _result("error", error="code produced no actions", executed_steps=0)
    if len(steps) > _MAX_CODE_STEPS:
        return _result("blocked", error=f"code expands to more than {_MAX_CODE_STEPS} safe steps", executed_steps=0)

    # Whole-program preflight happens before the first chunk executes.
    for index, step in enumerate(steps):
        reason = _batch_block_reason(step, index)
        if reason:
            return _result("blocked", error=reason, blocked_step=index, planned_steps=len(steps), executed_steps=0)
    sequence_reason = _batch_sequence_block_reason(steps)
    if sequence_reason:
        return _result("blocked", error=sequence_reason, planned_steps=len(steps), executed_steps=0)

    started = time.monotonic()
    chunks: List[Dict[str, Any]] = []
    executed = 0
    for chunk_start in range(0, len(steps), 12):
        chunk = steps[chunk_start:chunk_start + 12]
        result = _computer_use_batch(chunk, stop_on_failure=stop_on_failure)
        chunks.append(result)
        executed += int(result.get("executed_steps", 0))
        if result.get("status") != "ok" and stop_on_failure:
            return _result(
                "stopped", error=f"chunk {len(chunks) - 1} returned {result.get('status')}",
                planned_steps=len(steps), executed_steps=executed,
                chunks=chunks, duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
    return _result(
        planned_steps=len(steps), executed_steps=executed, chunks=chunks,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
    )


def _worker_script_path() -> Path:
    return Path(__file__).with_name("windows_computer_use_locate_worker.py")


def _locate_worker_default_venv() -> Path:
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes" / "theia-ui-computer-use" / "locate-worker" / ".venv"
    return _hermes_home() / "theia-ui-computer-use" / "locate-worker" / ".venv"


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _locate_setup_script() -> Path:
    return Path(__file__).resolve().parent / "scripts" / "setup_locate_worker.py"


def _locate_worker_status() -> Dict[str, Any]:
    venv = _locate_worker_default_venv()
    status_path = venv / "locate-worker-status.json"
    data: Dict[str, Any] = {"target": str(venv), "python": str(_venv_python(venv)), "python_exists": _venv_python(venv).exists()}
    if status_path.exists():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception as exc:
            data["status_file_error"] = str(exc)
    return data


def _start_locate_worker_bootstrap() -> Dict[str, Any]:
    if os.getenv("THEIA_AUTO_INSTALL_LOCATE_WORKER", "true").strip().lower() in {"0", "false", "no", "off"}:
        return {"status": "disabled", "reason": "THEIA_AUTO_INSTALL_LOCATE_WORKER=false"}
    script = _locate_setup_script()
    if not script.exists():
        return {"status": "error", "error": f"setup script not found: {script}"}
    try:
        subprocess.Popen(
            [sys.executable, str(script), "--torch", os.getenv("THEIA_LOCATE_TORCH", "auto")],
            cwd=str(Path(__file__).resolve().parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=(os.name != "nt"),
        )
        status = _locate_worker_status()
        status.update({"status": "installing", "setup_script": str(script)})
        return status
    except Exception as exc:
        return {"status": "error", "error": str(exc), "setup_script": str(script)}


def _external_python_path(explicit: Optional[str] = None) -> Optional[str]:
    candidates: List[str] = []
    for value in [explicit, os.getenv("COMPUTER_USE_LOCATE_PYTHON")]:
        if value:
            candidates.append(str(value))
    candidates.append(str(_venv_python(_locate_worker_default_venv())))
    # Safe defaults: only use already-existing interpreters outside Hermes' venv.
    candidates.extend([r"C:\Python312\python.exe", r"C:\Python311\python.exe", "/usr/local/bin/python3", "/usr/bin/python3"])
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
_EXTERNAL_WORKER_SIGNATURE = None
_EXTERNAL_WORKER_EOF = object()
_EXTERNAL_WORKER_LOCK = threading.Lock()
_EXTERNAL_WORKER_CALL_LOCK = threading.Lock()


def _external_worker_signature(external_python: str) -> Tuple[Any, ...]:
    """Return the process identity for code/config that is fixed at worker start."""
    worker = _worker_script_path()
    try:
        stat = worker.stat()
        code_identity: Tuple[Any, ...] = (str(worker.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        code_identity = (str(worker), None, None)
    config = tuple(
        sorted(
            (key, value)
            for key, value in os.environ.items()
            if key.startswith("COMPUTER_USE_LOCATE_")
        )
    )
    return (str(Path(external_python)), code_identity, config)


def _dispose_external_worker_locked() -> bool:
    """Terminate and forget the current worker. Caller holds worker/call lock."""
    global _EXTERNAL_WORKER_PROC, _EXTERNAL_WORKER_PYTHON, _EXTERNAL_WORKER_QUEUE, _EXTERNAL_WORKER_SIGNATURE
    proc = _EXTERNAL_WORKER_PROC
    terminated = False
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            terminated = True
        except Exception:
            logger.exception("failed to terminate LocateAnything worker")
    # Replacing the queue is deliberate: late output from the old reader remains
    # isolated in its old queue and cannot be mistaken for a new response.
    _EXTERNAL_WORKER_PROC = None
    _EXTERNAL_WORKER_PYTHON = None
    _EXTERNAL_WORKER_QUEUE = None
    _EXTERNAL_WORKER_SIGNATURE = None
    return terminated


def _start_persistent_external_worker(python: Optional[str] = None) -> Dict[str, Any]:
    global _EXTERNAL_WORKER_PROC, _EXTERNAL_WORKER_PYTHON, _EXTERNAL_WORKER_QUEUE, _EXTERNAL_WORKER_SIGNATURE
    external_python = _external_python_path(python)
    if not external_python:
        return {"status": "error", "backend": "external", "error": "No LocateAnything worker Python is ready yet. THEIA auto-installs one outside the Hermes venv by default; set COMPUTER_USE_LOCATE_PYTHON manually or run scripts/setup_locate_worker.py if needed."}
    worker = _worker_script_path()
    if not worker.exists():
        return {"status": "error", "backend": "external", "error": f"Locate worker script not found: {worker}", "python": external_python}
    signature = _external_worker_signature(external_python)
    with _EXTERNAL_WORKER_LOCK:
        if (
            _EXTERNAL_WORKER_PROC is not None
            and _EXTERNAL_WORKER_PROC.poll() is None
            and _EXTERNAL_WORKER_PYTHON == external_python
            and _EXTERNAL_WORKER_SIGNATURE == signature
        ):
            return {"status": "ok", "backend": "external", "python": external_python, "worker": str(worker), "persistent": True}
        invalidated = _EXTERNAL_WORKER_PROC is not None
        _dispose_external_worker_locked()
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
            try:
                for line in proc.stdout:
                    q.put(line)
            finally:
                q.put(_EXTERNAL_WORKER_EOF)
        threading.Thread(target=_reader, daemon=True).start()
        _EXTERNAL_WORKER_PROC = proc
        _EXTERNAL_WORKER_PYTHON = external_python
        _EXTERNAL_WORKER_QUEUE = q
        _EXTERNAL_WORKER_SIGNATURE = signature
        return {"status": "ok", "backend": "external", "python": external_python, "worker": str(worker), "persistent": True, "invalidated_previous": invalidated}


def _call_persistent_external_worker(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    # A single worker owns one native model/GPU context. Serialize the complete
    # request/response transaction so callers can never run native inference in
    # parallel or consume each other's stdout.
    with _EXTERNAL_WORKER_CALL_LOCK:
        started = _start_persistent_external_worker(python)
        if started.get("status") == "error":
            return started
        proc = _EXTERNAL_WORKER_PROC
        q = _EXTERNAL_WORKER_QUEUE
        if proc is None or proc.stdin is None or q is None or proc.poll() is not None:
            return {"status": "error", "backend": "external", "error": "persistent external worker is not running", "start": started}
        request = dict(payload)
        request_id = str(request.get("request_id") or uuid.uuid4())
        request["request_id"] = request_id
        timeout_seconds = float(timeout or os.getenv("COMPUTER_USE_LOCATE_WORKER_TIMEOUT", "300"))
        deadline = time.monotonic() + timeout_seconds
        stale = 0
        try:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Empty
                line = q.get(timeout=remaining)
                if line is _EXTERNAL_WORKER_EOF:
                    raise RuntimeError(f"persistent external worker exited while awaiting response (exit={proc.poll()})")
                data = json.loads(line)
                if data.get("request_id") != request_id:
                    stale += 1
                    continue
                data.setdefault("backend", "external")
                data.setdefault("python", _EXTERNAL_WORKER_PYTHON)
                data["persistent"] = True
                data["stale_responses_discarded"] = stale
                return data
        except Empty:
            worker_python = _EXTERNAL_WORKER_PYTHON
            _dispose_external_worker_locked()
            return {
                "status": "error",
                "backend": "external",
                "error": "persistent external worker timed out",
                "python": worker_python,
                "persistent": True,
                "request_id": request_id,
                "stale_responses_discarded": stale,
                "worker_restarted": True,
            }
        except Exception as exc:
            worker_python = _EXTERNAL_WORKER_PYTHON
            _dispose_external_worker_locked()
            return {
                "status": "error",
                "backend": "external",
                "error": str(exc),
                "python": worker_python,
                "persistent": True,
                "request_id": request_id,
                "stale_responses_discarded": stale,
                "worker_restarted": True,
            }


def _external_worker_call(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    persistent = os.getenv("COMPUTER_USE_LOCATE_PERSISTENT", "true").strip().lower() not in {"0", "false", "no", "off"}
    if persistent:
        return _call_persistent_external_worker(payload, python=python, timeout=timeout)
    return _run_external_locate_worker(payload, python=python, timeout=timeout)


def _run_external_locate_worker(payload: Dict[str, Any], python: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
    external_python = _external_python_path(python)
    if not external_python:
        return {"status": "error", "backend": "external", "error": "No LocateAnything worker Python is ready yet. THEIA auto-installs one outside the Hermes venv by default; set COMPUTER_USE_LOCATE_PYTHON manually or run scripts/setup_locate_worker.py if needed."}
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
    value = backend or os.getenv("COMPUTER_USE_LOCATE_BACKEND", "cpp")
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
        model_id = os.getenv("COMPUTER_USE_LOCATE_MODEL", "nvidia/LocateAnything-3B")  # fallback; cpp uses GGUF via env
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
    if pref in {"external", "worker", "cpp"}:
        external = _external_worker_call({"action": "warm", "backend": pref, "device": device, "model_id": os.getenv("COMPUTER_USE_LOCATE_MODEL")}, python=python)
        if external.get("status") == "error" and not _external_python_path(python):
            external["bootstrap"] = _start_locate_worker_bootstrap()
        return external
    external_python = _external_python_path(python)
    if pref == "auto" and external_python:
        external = _external_worker_call({"action": "warm", "backend": "auto", "device": device, "model_id": os.getenv("COMPUTER_USE_LOCATE_MODEL")}, python=python, timeout=90)
        if external.get("status") in {"loaded", "already_loaded"}:
            return external
    elif pref == "auto":
        bootstrap = _start_locate_worker_bootstrap()
        if bootstrap.get("status") in {"installing", "in_progress"}:
            return {"status": "installing", "backend": "external", "bootstrap": bootstrap, "fallback": "basic desktop controls remain available while LocateAnything installs"}
    internal = _locate_model.load(device=device)
    internal.setdefault("backend", "internal")
    return internal


def _default_locate_max_side() -> int:
    return int(os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "1024"))


def _load_capture_meta(image_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not image_path:
        return None
    absolute = os.path.abspath(str(image_path))
    try:
        stat = os.stat(absolute)
    except OSError:
        return None
    registered = _CAPTURE_META_REGISTRY.get(absolute)
    if registered:
        if int(registered.get("file_size", -1)) == int(stat.st_size) and int(registered.get("file_mtime_ns", -1)) == int(stat.st_mtime_ns):
            out = dict(registered)
            out["metadata_provenance"] = "trusted_runtime_registry"
            return out
        _CAPTURE_META_REGISTRY.pop(absolute, None)
    meta_path = f"{absolute}.meta.json"
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            meta = json.load(mf)
        if not isinstance(meta, dict) or meta.get("immutable") is not True:
            return None
        expected = str(meta.get("sha256", "")).strip().lower()
        if len(expected) != 64 or int(meta.get("file_size", -1)) != int(stat.st_size) or int(meta.get("file_mtime_ns", -1)) != int(stat.st_mtime_ns):
            return None
        digest = hashlib.sha256()
        with open(absolute, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            return None
        meta["metadata_provenance"] = "verified_sidecar"
        return meta
    except Exception:
        return None


def _screen_adjust_locate_hit(hit: Dict[str, Any], image_path: Optional[str]) -> Dict[str, Any]:
    """Map locate results from crop captures to absolute screen pixels."""
    if not hit or hit.get("status") != "found":
        return hit
    meta = _load_capture_meta(image_path)
    if not meta:
        out = dict(hit)
        out["coordinate_space"] = "image_pixels_unverified"
        out["screen_coordinates_valid"] = False
        out["coordinate_error"] = "trusted capture metadata is unavailable"
        return out
    ox = int(meta.get("screen_origin", {}).get("x", 0))
    oy = int(meta.get("screen_origin", {}).get("y", 0))
    out = dict(hit)
    if ox == 0 and oy == 0:
        out["coordinate_space"] = "screen_pixels"
        out["screen_coordinates_valid"] = True
        out["capture_metadata_provenance"] = meta.get("metadata_provenance")
        return out

    def _shift_point(p: Dict[str, int]) -> Dict[str, int]:
        return {"x": int(p["x"]) + ox, "y": int(p["y"]) + oy}

    def _shift_box(b: Dict[str, int]) -> Dict[str, int]:
        return {
            "x1": int(b["x1"]) + ox,
            "y1": int(b["y1"]) + oy,
            "x2": int(b["x2"]) + ox,
            "y2": int(b["y2"]) + oy,
        }

    if out.get("center"):
        out["center"] = _shift_point(out["center"])
    if out.get("box"):
        out["box"] = _shift_box(out["box"])
    if out.get("boxes"):
        out["boxes"] = [_shift_box(b) for b in out["boxes"]]
    if out.get("points"):
        out["points"] = [_shift_point(p) for p in out["points"]]
    out["coordinate_space"] = "screen_pixels"
    out["screen_coordinates_valid"] = True
    out["capture_metadata_provenance"] = meta.get("metadata_provenance")
    out["screen_origin"] = {"x": ox, "y": oy}
    return out


def _pick_anchor_point(hit: Dict[str, Any], anchor: str = "center") -> Tuple[int, int]:
    anchor = (anchor or "center").strip().lower()
    box = hit.get("box")
    center = hit.get("center")
    if box:
        x1, y1, x2, y2 = int(box["x1"]), int(box["y1"]), int(box["x2"]), int(box["y2"])
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        margin = max(2, min(14, (y2 - y1) // 8))
        if anchor in {"top", "top_center"}:
            return cx, y1 + margin
        if anchor in {"bottom", "bottom_center"}:
            return cx, y2 - margin
        if anchor in {"left_center"}:
            return x1 + margin, cy
        if anchor in {"right_center"}:
            return x2 - margin, cy
        return cx, cy
    if center:
        return int(center["x"]), int(center["y"])
    raise ValueError("locate hit has no box/center to derive drag point")


def _interpolate_drag_points(x1: int, y1: int, x2: int, y2: int, segments: int) -> List[Dict[str, int]]:
    segments = max(2, int(segments))
    points: List[Dict[str, int]] = []
    for i in range(segments):
        t = i / (segments - 1)
        points.append({"x": int(round(x1 + (x2 - x1) * t)), "y": int(round(y1 + (y2 - y1) * t))})
    return points


def _drag_gesture_backend() -> str:
    default = "win32" if os.name == "nt" else "pyautogui"
    return os.getenv("COMPUTER_USE_DRAG_BACKEND", default).strip().lower()


def _win32_mouse_button_event(button: str, down: bool) -> int:
    if button == "right":
        return 0x0008 if down else 0x0010
    if button == "middle":
        return 0x0020 if down else 0x0040
    return 0x0002 if down else 0x0004


def _perform_drag_path(
    points: List[Dict[str, int]],
    button: str = "left",
    duration_per_segment: float = 0.1,
    hold_after_down: float = 0.08,
) -> Dict[str, Any]:
    if not points or len(points) < 2:
        raise ValueError("drag path requires at least two points")
    normalized: List[Dict[str, int]] = []
    for p in points:
        x, y = int(p["x"]), int(p["y"])
        _ensure_on_screen(x, y)
        normalized.append({"x": x, "y": y})
    backend = _drag_gesture_backend()
    if DRY_RUN:
        return {"backend": backend, "points": normalized, "dry_run": True}
    if os.name == "nt" and backend in {"win32", "native", "both"}:
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetCursorPos(normalized[0]["x"], normalized[0]["y"])
        time.sleep(0.03)
        user32.mouse_event(_win32_mouse_button_event(button, True), 0, 0, 0, 0)
        time.sleep(float(hold_after_down))
        for p in normalized[1:]:
            user32.SetCursorPos(p["x"], p["y"])
            time.sleep(float(duration_per_segment))
        user32.mouse_event(_win32_mouse_button_event(button, False), 0, 0, 0, 0)
        return {"backend": "win32", "points": normalized, "hold_after_down": float(hold_after_down)}
    pg = _pyautogui()
    pg.moveTo(normalized[0]["x"], normalized[0]["y"])
    pg.mouseDown(button=button)
    time.sleep(float(hold_after_down))
    try:
        for p in normalized[1:]:
            pg.moveTo(p["x"], p["y"], duration=float(duration_per_segment), tween=pg.linear)
    finally:
        pg.mouseUp(button=button)
    return {"backend": "pyautogui", "points": normalized, "hold_after_down": float(hold_after_down)}


def _locate_drag_defaults(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "generation_mode": "slow",
        "max_side": _default_locate_max_side(),
        "strategy": "coarse_refine",
        "output_type": "box",
        "task": "single",
    }
    merged = dict(defaults)
    for key, value in kwargs.items():
        if value is not None:
            merged[key] = value
    return merged


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
        image_path = _capture_for_grounding(description)["image_path"]
    pref = _locate_backend_preference(backend)
    model_id = os.getenv("COMPUTER_USE_LOCATE_MODEL")
    if pref in {"external", "worker", "cpp"}:
        # cpp is handled inside the worker via _locate_with_cpp when COMPUTER_USE_LOCATE_BACKEND=cpp
        hit = _external_worker_call({
            "action": "locate",
            "backend": pref,
            "description": description,
            "image_path": image_path,
            "threshold": threshold,
            "device": device,
            "model_id": model_id,
            "max_side": _default_locate_max_side(),
            "max_new_tokens": int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")),
            **_locate_payload_options(_),
        }, python=python)
        return [_screen_adjust_locate_hit(hit, image_path)]
    external_python = _external_python_path(python)
    if pref == "auto" and external_python:
        external = _external_worker_call({
            "action": "locate",
            "backend": "auto",
            "description": description,
            "image_path": image_path,
            "threshold": threshold,
            "device": device,
            "model_id": model_id,
            "max_side": _default_locate_max_side(),
            "max_new_tokens": int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")),
            **_locate_payload_options(_),
        }, python=python)
        if external.get("status") in {"found", "not_found"}:
            return [_screen_adjust_locate_hit(external, image_path)]
        # Auto mode can fall back to internal. Explicit external mode returns the external error above.
    elif pref == "auto":
        bootstrap = _start_locate_worker_bootstrap()
        if bootstrap.get("status") in {"installing", "in_progress"}:
            return [{"status": "installing", "backend": "external", "description": description, "image_path": image_path, "bootstrap": bootstrap, "fallback": "basic desktop controls remain available while LocateAnything installs"}]
    load = _locate_model.load(device=device)
    if load.get("status") == "error":
        return [{"status": "error", "backend": "internal", "error": load.get("error"), "load": load}]
    Image = _pil_image()
    image = Image.open(image_path).convert("RGB")
    original_width, original_height = image.size
    infer_image = image.copy()
    max_side = _default_locate_max_side()
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
        return [_screen_adjust_locate_hit({
            "status": "found", "backend": "internal", "description": description, "image_path": image_path,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "center": {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2},
            "raw": text, "score": 1.0, "threshold": threshold, "device": _locate_model.device,
        }, image_path)]
    except Exception as exc:
        logger.exception("locate failed")
        return [{"status": "error", "backend": "internal", "error": str(exc), "description": description, "image_path": image_path, "device": _locate_model.device}]


def _locate_batch(
    targets: List[Dict[str, str]],
    image_path: Optional[str] = None,
    mode: str = "exact",
    threshold: float = 0.3,
    device: Optional[str] = None,
    backend: Optional[str] = None,
    python: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    **options: Any,
) -> Dict[str, Any]:
    """Resolve multiple symbolic targets from one immutable screenshot.

    ``one_pass`` uses LocateAnything's multi-category/PBD path. ``auto`` first
    tries that path and falls back to independent prompts when labels cannot be
    mapped exactly. ``exact`` always uses independent prompts while the native
    DLL reuses the image's prepared vision features.
    """
    if not isinstance(targets, list) or not targets:
        return _result("error", error="targets must be a non-empty list")
    if not image_path:
        capture = _capture_for_grounding([target.get("description", "") for target in targets if isinstance(target, dict)])
        image_path = capture["image_path"]
    pref = _locate_backend_preference(backend)
    if pref == "internal":
        resolved: List[Dict[str, Any]] = []
        for target in targets:
            target_id = str(target.get("id", "")).strip()
            description = str(target.get("description", "")).strip()
            hits = _locate(
                description=description, image_path=image_path, threshold=threshold,
                device=device, backend="internal", python=python, **options,
            )
            hit = dict(hits[0] if hits else {"status": "error", "error": "no locate response"})
            hit.update({"id": target_id, "description": description})
            resolved.append(hit)
        status = "found" if all(item.get("status") == "found" for item in resolved) else "partial"
        return _result(status, targets=resolved, image_path=image_path, mode_requested=mode, mode_used="exact_internal")

    payload = {
        "action": "locate_batch",
        "backend": pref,
        "targets": targets,
        "image_path": image_path,
        "mode": mode,
        "threshold": threshold,
        "device": device,
        "model_id": os.getenv("COMPUTER_USE_LOCATE_MODEL"),
        "max_side": _default_locate_max_side(),
        "max_new_tokens": int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")),
        **_locate_payload_options(options),
    }
    trusted_meta = _load_capture_meta(image_path)
    if trusted_meta:
        payload["image_identity"] = [
            os.path.abspath(str(image_path)), int(trusted_meta["file_size"]),
            int(trusted_meta["file_mtime_ns"]), str(trusted_meta["sha256"]),
        ]
    result = _external_worker_call(payload, python=python, timeout=timeout_seconds)
    adjusted = dict(result)
    adjusted["targets"] = [
        _screen_adjust_locate_hit(dict(item), image_path)
        if isinstance(item, dict) else item
        for item in result.get("targets") or []
    ]
    adjusted["image_path"] = image_path
    adjusted["immutable_screenshot"] = True
    return adjusted

def _find_click(description: str, image_path: Optional[str] = None, button: str = "left", click_anchor: str = "center", **kwargs: Any) -> Dict[str, Any]:
    hits = _locate(description=description, image_path=image_path, **kwargs)
    if not hits or hits[0].get("status") != "found":
        return _result("not_found", description=description, locate=hits)
    hit = hits[0]
    if hit.get("screen_coordinates_valid") is not True:
        return _result("blocked", error="locate result lacks trusted screen-coordinate metadata", description=description, locate=hits)
    try:
        x, y = _pick_anchor_point(hit, click_anchor)
    except ValueError:
        x, y = int(hit["center"]["x"]), int(hit["center"]["y"])
    clicked = _click(x, y, button=button)
    clicked["locate"] = hit
    clicked["click_point"] = {"x": x, "y": y, "anchor": click_anchor}
    return clicked


def _find_drag(
    from_description: str,
    to_description: str,
    image_path: Optional[str] = None,
    button: str = "left",
    from_anchor: str = "center",
    to_anchor: str = "center",
    path_segments: int = 6,
    duration_per_segment: float = 0.18,
    hold_after_down: float = 0.1,
    capture_region: Optional[List[int]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Locate drag source + drop target on one screenshot, then perform a held drag path."""
    capture_meta: Optional[Dict[str, Any]] = None
    if not image_path:
        capture_meta = _capture_for_grounding([from_description, to_description], region=capture_region)
        image_path = capture_meta["image_path"]
    locate_opts = _locate_drag_defaults({k: v for k, v in kwargs.items() if k in {
        "threshold", "device", "backend", "python", "output_type", "task", "strategy", "region",
        "max_side", "refine_max_side", "point_refine_radius", "max_new_tokens", "generation_mode",
        "prompt_style", "do_sample", "dtype",
    }})
    from_hits = _locate(from_description, image_path=image_path, **locate_opts)
    to_hits = _locate(to_description, image_path=image_path, **locate_opts)
    from_hit = from_hits[0] if from_hits else {"status": "error", "error": "no from locate response"}
    to_hit = to_hits[0] if to_hits else {"status": "error", "error": "no to locate response"}
    if from_hit.get("status") != "found" or to_hit.get("status") != "found":
        return _result(
            "not_found",
            from_description=from_description,
            to_description=to_description,
            image_path=image_path,
            from_locate=from_hit,
            to_locate=to_hit,
        )
    if from_hit.get("screen_coordinates_valid") is not True or to_hit.get("screen_coordinates_valid") is not True:
        return _result("blocked", error="drag locate results lack trusted screen-coordinate metadata", from_locate=from_hit, to_locate=to_hit)
    try:
        x1, y1 = _pick_anchor_point(from_hit, from_anchor)
        x2, y2 = _pick_anchor_point(to_hit, to_anchor)
    except ValueError as exc:
        return _result("error", error=str(exc), from_locate=from_hit, to_locate=to_hit)
    points = _interpolate_drag_points(x1, y1, x2, y2, path_segments)
    dragged = _drag_path(
        points,
        button=button,
        duration_per_segment=float(duration_per_segment),
        hold_after_down=float(hold_after_down),
    )
    dragged["from_locate"] = from_hit
    dragged["to_locate"] = to_hit
    dragged["from_point"] = {"x": x1, "y": y1, "anchor": from_anchor}
    dragged["to_point"] = {"x": x2, "y": y2, "anchor": to_anchor}
    dragged["image_path"] = image_path
    if capture_meta:
        dragged["capture"] = capture_meta
    return dragged


_GROUNDING_CACHE: Dict[str, Dict[str, Any]] = {}


def _visual_patch_signature(image: Any, x: int, y: int, radius: int) -> List[int]:
    Image = _pil_image()
    x1, y1 = max(0, int(x) - radius), max(0, int(y) - radius)
    x2, y2 = min(image.width, int(x) + radius), min(image.height, int(y) + radius)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("visual guard anchor is outside the captured image")
    patch = image.crop((x1, y1, x2, y2)).convert("L").resize((8, 8), Image.Resampling.BILINEAR)
    values = patch.get_flattened_data() if hasattr(patch, "get_flattened_data") else patch.getdata()
    return [int(value) // 16 for value in values]


def _visual_signature_distance(first: List[int], second: List[int]) -> float:
    if len(first) != len(second) or not first:
        return 1.0
    return round(sum(abs(int(a) - int(b)) for a, b in zip(first, second)) / (15.0 * len(first)), 4)


def _build_visual_guard(
    image_path: Optional[str],
    targets: Dict[str, Dict[str, Any]],
    radius: int = 16,
) -> Optional[Dict[str, Any]]:
    if not image_path or not os.path.exists(image_path) or not targets:
        return None
    Image = _pil_image()
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    meta = _load_capture_meta(image_path) or {}
    origin = meta.get("screen_origin") or {"x": 0, "y": 0}
    ox, oy = int(origin.get("x", 0)), int(origin.get("y", 0))
    anchors: List[Dict[str, Any]] = []
    for target_id, target in targets.items():
        center = target.get("center") if isinstance(target, dict) else None
        if not center:
            continue
        sx, sy = int(center["x"]), int(center["y"])
        lx, ly = sx - ox, sy - oy
        if not (0 <= lx < image.width and 0 <= ly < image.height):
            continue
        anchors.append({
            "id": str(target_id),
            "screen": {"x": sx, "y": sy},
            "radius": int(radius),
            "signature": _visual_patch_signature(image, lx, ly, int(radius)),
        })
    if not anchors:
        return None
    left = min(item["screen"]["x"] - item["radius"] for item in anchors)
    top = min(item["screen"]["y"] - item["radius"] for item in anchors)
    right = max(item["screen"]["x"] + item["radius"] for item in anchors)
    bottom = max(item["screen"]["y"] + item["radius"] for item in anchors)
    return {
        "version": 1,
        "anchors": anchors,
        "capture_region": [left, top, max(1, right - left), max(1, bottom - top)],
        "threshold": float(os.getenv("COMPUTER_USE_GROUNDING_GUARD_THRESHOLD", "0.12")),
    }


def _capture_guard_image(region: List[int]) -> Tuple[Any, Tuple[int, int]]:
    normalized = _normalize_region(region)
    virtual = _virtual_screen_bounds()
    image = _capture_pixels(_pyautogui(), normalized, False, virtual).convert("RGB")
    return image, (int(normalized[0]), int(normalized[1]))


def _verify_visual_guard(guard: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not guard or not guard.get("anchors"):
        return {"matched": False, "error": "visual guard is missing"}
    try:
        image, origin = _capture_guard_image(list(guard["capture_region"]))
        distances: List[Dict[str, Any]] = []
        for anchor in guard["anchors"]:
            center = anchor["screen"]
            current = _visual_patch_signature(
                image,
                int(center["x"]) - int(origin[0]),
                int(center["y"]) - int(origin[1]),
                int(anchor["radius"]),
            )
            distance = _visual_signature_distance(anchor["signature"], current)
            distances.append({"id": anchor["id"], "distance": distance})
        max_distance = max(item["distance"] for item in distances)
        threshold = float(guard.get("threshold", 0.12))
        return {
            "matched": max_distance <= threshold,
            "max_distance": max_distance,
            "threshold": threshold,
            "anchors": distances,
        }
    except Exception as exc:
        return {"matched": False, "error": str(exc), "max_distance": 1.0}


def _monitor_topology() -> List[Dict[str, Any]]:
    virtual = _virtual_screen_bounds()
    if os.name != "nt":
        return [{"left": virtual["left"], "top": virtual["top"], "right": virtual["right"], "bottom": virtual["bottom"], "dpi_x": None, "dpi_y": None}]
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        monitors: List[Dict[str, Any]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p)
        try:
            get_dpi = ctypes.windll.shcore.GetDpiForMonitor
        except Exception:
            get_dpi = None

        def _collect(handle, _hdc, rect_ptr, _data):
            rect = rect_ptr.contents
            dpi_x = ctypes.c_uint(0)
            dpi_y = ctypes.c_uint(0)
            if get_dpi is None or get_dpi(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:
                dx = dy = None
            else:
                dx, dy = int(dpi_x.value), int(dpi_y.value)
            monitors.append({
                "left": int(rect.left), "top": int(rect.top), "right": int(rect.right), "bottom": int(rect.bottom),
                "dpi_x": dx, "dpi_y": dy,
            })
            return 1

        callback = callback_type(_collect)
        if not ctypes.windll.user32.EnumDisplayMonitors(0, 0, callback, 0):
            raise OSError("EnumDisplayMonitors failed")
        return sorted(monitors, key=lambda item: (item["left"], item["top"], item["right"], item["bottom"]))
    except Exception:
        return [{"left": virtual["left"], "top": virtual["top"], "right": virtual["right"], "bottom": virtual["bottom"], "dpi_x": None, "dpi_y": None}]


def _grounding_window_fingerprint() -> Dict[str, Any]:
    """Cheap cache guard: layout reuse is valid only while host geometry is stable."""
    virtual = _virtual_screen_bounds()
    topology = _monitor_topology()
    window = _active_window()
    if window:
        return {
            "kind": "window",
            "virtual_screen": virtual,
            "monitors": topology,
            "handle": window.get("handle"),
            "process_id": window.get("process_id"),
            "dpi": window.get("dpi"),
            "left": int(window["left"]), "top": int(window["top"]),
            "width": int(window["width"]), "height": int(window["height"]),
            "client_bounds": window.get("client_bounds"),
        }
    return {"kind": "screen", "virtual_screen": virtual, "monitors": topology}


def _grounding_cache_entry(cache_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    key = str(cache_id or "").strip()
    if not key:
        return None, _result("error", error="cache_id is required")
    entry = _GROUNDING_CACHE.get(key)
    if not entry:
        return None, _result("not_found", error=f"no cached grounding named {key!r}; calibrate or remember it first", cache_id=key)
    current = _grounding_window_fingerprint()
    if entry.get("window_fingerprint") != current:
        return None, _result("stale", error="cached grounding is invalid because active window/screen geometry changed; recapture and recalibrate", cache_id=key, cached_window_fingerprint=entry.get("window_fingerprint"), current_window_fingerprint=current)
    if entry.get("visual_guard"):
        verification = _verify_visual_guard(entry.get("visual_guard"))
        if not verification.get("matched"):
            return None, _result(
                "stale",
                error="cached grounding is invalid because visual anchors changed; recapture and recalibrate",
                cache_id=key,
                visual_guard_verification=verification,
            )
    return entry, None


def _remember_groundings(cache_id: str, targets: List[Dict[str, str]], image_path: Optional[str] = None, mode: str = "exact", backend: Optional[str] = "cpp", device: Optional[str] = "cuda", **options: Any) -> Dict[str, Any]:
    """Ground stable targets once, then retain screen coordinates in this gateway session."""
    key = str(cache_id or "").strip()
    if not key:
        return _result("error", error="cache_id is required")
    result = _locate_batch(targets=targets, image_path=image_path, mode=mode, backend=backend, device=device, **options)
    found = [item for item in result.get("targets") or [] if isinstance(item, dict) and item.get("status") == "found" and item.get("center")]
    if len(found) != len(targets):
        return _result("not_found", error="all targets must resolve before creating a cache", cache_id=key, locate_batch=result)
    cached = {str(item["id"]): {"id": str(item["id"]), "description": str(item.get("description", "")), "center": {"x": int(item["center"]["x"]), "y": int(item["center"]["y"])}, "box": item.get("box")} for item in found}
    fingerprint = _grounding_window_fingerprint()
    visual_guard = _build_visual_guard(result.get("image_path"), cached)
    _GROUNDING_CACHE[key] = {"kind": "targets", "created_at": time.time(), "window_fingerprint": fingerprint, "visual_guard": visual_guard, "image_path": result.get("image_path"), "targets": cached}
    return _result("ok", cache_id=key, kind="targets", cached_targets=list(cached.values()), window_fingerprint=fingerprint, visual_guard=visual_guard, locate_batch=result)


def _reuse_groundings(cache_id: str, target_ids: Optional[List[str]] = None, **_: Any) -> Dict[str, Any]:
    entry, error = _grounding_cache_entry(cache_id)
    if error:
        return error
    if entry.get("kind") != "targets":
        return _result("error", error="cache_id refers to a grid; use computer_use_grid_cells", cache_id=cache_id)
    targets = entry["targets"]
    requested = [str(target_id) for target_id in target_ids] if target_ids else list(targets)
    missing = [target_id for target_id in requested if target_id not in targets]
    if missing:
        return _result("not_found", error=f"unknown cached target ids: {', '.join(missing)}", cache_id=cache_id)
    return _result("ok", cache_id=cache_id, kind="targets", reused=True, targets=[targets[target_id] for target_id in requested], window_fingerprint=entry["window_fingerprint"])


def _calibrate_grid(cache_id: str, description: str, columns: int, rows: int, image_path: Optional[str] = None, backend: Optional[str] = "cpp", device: Optional[str] = "cuda", **options: Any) -> Dict[str, Any]:
    """Ground a stable rectangular grid once and cache its cell-center geometry."""
    key = str(cache_id or "").strip()
    if not key:
        return _result("error", error="cache_id is required")
    if not isinstance(columns, int) or not 1 <= columns <= 100 or not isinstance(rows, int) or not 1 <= rows <= 100:
        return _result("error", error="columns and rows must be integers from 1 through 100")
    hits = _locate(description=description, image_path=image_path, backend=backend, device=device, output_type="box", **options)
    hit = hits[0] if hits else {"status": "error", "error": "no locate response"}
    box = hit.get("box") if isinstance(hit, dict) else None
    if hit.get("status") != "found" or not box:
        return _result("not_found", error="grid calibration requires a LocateAnything box result", cache_id=key, locate=hit)
    x1, y1, x2, y2 = (int(box["x1"]), int(box["y1"]), int(box["x2"]), int(box["y2"]))
    width, height = x2 - x1, y2 - y1
    if width < columns or height < rows:
        return _result("error", error="located grid is too small for the requested row/column count", cache_id=key, locate=hit)
    geometry = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": width, "height": height, "columns": columns, "rows": rows}
    fingerprint = _grounding_window_fingerprint()
    guard_target = {"grid": {"center": {"x": int(round((x1 + x2) / 2)), "y": int(round((y1 + y2) / 2))}}}
    guard_image_path = hit.get("image_path") or image_path
    visual_guard = _build_visual_guard(guard_image_path, guard_target)
    _GROUNDING_CACHE[key] = {"kind": "grid", "created_at": time.time(), "window_fingerprint": fingerprint, "visual_guard": visual_guard, "image_path": guard_image_path, "description": description, "geometry": geometry}
    return _result("ok", cache_id=key, kind="grid", geometry=geometry, window_fingerprint=fingerprint, visual_guard=visual_guard, locate=hit)


def _grid_cells(cache_id: str, cells: List[Dict[str, Any]], **_: Any) -> Dict[str, Any]:
    entry, error = _grounding_cache_entry(cache_id)
    if error:
        return error
    if entry.get("kind") != "grid":
        return _result("error", error="cache_id refers to remembered targets; use computer_use_reuse_groundings", cache_id=cache_id)
    if not isinstance(cells, list) or not cells:
        return _result("error", error="cells must be a non-empty list")
    geometry = entry["geometry"]
    resolved: List[Dict[str, Any]] = []
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            return _result("error", error=f"cell {index} must be an object", cache_id=cache_id)
        column, row = cell.get("column"), cell.get("row")
        if not isinstance(column, int) or not isinstance(row, int) or not (0 <= column < geometry["columns"]) or not (0 <= row < geometry["rows"]):
            return _result("error", error=f"cell {index} must use zero-based column 0..{geometry['columns'] - 1} and row 0..{geometry['rows'] - 1}", cache_id=cache_id)
        x = int(round(geometry["x1"] + (column + 0.5) * geometry["width"] / geometry["columns"]))
        y = int(round(geometry["y1"] + (row + 0.5) * geometry["height"] / geometry["rows"]))
        try:
            _ensure_on_screen(x, y)
        except ValueError as exc:
            return _result("stale", error=f"cached cell is no longer on-screen: {exc}; recapture and recalibrate", cache_id=cache_id)
        resolved.append({"id": str(cell.get("id", f"cell_{index}")), "column": column, "row": row, "center": {"x": x, "y": y}})
    return _result("ok", cache_id=cache_id, kind="grid", reused=True, cells=resolved, geometry=geometry, window_fingerprint=entry["window_fingerprint"])


def _forget_grounding(cache_id: str, **_: Any) -> Dict[str, Any]:
    key = str(cache_id or "").strip()
    removed = _GROUNDING_CACHE.pop(key, None) is not None
    return _result("ok", cache_id=key, removed=removed)


# ---- Schemas and plugin registration -----------------------------------------

def _schema(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required or []}}

_COMMON_CHECK = check_windows_computer_use_requirements
_TOOLSET = "windows_computer_use"
_PLUGIN_CTX = None

_SAFE_STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": sorted(_BATCH_ACTIONS)},
        "risk": {"type": "string", "enum": ["non_destructive"]},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "dx": {"type": "integer"}, "dy": {"type": "integer"},
        "duration": {"type": "number", "minimum": 0, "maximum": 10},
        "tween": {"type": "string", "enum": sorted(_BATCH_TWEENS)},
        "button": {"type": "string", "enum": ["left"]},
        "clicks": {"type": "integer"}, "interval": {"type": "number", "minimum": 0, "maximum": 2},
        "target_hint": {"type": "string"}, "target_id": {"type": "string"},
        "safe_purpose": {"type": "string", "enum": sorted(_BATCH_SAFE_PURPOSE_RE)},
        "text": {"type": "string", "maxLength": 10000}, "field_hint": {"type": "string"},
        "keys": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "presses": {"type": "integer", "minimum": 1, "maximum": 10},
        "title": {"type": "string", "maxLength": 512}, "exact": {"type": "boolean"},
        "duration_ms": {"type": "number", "minimum": 0, "maximum": 10000},
    },
    "required": ["action", "risk"],
}

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
        _register("computer_use_capture_screen", "Capture the desktop screenshot and return an image path.", {"display_index": {"type": "integer", "default": 0}, "question": {"type": "string"}, "region": {"description": "Optional [x, y, width, height] capture region", "type": "array", "items": {"type": "integer"}}, "all_screens": {"type": "boolean", "default": False}, "scope": {"type": "string", "enum": ["primary", "virtual_desktop", "active_window", "active_client", "region"], "default": "primary"}}, [], _capture_screen)
        _register("computer_use_observe_stage", "Capture one immutable active-window/client/desktop stage and optionally resolve up to 16 targets against that exact image. Read-only; performs no GUI action.", {"targets": {"type": "array", "maxItems": 16, "items": {"type": "object", "properties": {"id": {"type": "string"}, "description": {"type": "string"}}, "required": ["id", "description"]}}, "scope": {"type": "string", "enum": ["primary", "virtual_desktop", "active_window", "active_client", "region"], "default": "active_window"}, "region": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}, "mode": {"type": "string", "enum": ["exact", "auto", "one_pass"], "default": "exact"}, "backend": {"type": "string", "enum": ["cpp", "auto", "worker", "external", "internal"], "default": "cpp"}, "device": {"type": "string", "enum": ["cuda", "auto", "cpu"], "default": "cuda"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point"}, "strategy": {"type": "string", "enum": ["direct", "refine", "coarse_refine"], "default": "direct"}, "max_side": {"type": "integer", "default": 1024}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}}, [], _observe_stage)
        _register("computer_use_dynamic_workflow", "Execute up to 8 bounded non-destructive UI stages. The whole workflow is safety-preflighted first; every stage captures fresh pixels, independently grounds exact targets, then runs at most 12 safe actions. Consequential targets, credentials, submissions, payments, permissions, arbitrary code, imports, files, and network access are blocked.", {"stages": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "object", "properties": {"scope": {"type": "string", "enum": ["primary", "virtual_desktop", "active_window", "active_client", "region"], "default": "active_window"}, "region": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}, "static_screen": {"type": "boolean", "enum": [True], "description": "Required true when the stage contains actions; coordinates are valid only within this stage."}, "targets": {"type": "array", "maxItems": 16, "items": {"type": "object", "properties": {"id": {"type": "string"}, "description": {"type": "string"}}, "required": ["id", "description"]}}, "steps": {"type": "array", "maxItems": 12, "description": "Every state-changing action must end the stage (an optional trailing wait is allowed); recapture before the next action.", "items": _SAFE_STEP_SCHEMA}, "locate_mode": {"type": "string", "enum": ["exact", "auto", "one_pass"], "default": "exact"}, "backend": {"type": "string", "enum": ["cpp", "auto", "worker", "external", "internal"], "default": "cpp"}, "device": {"type": "string", "enum": ["cuda", "auto", "cpu"], "default": "cuda"}, "locate_options": {"type": "object"}}}}, "stop_on_failure": {"type": "boolean", "default": True}, "max_duration_ms": {"type": "integer", "minimum": 1000, "maximum": 120000, "default": 120000}}, ["stages"], _dynamic_workflow)
        _register("computer_use_warm", "Load LocateAnything-3B lazily. Defaults to THEIA's isolated external worker, auto-bootstraps worker deps outside the Hermes venv, and falls back to basic controls while installing.", {"device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}}, [], _warm)
        _register("computer_use_locate", "Locate a UI element on the desktop using LocateAnything-3B visual grounding. Preferred for UI grounding; supports isolated external CUDA worker, point/box output, and coarse-refine strategy.", {"description": {"type": "string"}, "image_path": {"type": "string"}, "threshold": {"type": "number", "default": 0.3}, "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point", "description": "Use point for click targets; box for region bounds"}, "task": {"type": "string", "enum": ["gui", "single", "multi", "text", "detect_text"], "default": "gui"}, "strategy": {"type": "string", "enum": ["auto", "direct", "point_refine", "refine", "coarse_refine"], "default": "direct"}, "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [x,y,width,height] crop in screenshot coordinates"}, "max_side": {"type": "integer", "default": 1024}, "refine_max_side": {"type": "integer", "default": 1024}, "point_refine_radius": {"type": "integer", "default": 360}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}, "prompt_style": {"type": "string", "enum": ["direct", "chat_template"], "default": "direct"}, "do_sample": {"type": "boolean", "default": False}, "dtype": {"type": "string", "enum": ["bfloat16", "float16", "float32", "bf16", "fp16", "fp32"], "default": "bfloat16"}}, ["description"], _locate)
        _register("computer_use_locate_batch", "Resolve up to 16 symbolic UI targets from one immutable screenshot. exact is the safe default. auto uses one-pass only after two explicit successful one-pass calibrations for the same normalized target set; ambiguous labels fall back to exact.", {"targets": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "properties": {"id": {"type": "string"}, "description": {"type": "string"}}, "required": ["id", "description"]}}, "image_path": {"type": "string", "description": "Exact immutable screenshot. Captures once when omitted."}, "mode": {"type": "string", "enum": ["auto", "exact", "one_pass"], "default": "exact"}, "threshold": {"type": "number", "default": 0.3}, "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"], "default": "cpp"}, "python": {"type": "string"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point"}, "strategy": {"type": "string", "enum": ["direct", "refine", "coarse_refine"], "default": "direct"}, "max_side": {"type": "integer", "default": 1024}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}}, ["targets"], _locate_batch)
        _register("computer_use_remember_groundings", "Ground up to 16 stable UI targets once and cache their coordinates for reuse while active window geometry remains unchanged.", {"cache_id": {"type": "string"}, "targets": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "properties": {"id": {"type": "string"}, "description": {"type": "string"}}, "required": ["id", "description"]}}, "image_path": {"type": "string"}, "mode": {"type": "string", "enum": ["exact", "auto", "one_pass"], "default": "exact"}, "backend": {"type": "string", "enum": ["cpp", "auto", "internal", "external", "worker"], "default": "cpp"}, "device": {"type": "string", "enum": ["cuda", "auto", "cpu"], "default": "cuda"}}, ["cache_id", "targets"], _remember_groundings)
        _register("computer_use_reuse_groundings", "Return cached stable target coordinates without LocateAnything inference. Refuses reuse when active window/screen geometry changed.", {"cache_id": {"type": "string"}, "target_ids": {"type": "array", "items": {"type": "string"}}}, ["cache_id"], _reuse_groundings)
        _register("computer_use_calibrate_grid", "Locate a stable rectangular grid once and cache its row/column cell geometry for fast coordinate reuse.", {"cache_id": {"type": "string"}, "description": {"type": "string"}, "columns": {"type": "integer", "minimum": 1, "maximum": 100}, "rows": {"type": "integer", "minimum": 1, "maximum": 100}, "image_path": {"type": "string"}, "backend": {"type": "string", "enum": ["cpp", "auto", "internal", "external", "worker"], "default": "cpp"}, "device": {"type": "string", "enum": ["cuda", "auto", "cpu"], "default": "cuda"}}, ["cache_id", "description", "columns", "rows"], _calibrate_grid)
        _register("computer_use_grid_cells", "Return zero-based row/column centers from a cached stable grid without re-grounding. Refuses reuse if host geometry changed.", {"cache_id": {"type": "string"}, "cells": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "object", "properties": {"id": {"type": "string"}, "column": {"type": "integer", "minimum": 0}, "row": {"type": "integer", "minimum": 0}}, "required": ["column", "row"]}}}, ["cache_id", "cells"], _grid_cells)
        _register("computer_use_forget_grounding", "Clear one remembered target or grid geometry cache entry.", {"cache_id": {"type": "string"}}, ["cache_id"], _forget_grounding)
        _register("computer_use_find_click", "Locate a described UI element and click its point/center. Preferred for UI grounding; supports isolated external CUDA worker and point output.", {"description": {"type": "string"}, "image_path": {"type": "string"}, "threshold": {"type": "number", "default": 0.3}, "device": {"type": "string", "enum": ["auto", "cuda", "cpu"], "default": "auto"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"], "default": "auto"}, "python": {"type": "string", "description": "Optional external Python interpreter for isolated LocateAnything worker"}, "output_type": {"type": "string", "enum": ["point", "box"], "default": "point", "description": "Use point for click targets; box for region bounds"}, "task": {"type": "string", "enum": ["gui", "single", "multi", "text", "detect_text"], "default": "gui"}, "strategy": {"type": "string", "enum": ["auto", "direct", "point_refine", "refine", "coarse_refine"], "default": "direct"}, "region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [x,y,width,height] crop in screenshot coordinates"}, "max_side": {"type": "integer", "default": 1024}, "refine_max_side": {"type": "integer", "default": 1024}, "point_refine_radius": {"type": "integer", "default": 360}, "max_new_tokens": {"type": "integer", "default": 32}, "generation_mode": {"type": "string", "enum": ["fast", "hybrid", "slow"], "default": "hybrid"}, "prompt_style": {"type": "string", "enum": ["direct", "chat_template"], "default": "direct"}, "do_sample": {"type": "boolean", "default": False}, "dtype": {"type": "string", "enum": ["bfloat16", "float16", "float32", "bf16", "fp16", "fp32"], "default": "bfloat16"}, "button": {"type": "string", "default": "left"}, "click_anchor": {"type": "string", "default": "center", "description": "center, top_center, bottom_center, left_center, right_center"}}, ["description"], _find_click)
        _register("computer_use_find_drag", "Locate a drag source and drop target on one screenshot, then drag with button held (Win32 drag backend on Windows). Defaults: slow generation, coarse_refine, box output.", {"from_description": {"type": "string"}, "to_description": {"type": "string"}, "image_path": {"type": "string"}, "capture_region": {"type": "array", "items": {"type": "integer"}, "description": "Optional [x,y,w,h] when capturing a fresh screenshot"}, "button": {"type": "string", "default": "left"}, "from_anchor": {"type": "string", "default": "center"}, "to_anchor": {"type": "string", "default": "center"}, "path_segments": {"type": "integer", "default": 6}, "duration_per_segment": {"type": "number", "default": 0.18}, "hold_after_down": {"type": "number", "default": 0.1}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"], "default": "worker"}, "max_side": {"type": "integer", "default": 1024}, "strategy": {"type": "string", "default": "coarse_refine"}, "generation_mode": {"type": "string", "default": "slow"}}, ["from_description", "to_description"], _find_drag)
        _register("computer_use_move", "Move the mouse cursor to an absolute coordinate without clicking.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, ["x", "y"], _move)
        _register("computer_use_move_relative", "Move the mouse cursor by a relative offset without clicking.", {"dx": {"type": "integer"}, "dy": {"type": "integer"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, ["dx", "dy"], _move_relative)
        _register("computer_use_click", "Click a desktop coordinate, or the current cursor position when x/y are omitted.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "clicks": {"type": "integer", "default": 1}, "interval": {"type": "number", "default": 0.0}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _click)
        _register("computer_use_double_click", "Double-click a desktop coordinate, or the current cursor position when x/y are omitted.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "interval": {"type": "number", "default": 0.0}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _double_click)
        _register("computer_use_batch", "Execute up to 12 explicitly non-destructive GUI steps in order after an all-or-nothing safety preflight. Blocks destructive/high-impact targets, credentials, submissions, payments, unsafe keys, app launches, and held/drag gestures. Use only for a known-safe sequence; inspect and verify the resulting UI afterward.", {"steps": {"type": "array", "minItems": 1, "maxItems": 12, "description": "Ordered safe steps. Every step must set risk='non_destructive'. Allowed actions: move, move_relative, click, double_click, type, press (navigation keys only), scroll, focus_window, wait. click/double_click require x, y, target_hint; type requires text and field_hint; wait uses duration_ms 0..10000.", "items": {"type": "object", "properties": {"action": {"type": "string", "enum": ["move", "move_relative", "click", "double_click", "type", "press", "scroll", "focus_window", "wait"]}, "risk": {"type": "string", "enum": ["non_destructive"]}, "x": {"type": "integer"}, "y": {"type": "integer"}, "dx": {"type": "integer"}, "dy": {"type": "integer"}, "duration": {"type": "number"}, "tween": {"type": "string"}, "button": {"type": "string", "enum": ["left"]}, "clicks": {"type": "integer"}, "interval": {"type": "number"}, "target_hint": {"type": "string", "description": "Visible, non-destructive purpose of a click target; high-impact labels are rejected"}, "safe_purpose": {"type": "string", "enum": ["navigate_view", "focus_input", "expand_collapse", "choose_option", "inspect", "select_item"], "description": "Required structured purpose for click/double_click; must match both target_hint and symbolic target description"}, "target_id": {"type": "string", "description": "Optional symbolic target resolved during preflight; requires targets and static_screen=true"}, "text": {"type": "string"}, "field_hint": {"type": "string", "description": "Visible non-sensitive field purpose; credential/payment/security fields are rejected"}, "keys": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "presses": {"type": "integer"}, "title": {"type": "string"}, "exact": {"type": "boolean"}, "duration_ms": {"type": "number", "minimum": 0, "maximum": 10000}}, "required": ["action", "risk"]}}, "stop_on_failure": {"type": "boolean", "default": True, "description": "Stop at the first failed step. Disable only for harmless independent actions."}, "targets": {"type": "array", "maxItems": 16, "description": "Optional symbolic targets resolved together before action one", "items": {"type": "object", "properties": {"id": {"type": "string"}, "description": {"type": "string"}}, "required": ["id", "description"]}}, "image_path": {"type": "string", "description": "Immutable screenshot used for symbolic target resolution; captures once when omitted"}, "locate_mode": {"type": "string", "enum": ["auto", "exact", "one_pass"], "default": "exact"}, "static_screen": {"type": "boolean", "default": False, "description": "Required true with targets; acknowledges coordinates remain valid for the entire batch"}, "backend": {"type": "string", "enum": ["auto", "internal", "external", "worker", "cpp"]}, "python": {"type": "string"}}, ["steps"], _computer_use_batch)
        _register("computer_use_execute_code", "Execute a restricted THEIA action program for a fixed, non-destructive screen stage. Supports only safe batch primitives plus literal bounded for _ in range(n) loops; arbitrary Python is rejected.", {"code": {"type": "string", "description": "Restricted action program: keyword-only calls to move, move_relative, click, double_click, type, press, scroll, focus_window, or wait; optional literal for _ in range(n) loops. Every expanded action must be non-destructive."}, "static_screen": {"type": "boolean", "enum": [True], "description": "Required true: assert every coordinate remains valid for the complete program."}, "stop_on_failure": {"type": "boolean", "default": True}}, ["code", "static_screen"], _computer_use_execute_code)
        _register("computer_use_mouse_down", "Press and hold a mouse button at an optional coordinate. Pair with computer_use_mouse_up or computer_use_release_all.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _mouse_down)
        _register("computer_use_mouse_up", "Release a mouse button at an optional coordinate.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "default": "left"}, "duration": {"type": "number", "default": 0.0}, "tween": {"type": "string", "default": "linear"}}, [], _mouse_up)
        _register("computer_use_type", "Type text into the focused application.", {"text": {"type": "string"}, "interval": {"type": "number", "default": 0.0}}, ["text"], _type)
        _register("computer_use_press", "Press one or more keyboard keys, with optional repeat count and interval.", {"keys": {"description": "A key string or list of key strings", "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, "presses": {"type": "integer", "default": 1}, "interval": {"type": "number", "default": 0.0}}, ["keys"], _press)
        _register("computer_use_key_down", "Hold down a keyboard key until computer_use_key_up or computer_use_release_all is called.", {"key": {"type": "string"}}, ["key"], _key_down)
        _register("computer_use_key_up", "Release a keyboard key previously held down.", {"key": {"type": "string"}}, ["key"], _key_up)
        _register("computer_use_hotkey", "Press a hotkey sequence, e.g. ['ctrl','s'] or ['cmd','s']; keys go down in order and up in reverse order.", {"keys": {"type": "array", "items": {"type": "string"}}, "interval": {"type": "number", "default": 0.0}}, ["keys"], _hotkey)
        _register("computer_use_scroll", "Scroll at the current mouse position or optional coordinate. Uses native Win32 wheel events by default on Windows and PyAutoGUI elsewhere.", {"clicks": {"type": "integer"}, "x": {"type": "integer"}, "y": {"type": "integer"}}, ["clicks"], _scroll)
        _register("computer_use_drag", "Drag from one desktop coordinate to another while holding a mouse button down.", {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}, "duration": {"type": "number", "default": 0.3}, "button": {"type": "string", "default": "left"}, "tween": {"type": "string", "default": "linear"}}, ["x1", "y1", "x2", "y2"], _drag)
        _register("computer_use_drag_relative", "Drag from the current cursor position by a relative offset while holding a mouse button down.", {"dx": {"type": "integer"}, "dy": {"type": "integer"}, "duration": {"type": "number", "default": 0.3}, "button": {"type": "string", "default": "left"}, "tween": {"type": "string", "default": "linear"}}, ["dx", "dy"], _drag_relative)
        _register("computer_use_drag_path", "Drag through multiple absolute points while holding a mouse button down; useful for sliders, selection boxes, drawing, and finicky UI gestures.", {"points": {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}, "minItems": 2}, "button": {"type": "string", "default": "left"}, "duration_per_segment": {"type": "number", "default": 0.1}, "hold_after_down": {"type": "number", "default": 0.08}, "tween": {"type": "string", "default": "linear"}}, ["points"], _drag_path)
        _register("computer_use_release_all", "Safety release for common held mouse buttons and modifier keys after manual hold gestures.", {}, [], _release_all)
        _register("computer_use_pixel", "Read the RGB color of a screen pixel at x,y for lightweight visual verification.", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"], _pixel)
        _register("computer_use_pixel_matches", "Check whether a screen pixel matches an expected RGB color within tolerance.", {"x": {"type": "integer"}, "y": {"type": "integer"}, "rgb": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3}, "tolerance": {"type": "integer", "default": 0}}, ["x", "y", "rgb"], _pixel_matches)
        _register("computer_use_open_app", "Open an application or command.", {"command": {"type": "string"}}, ["command"], _open_app)
        _register("computer_use_focus_window", "Focus a window by title.", {"title": {"type": "string"}, "exact": {"type": "boolean", "default": False}}, ["title"], _focus_window)
        _register("computer_use_get_active_window", "Return active window and screen information.", {}, [], _get_active_window)
        _register("computer_use_set_dry_run", "Enable or disable dry-run mode for desktop computer-use actions.", {"dry_run": {"type": "boolean"}}, ["dry_run"], _set_dry_run)
    finally:
        _PLUGIN_CTX = old_ctx

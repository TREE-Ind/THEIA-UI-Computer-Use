"""External LocateAnything worker for windows_computer_use.

Runs in a separate Python interpreter so CUDA Torch can live outside the Hermes
runtime venv. Protocol: JSON stdin/stdout, or newline-delimited JSON with
``--server``. No installs, no Hermes imports, no mutation of caller env.
"""
from __future__ import annotations

import ctypes
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

_MODEL = None
_PROCESSOR = None
_TOK = None
_TORCH = None
_DEVICE = None
_MODEL_ID = None
_DTYPE_NAME = None
_CPP_DLL_RUNTIME = None
_CPP_DLL_SIGNATURE = None
_CPP_DLL_LAST_ERROR = None

_CPP_STAGE_CACHE: "OrderedDict[Tuple[Any, ...], Dict[str, Any]]" = OrderedDict()
_CPP_RESULT_CACHE: "OrderedDict[Tuple[Any, ...], Dict[str, Any]]" = OrderedDict()
_ONE_PASS_STATS: Dict[Tuple[str, ...], Dict[str, int]] = {}


def _cache_limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _image_identity(image_path: str) -> Tuple[str, int, int, str]:
    """Return an exact immutable image identity suitable for cache keys."""
    normalized = os.path.abspath(image_path)
    stat = os.stat(normalized)
    digest = hashlib.sha256()
    with open(normalized, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return normalized, int(stat.st_size), int(stat.st_mtime_ns), digest.hexdigest()


def _normalized_region_key(region: Optional[Any]) -> Optional[Tuple[int, int, int, int]]:
    if not region:
        return None
    if isinstance(region, dict):
        values = (region.get("x"), region.get("y"), region.get("width"), region.get("height"))
    else:
        values = tuple(region[:4])
    return tuple(int(value) for value in values)


def _get_cpp_stage(
    image_path: str,
    region: Optional[Any],
    max_side: int,
    identity: Optional[Tuple[Any, ...]] = None,
    frame_image: Any = None,
) -> Dict[str, Any]:
    """Open/crop/resize an immutable screenshot once per exact stage."""
    from PIL import Image

    source_identity = tuple(identity or _image_identity(image_path))
    region_key = _normalized_region_key(region)
    key = (source_identity, region_key, int(max_side), "rgb-lanczos-v1")
    cached = _CPP_STAGE_CACHE.get(key)
    if cached is not None:
        _CPP_STAGE_CACHE.move_to_end(key)
        cached["cache_hit"] = True
        return cached

    started = time.perf_counter()
    if frame_image is not None:
        full_image = frame_image.copy()
    else:
        with Image.open(image_path) as opened:
            full_image = opened.convert("RGB")
    source_size = full_image.size
    work_image, offset = _crop_image(full_image, region)
    work_size = work_image.size
    infer_image = _resize_for_inference(work_image, int(max_side))
    cached = {
        "key": key,
        "identity": source_identity,
        "image": infer_image,
        "work_image": work_image,
        "offset": offset,
        "work_size": work_size,
        "source_size": source_size,
        "infer_size": infer_image.size,
        "region": region_key,
        "max_side": int(max_side),
        "cache_hit": False,
        "preprocess_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    _CPP_STAGE_CACHE[key] = cached
    _CPP_STAGE_CACHE.move_to_end(key)
    while len(_CPP_STAGE_CACHE) > _cache_limit("COMPUTER_USE_LOCATE_STAGE_CACHE", 6):
        _old_key, old = _CPP_STAGE_CACHE.popitem(last=False)
        try:
            old["image"].close()
        except Exception:
            pass
        try:
            if old.get("work_image") is not old.get("image"):
                old["work_image"].close()
        except Exception:
            pass
    return cached


def _cpp_result_key(payload: Dict[str, Any]) -> Tuple[Any, ...]:
    image_path = str(payload.get("image_path", ""))
    identity = tuple(payload.get("image_identity") or _image_identity(image_path))
    relevant = {
        key: payload.get(key)
        for key in (
            "description", "task", "output_type", "strategy", "region", "max_side",
            "refine_max_side", "refine_pad", "max_new_tokens", "generation_mode",
            "threshold", "prompt_style", "do_sample", "dtype",
        )
    }
    cli_path, model_path = _cpp_runtime_paths()
    runtime_identity = []
    for path in [cli_path, model_path, *list(_cpp_dll_candidates())]:
        if not path:
            continue
        try:
            stat = os.stat(path)
            runtime_identity.append((os.path.abspath(path), int(stat.st_size), int(stat.st_mtime_ns)))
        except OSError:
            continue
    return (
        identity,
        json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str),
        tuple(runtime_identity),
        "cpp-result-v1",
    )


def _json(data: Any) -> None:
    print(json.dumps(data, default=str), flush=True)


def _numbers(text: str) -> List[int]:
    return [int(n) for n in re.findall(r"-?\d+", text)]


def _scale_box(coords: Tuple[int, int, int, int], image_size: Tuple[int, int]) -> Dict[str, int]:
    x1, y1, x2, y2 = coords
    width, height = image_size
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1000:
        x1 = round(x1 / 1000 * width)
        x2 = round(x2 / 1000 * width)
        y1 = round(y1 / 1000 * height)
        y2 = round(y2 / 1000 * height)
    x1, x2 = sorted((max(0, min(width, int(x1))), max(0, min(width, int(x2)))))
    y1, y2 = sorted((max(0, min(height, int(y1))), max(0, min(height, int(y2)))))
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _scale_point(coords: Tuple[int, int], image_size: Tuple[int, int]) -> Dict[str, int]:
    x, y = coords
    width, height = image_size
    if max(abs(x), abs(y)) <= 1000:
        x = round(x / 1000 * width)
        y = round(y / 1000 * height)
    return {"x": max(0, min(max(0, width - 1), int(x))), "y": max(0, min(max(0, height - 1), int(y)))}


def _parse_boxes(text: str, image_size: Tuple[int, int]) -> List[Dict[str, int]]:
    boxes: List[Dict[str, int]] = []
    tag_bodies = re.findall(r"<box>(.*?)</box>", text, re.DOTALL)
    for body in tag_bodies:
        nums = _numbers(body)
        if len(nums) >= 4:
            boxes.append(_scale_box((nums[0], nums[1], nums[2], nums[3]), image_size))
    if not boxes and not tag_bodies:
        nums = _numbers(text)
        if len(nums) >= 4:
            boxes.append(_scale_box((nums[0], nums[1], nums[2], nums[3]), image_size))
    return boxes


def _parse_points(text: str, image_size: Tuple[int, int]) -> List[Dict[str, int]]:
    points: List[Dict[str, int]] = []
    for body in re.findall(r"<box>(.*?)</box>", text, re.DOTALL):
        nums = _numbers(body)
        if len(nums) == 2:
            points.append(_scale_point((nums[0], nums[1]), image_size))
    return points


def _box_center(box: Dict[str, int]) -> Dict[str, int]:
    return {"x": (box["x1"] + box["x2"]) // 2, "y": (box["y1"] + box["y2"]) // 2}


def _preproc_target(w0: int, h0: int) -> Tuple[int, int]:
    k_patch = 14
    k_in_token_limit = 25600
    w, h = w0, h0
    if (w // k_patch) * (h // k_patch) > k_in_token_limit:
        scale = math.sqrt(k_in_token_limit / ((w // k_patch) * (h // k_patch)))
        w = int(w0 * scale)
        h = int(h0 * scale)
    pad = 28
    target_w = int(math.ceil(w / pad)) * pad
    target_h = int(math.ceil(h / pad)) * pad
    return target_w, target_h


def _cpp_boxes_target_to_image(boxes: List[Dict[str, float]], img_w: int, img_h: int) -> List[Dict[str, int]]:
    tw, th = _preproc_target(img_w, img_h)
    if tw <= 0 or th <= 0:
        return []
    sx, sy = img_w / tw, img_h / th
    return [
        {
            "x1": int(round(b["x1"] * sx)),
            "y1": int(round(b["y1"] * sy)),
            "x2": int(round(b["x2"] * sx)),
            "y2": int(round(b["y2"] * sy)),
        }
        for b in boxes
    ]


def _scale_boxes_between_sizes(
    boxes: List[Dict[str, int]], from_w: int, from_h: int, to_w: int, to_h: int
) -> List[Dict[str, int]]:
    if from_w <= 0 or from_h <= 0:
        return boxes
    sx, sy = to_w / from_w, to_h / from_h
    return [
        {
            "x1": int(round(b["x1"] * sx)),
            "y1": int(round(b["y1"] * sy)),
            "x2": int(round(b["x2"] * sx)),
            "y2": int(round(b["y2"] * sy)),
        }
        for b in boxes
    ]


def _offset_boxes(boxes: List[Dict[str, int]], ox: int, oy: int) -> List[Dict[str, int]]:
    return [
        {"x1": b["x1"] + ox, "y1": b["y1"] + oy, "x2": b["x2"] + ox, "y2": b["y2"] + oy}
        for b in boxes
    ]


class _CapiTimings(ctypes.Structure):
    _fields_ = [
        ("image_load_ms", ctypes.c_double),
        ("preprocess_ms", ctypes.c_double),
        ("vision_ms", ctypes.c_double),
        ("projector_ms", ctypes.c_double),
        ("prompt_ms", ctypes.c_double),
        ("decode_ms", ctypes.c_double),
        ("parse_ms", ctypes.c_double),
        ("total_ms", ctypes.c_double),
    ]


class _LocateAnythingDLL:
    """Persistent ctypes adapter for locate-anything's prepared-image C API."""

    def __init__(self, dll_path: str, model_path: str, threads: int = 0) -> None:
        self.dll_path = os.path.abspath(dll_path)
        self.model_path = os.path.abspath(model_path)
        self._dll_directory_handles: List[Any] = []
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            cuda_bins = [
                os.getenv("COMPUTER_USE_LOCATE_CUDA_BIN"),
                os.path.join(os.getenv("CUDA_PATH", ""), "bin") if os.getenv("CUDA_PATH") else None,
                os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"),
                             "NVIDIA GPU Computing Toolkit", "CUDA", "v11.7", "bin"),
            ]
            for cuda_bin in cuda_bins:
                if cuda_bin and os.path.isdir(cuda_bin):
                    try:
                        self._dll_directory_handles.append(os.add_dll_directory(cuda_bin))
                    except OSError:
                        pass
        self.lib = ctypes.CDLL(self.dll_path)
        # Windows pins this file while loaded; retain its byte identity on the
        # runtime, not a later parent-side source-only deployment observation.
        digest = hashlib.sha256()
        with open(self.dll_path, 'rb') as source:
            for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                digest.update(block)
        self.dll_sha256 = digest.hexdigest()
        self._abi_version = self._symbol("la_capi_abi_version")
        self._abi_version.argtypes = []
        self._abi_version.restype = ctypes.c_int
        abi_version = int(self._abi_version())
        if abi_version not in {2, 3}:
            raise RuntimeError(f"unsupported locate-anything C API ABI {abi_version}; expected 2 or 3")
        self.abi_version = abi_version
        self._load = self._symbol("la_capi_load", "load")
        self._free = self._symbol("la_capi_free", "free")
        self._prepare = self._symbol("la_capi_prepare_path", "prepare_path")
        self._prepare_rgb = self._symbol("la_capi_prepare_rgb", "prepare_rgb", required=False)
        if abi_version >= 3 and self._prepare_rgb is None:
            raise RuntimeError("locate-anything ABI 3 is missing la_capi_prepare_rgb")
        self._locate = self._symbol(
            "la_capi_locate_prepared_ex",
            "la_capi_locate_prepared",
            "locate_prepared_ex",
        )
        self._clear = self._symbol("la_capi_clear_prepared", "la_capi_clear", "clear")
        self._free_string = self._symbol("la_capi_free_string", "free_string")
        self._last_error = self._symbol("la_capi_last_error", "last_error", required=False)
        self._get_timings = self._symbol("la_capi_get_last_timings", required=False)
        self._configure_signatures()
        self.ctx = self._load(self.model_path.encode("utf-8"), int(threads))
        if not self.ctx:
            raise RuntimeError("locate-anything DLL failed to load model")
        self.prepared_path: Optional[str] = None
        self.prepared_signature: Optional[Tuple[Any, ...]] = None
        self.prepared_source: Optional[str] = None
        self.prepare_timing: Dict[str, float] = {}

    def _symbol(self, *names: str, required: bool = True):
        for name in names:
            fn = getattr(self.lib, name, None)
            if fn is not None:
                return fn
        if required:
            raise AttributeError(f"locate-anything DLL is missing required export: {' or '.join(names)}")
        return None

    @staticmethod
    def _set_signature(fn, argtypes, restype) -> None:
        try:
            fn.argtypes = argtypes
            fn.restype = restype
        except Exception:
            pass

    def _configure_signatures(self) -> None:
        self._set_signature(self._load, [ctypes.c_char_p, ctypes.c_int], ctypes.c_void_p)
        self._set_signature(self._free, [ctypes.c_void_p], None)
        self._set_signature(self._prepare, [ctypes.c_void_p, ctypes.c_char_p], ctypes.c_int)
        if self._prepare_rgb is not None:
            self._set_signature(
                self._prepare_rgb,
                [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int],
                ctypes.c_int,
            )
        self._set_signature(
            self._locate,
            [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int],
            ctypes.c_void_p,
        )
        self._set_signature(self._clear, [ctypes.c_void_p], None)
        self._set_signature(self._free_string, [ctypes.c_void_p], None)
        if self._last_error is not None:
            self._set_signature(self._last_error, [ctypes.c_void_p], ctypes.c_char_p)
        if self._get_timings is not None:
            self._set_signature(
                self._get_timings,
                [ctypes.c_void_p, ctypes.POINTER(_CapiTimings)],
                ctypes.c_int,
            )

    def _timings(self) -> Dict[str, float]:
        if self._get_timings is None:
            return {}
        value = _CapiTimings()
        if int(self._get_timings(self.ctx, ctypes.byref(value))) != 0:
            return {}
        return {
            field: round(float(getattr(value, field)), 3)
            for field, _ctype in value._fields_
        }

    @staticmethod
    def _file_signature(path: str) -> tuple[int, str]:
        """Content identity for exact-image prepared-feature reuse.

        Batch requests may create distinct temporary PNG paths for the same
        immutable screenshot. Hashing the encoded image is cheap relative to a
        ViT pass and prevents both stale-path reuse and duplicate vision work.
        """
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()

    def _error(self, fallback: str) -> str:
        if self._last_error is None:
            return fallback
        try:
            value = self._last_error(self.ctx)
            if value:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        except Exception:
            pass
        return fallback

    def prepare_path(self, image_path: str) -> None:
        normalized = os.path.abspath(image_path)
        try:
            signature = self._file_signature(normalized)
        except OSError:
            # Keep the adapter unit-testable with synthetic paths; the native
            # call will still report a useful error for a genuinely bad image.
            signature = (-1, normalized)
        if self.prepared_signature == signature:
            # No image work occurred on this request; do not re-charge the first
            # request's preparation time to every cached prompt decode.
            self.prepare_timing = {}
            return
        if self.prepared_path is not None:
            self.clear()
        rc = int(self._prepare(self.ctx, normalized.encode("utf-8")))
        if rc != 0:
            raise RuntimeError(self._error(f"prepare_path failed with code {rc}"))
        self.prepared_path = normalized
        self.prepared_signature = signature
        self.prepared_source = "path"
        self.prepare_timing = self._timings()

    def prepare_rgb(
        self,
        rgb: bytes,
        *,
        width: int,
        height: int,
        stride: Optional[int] = None,
        signature: Optional[Tuple[Any, ...]] = None,
    ) -> None:
        if self._prepare_rgb is None:
            raise RuntimeError("loaded locate-anything DLL does not support raw RGB preparation")
        width, height = int(width), int(height)
        stride = int(stride if stride is not None else width * 3)
        if width <= 0 or height <= 0 or stride < width * 3:
            raise ValueError("raw RGB width/height must be positive and stride must be at least width*3")
        expected = height * stride
        if len(rgb) < expected:
            raise ValueError(f"raw RGB buffer is too short: got {len(rgb)}, need {expected}")
        identity = tuple(signature or ("rgb", width, height, stride, hashlib.sha256(rgb[:expected]).hexdigest()))
        if self.prepared_signature == identity:
            self.prepare_timing = {}
            return
        if self.prepared_source is not None:
            self.clear()
        buffer = ctypes.create_string_buffer(rgb[:expected], expected)
        rc = int(self._prepare_rgb(self.ctx, ctypes.cast(buffer, ctypes.c_void_p), width, height, stride))
        if rc != 0:
            raise RuntimeError(self._error(f"prepare_rgb failed with code {rc}"))
        self.prepared_path = None
        self.prepared_signature = identity
        self.prepared_source = "rgb"
        self.prepare_timing = self._timings()

    def locate_prepared(self, prompt: str, mode: str, max_new_tokens: int = 32) -> Dict[str, Any]:
        if self.prepared_source is None:
            raise RuntimeError("prepare_path or prepare_rgb must be called before locate_prepared")
        mode_value = {"hybrid": 0, "slow": 1, "fast": 2}.get(str(mode).lower(), 0)
        max_new = int(max_new_tokens)
        if max_new <= 0:
            raise ValueError("max_new_tokens must be positive")
        ptr = self._locate(self.ctx, str(prompt).encode("utf-8"), mode_value, max_new)
        if not ptr:
            raise RuntimeError(self._error("locate_prepared_ex failed"))
        try:
            raw = ctypes.string_at(ptr).decode("utf-8")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("locate_prepared_ex returned non-object JSON")
            native_timing = self._timings()
            if native_timing:
                combined = dict(self.prepare_timing)
                combined.update({
                    "prompt_ms": native_timing.get("prompt_ms", 0.0),
                    "decode_ms": native_timing.get("decode_ms", 0.0),
                    "parse_ms": native_timing.get("parse_ms", 0.0),
                    "locate_ms": native_timing.get("total_ms", 0.0),
                })
                combined["total_ms"] = round(
                    float(self.prepare_timing.get("total_ms", 0.0))
                    + float(native_timing.get("total_ms", 0.0)), 3,
                )
                value.setdefault("timing", combined)
            return value
        finally:
            self._free_string(ptr)

    def clear(self) -> None:
        if getattr(self, "ctx", None):
            self._clear(self.ctx)
        self.prepared_path = None
        self.prepared_signature = None
        self.prepared_source = None
        self.prepare_timing = {}

    def close(self) -> None:
        ctx = getattr(self, "ctx", None)
        if ctx:
            try:
                self.clear()
            finally:
                self._free(ctx)
                self.ctx = None
        for handle in self._dll_directory_handles:
            try:
                handle.close()
            except Exception:
                pass
        self._dll_directory_handles = []


def _cpp_dll_candidates() -> List[str]:
    explicit = os.getenv("COMPUTER_USE_LOCATE_CPP_DLL")
    cli = os.getenv("COMPUTER_USE_LOCATE_CPP_CLI", "")
    if not cli:
        if os.name == "nt" and os.getenv("LOCALAPPDATA"):
            cli = os.path.join(
                os.environ["LOCALAPPDATA"], "hermes", "theia-ui-computer-use",
                "cpp", "locate-anything-cli.exe",
            )
        else:
            cli = os.path.expanduser("~/.hermes/theia-ui-computer-use/cpp/locate-anything-cli")
    candidates = [explicit] if explicit else []
    if cli:
        base = os.path.dirname(cli)
        candidates.extend([
            os.path.join(base, "locate-anything.dll"),
            os.path.join(base, "locate-anything-capi.dll"),
            os.path.join(base, "locate_anything.dll"),
            os.path.join(base, "liblocate-anything.so"),
            os.path.join(base, "liblocate-anything.dylib"),
        ])
    return [str(path) for path in candidates if path]


def _cpp_runtime_paths() -> Tuple[str, str]:
    """Resolve one consistent Q5 native CLI/model configuration."""
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        base = os.path.join(os.environ["LOCALAPPDATA"], "hermes", "theia-ui-computer-use", "cpp")
    else:
        base = os.path.expanduser("~/.hermes/theia-ui-computer-use/cpp")
    cli_path = os.getenv("COMPUTER_USE_LOCATE_CPP_CLI") or os.path.join(base, "locate-anything-cli.exe")
    configured_model = os.getenv("COMPUTER_USE_LOCATE_MODEL")
    model_candidates = [
        configured_model,
        os.path.join(base, "locate-anything-q5_0.gguf"),
        os.path.join(base, "locate-anything-q8_0.gguf"),
    ]
    model_path = next((path for path in model_candidates if path and os.path.exists(path)), None)
    return cli_path, str(model_path or model_candidates[1])


def _get_cpp_dll_runtime(model_path: str) -> Optional[_LocateAnythingDLL]:
    global _CPP_DLL_RUNTIME, _CPP_DLL_SIGNATURE, _CPP_DLL_LAST_ERROR
    dll_path = next((path for path in _cpp_dll_candidates() if os.path.isfile(path)), None)
    if not dll_path:
        return None
    threads = int(os.getenv("COMPUTER_USE_LOCATE_CPP_THREADS", "0"))
    signature = (
        os.path.abspath(dll_path),
        os.path.getmtime(dll_path),
        os.path.abspath(model_path),
        os.path.getmtime(model_path) if os.path.exists(model_path) else None,
        threads,
    )
    if _CPP_DLL_RUNTIME is not None and _CPP_DLL_SIGNATURE == signature:
        return _CPP_DLL_RUNTIME
    if _CPP_DLL_RUNTIME is not None:
        try:
            _CPP_DLL_RUNTIME.close()
        except Exception:
            pass
    try:
        _CPP_DLL_RUNTIME = _LocateAnythingDLL(dll_path, model_path, threads=threads)
        _CPP_DLL_SIGNATURE = signature
        _CPP_DLL_LAST_ERROR = None
        return _CPP_DLL_RUNTIME
    except Exception as exc:
        _CPP_DLL_RUNTIME = None
        _CPP_DLL_SIGNATURE = None
        _CPP_DLL_LAST_ERROR = str(exc)
        return None


def _shutdown_cpp_dll_runtime() -> None:
    global _CPP_DLL_RUNTIME, _CPP_DLL_SIGNATURE, _CPP_DLL_LAST_ERROR
    runtime = _CPP_DLL_RUNTIME
    _CPP_DLL_RUNTIME = None
    _CPP_DLL_SIGNATURE = None
    _CPP_DLL_LAST_ERROR = None
    if runtime is not None:
        runtime.close()


def _normalize_cpp_detection_json(data: Dict[str, Any], width: int, height: int, runtime: str, elapsed_ms: float) -> Dict[str, Any]:
    raw_detections: List[Dict[str, Any]] = []
    raw_boxes: List[Dict[str, float]] = []
    for detection in data.get("detections", []):
        box = detection.get("box") or detection.get("bbox") or []
        if len(box) < 4:
            continue
        raw_box = {"x1": float(box[0]), "y1": float(box[1]), "x2": float(box[2]), "y2": float(box[3])}
        raw_boxes.append(raw_box)
        raw_detections.append({"label": str(detection.get("label", "")), "raw_box": raw_box})
    boxes = _cpp_boxes_target_to_image(raw_boxes, width, height)
    detections = [
        {"label": item["label"], "box": box, "center": _box_center(box)}
        for item, box in zip(raw_detections, boxes)
    ]
    timing = dict(data.get("timing") or {})
    timing.setdefault("duration_ms", round(float(elapsed_ms), 3))
    return {
        "status": "found" if boxes else "not_found",
        "backend": "cpp",
        "runtime": runtime,
        "boxes": boxes,
        "detections": detections,
        "raw": data,
        "infer_size": [width, height],
        "timing": timing,
        "duration_ms": timing.get("duration_ms"),
    }


def _cpp_detect_cli(
    image_path: str,
    prompt: str,
    mode: str,
    model_path: str,
    cli_path: str,
    max_new_tokens: int = 32,
) -> Dict[str, Any]:
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    started = time.perf_counter()
    try:
        cmd = [
            cli_path, "detect", "--model", model_path, "--input", image_path,
            "--prompt", prompt, "--mode", mode, "--max-new", str(int(max_new_tokens)),
            "--output", out_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-800:]
            return {"status": "error", "backend": "cpp", "runtime": "cli", "error": err, "cmd": " ".join(cmd)}
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        image = Image.open(image_path).convert("RGB")
        return _normalize_cpp_detection_json(data, image.width, image.height, "cli", (time.perf_counter() - started) * 1000.0)
    except Exception as exc:
        return {"status": "error", "backend": "cpp", "runtime": "cli", "error": str(exc)}
    finally:
        try:
            os.unlink(out_path)
        except Exception:
            pass


def _cpp_detect(
    image_path: str,
    prompt: str,
    mode: str,
    model_path: str,
    cli_path: str,
    max_new_tokens: int = 32,
) -> Dict[str, Any]:
    from PIL import Image

    runtime = _get_cpp_dll_runtime(model_path)
    dll_error: Optional[str] = None
    if runtime is not None:
        started = time.perf_counter()
        try:
            runtime.prepare_path(image_path)
            data = runtime.locate_prepared(prompt, mode, max_new_tokens=max_new_tokens)
            image = Image.open(image_path).convert("RGB")
            normalized = _normalize_cpp_detection_json(
                data, image.width, image.height, "dll",
                (time.perf_counter() - started) * 1000.0,
            )
            # A short bound is sufficient for normal GUI points, but never let
            # bounded decoding reduce accuracy: retry text decoding only (the
            # image remains prepared) when output is empty/incomplete.
            if not normalized.get("boxes") and int(max_new_tokens) < 256:
                retry_started = time.perf_counter()
                retry_data = runtime.locate_prepared(prompt, mode, max_new_tokens=256)
                normalized = _normalize_cpp_detection_json(
                    retry_data, image.width, image.height, "dll",
                    (time.perf_counter() - started) * 1000.0,
                )
                normalized["bounded_decode_retry"] = {
                    "initial_max_new_tokens": int(max_new_tokens),
                    "retry_max_new_tokens": 256,
                    "retry_ms": round((time.perf_counter() - retry_started) * 1000.0, 3),
                }
            return normalized
        except Exception as exc:
            dll_error = str(exc)
    fallback = _cpp_detect_cli(
        image_path, prompt, mode, model_path, cli_path,
        max_new_tokens=max_new_tokens,
    )
    if dll_error:
        fallback["dll_fallback_error"] = dll_error
    return fallback


def _cpp_detect_image(
    image: Any,
    prompt: str,
    mode: str,
    model_path: str,
    cli_path: str,
    max_new_tokens: int = 32,
    signature: Optional[Tuple[Any, ...]] = None,
    allow_file_fallback: bool = True,
) -> Dict[str, Any]:
    """Detect from RGB; internal memory frames fail closed without raw ABI."""
    runtime = _get_cpp_dll_runtime(model_path)
    raw_error: Optional[str] = None
    if runtime is not None and callable(getattr(runtime, "prepare_rgb", None)):
        started = time.perf_counter()
        try:
            rgb = image.tobytes("raw", "RGB")
            runtime.prepare_rgb(
                rgb,
                width=int(image.width),
                height=int(image.height),
                stride=int(image.width) * 3,
                signature=tuple(signature or ("pil-rgb", hashlib.sha256(rgb).hexdigest())),
            )
            data = runtime.locate_prepared(prompt, mode, max_new_tokens=max_new_tokens)
            normalized = _normalize_cpp_detection_json(
                data, int(image.width), int(image.height), "dll",
                (time.perf_counter() - started) * 1000.0,
            )
            if not normalized.get("boxes") and int(max_new_tokens) < 256:
                retry_started = time.perf_counter()
                retry_data = runtime.locate_prepared(prompt, mode, max_new_tokens=256)
                normalized = _normalize_cpp_detection_json(
                    retry_data, int(image.width), int(image.height), "dll",
                    (time.perf_counter() - started) * 1000.0,
                )
                normalized["bounded_decode_retry"] = {
                    "initial_max_new_tokens": int(max_new_tokens),
                    "retry_max_new_tokens": 256,
                    "retry_ms": round((time.perf_counter() - retry_started) * 1000.0, 3),
                }
            normalized["image_transport"] = "raw_rgb"
            normalized["encoded_file_ipc"] = False
            return normalized
        except Exception as exc:
            raw_error = str(exc)

    if not allow_file_fallback:
        raise RuntimeError("raw_memory_required: " + (raw_error or "native raw RGB runtime unavailable"))
    temp_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    try:
        image.save(temp_path)
        fallback = _cpp_detect(
            temp_path, prompt, mode, model_path, cli_path,
            max_new_tokens=max_new_tokens,
        )
        fallback["image_transport"] = "temporary_png"
        fallback["encoded_file_ipc"] = True
        if raw_error:
            fallback["raw_rgb_fallback_error"] = raw_error
        return fallback
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _locate_with_cpp(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return an exact cached result or perform one native grounding request."""
    try:
        key = _cpp_result_key(payload)
    except (OSError, ValueError) as exc:
        return {"status": "error", "backend": "cpp", "error": str(exc)}
    cached = _CPP_RESULT_CACHE.get(key)
    if cached is not None and (not payload.get("_memory_required") or cached.get("runtime") == "dll"):
        _CPP_RESULT_CACHE.move_to_end(key)
        result = copy.deepcopy(cached)
        result["cache_hit"] = True
        result["result_cache"] = "exact"
        return result

    request = dict(payload)
    request["image_identity"] = key[0]
    try:
        result = _locate_with_cpp_uncached(request)
    except RuntimeError as exc:
        if "raw_memory_required" not in str(exc):
            raise
        return {"status":"blocked", "backend":"cpp", "code":"raw_memory_required",
                "error":str(exc), "encoded_file_ipc":False, "next_step":"inspect_native_raw_abi"}
    result = dict(result)
    result["cache_hit"] = False
    result["result_cache"] = "exact"
    if result.get("status") in {"found", "not_found"}:
        _CPP_RESULT_CACHE[key] = copy.deepcopy(result)
        _CPP_RESULT_CACHE.move_to_end(key)
        while len(_CPP_RESULT_CACHE) > _cache_limit("COMPUTER_USE_LOCATE_RESULT_CACHE", 128):
            _CPP_RESULT_CACHE.popitem(last=False)
    return result


def _locate_with_cpp_uncached(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Use locate-anything.cpp CLI + GGUF for visual grounding (no torch)."""
    description = str(payload.get("description", ""))
    original_image_path = str(payload.get("image_path", ""))
    task = str(payload.get("task") or os.getenv("COMPUTER_USE_LOCATE_TASK", "gui"))
    output_type = str(payload.get("output_type") or os.getenv("COMPUTER_USE_LOCATE_OUTPUT", "point"))
    strategy = str(payload.get("strategy") or os.getenv("COMPUTER_USE_LOCATE_STRATEGY", "direct"))
    generation_mode = str(payload.get("generation_mode") or os.getenv("COMPUTER_USE_LOCATE_GENERATION_MODE", "hybrid"))
    max_side = int(payload.get("max_side") or os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "1024"))
    refine_max_side = int(payload.get("refine_max_side") or os.getenv("COMPUTER_USE_LOCATE_REFINE_MAX_SIDE", "1024"))
    refine_pad = int(payload.get("refine_pad") or os.getenv("COMPUTER_USE_LOCATE_REFINE_PAD", "80"))
    max_new_tokens = int(payload.get("max_new_tokens") or os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32"))
    cli_path, model_path = _cpp_runtime_paths()
    if not os.path.exists(cli_path):
        return {"status": "error", "backend": "cpp", "error": f"cli not found: {cli_path}"}
    if not os.path.exists(model_path):
        return {"status": "error", "backend": "cpp", "error": f"model not found: {model_path}"}

    mode = generation_mode if generation_mode in ("hybrid", "slow", "fast") else "slow"
    prompt = _prompt(description, task, output_type, for_cpp=True)
    passes: List[Dict[str, Any]] = []

    def _detect_pass(image: Any, signature: Tuple[Any, ...]) -> Dict[str, Any]:
        return _cpp_detect_image(
            image,
            prompt,
            mode,
            model_path,
            cli_path,
            max_new_tokens=max_new_tokens,
            signature=signature,
            **({"allow_file_fallback":False} if payload.get("_memory_required") else {}),
        )

    def _timed_pass(phase: str, result: Dict[str, Any], **details: Any) -> Dict[str, Any]:
        timing = dict(result.get("timing") or {})
        duration_ms = result.get("duration_ms")
        if duration_ms is None:
            duration_ms = timing.get("duration_ms", timing.get("total_ms"))
        record: Dict[str, Any] = {"phase": phase, "timing": timing, **details}
        if duration_ms is not None:
            record["duration_ms"] = round(float(duration_ms), 3)
        return record

    try:
        stage = _get_cpp_stage(
            original_image_path,
            payload.get("region"),
            max_side,
            identity=payload.get("image_identity"),
            frame_image=payload.get("_frame_image"),
        )
        work_image = stage["work_image"]
        offset = stage["offset"]
        work_w, work_h = stage["work_size"]
        thumb = stage["image"]
        thumb_w, thumb_h = stage["infer_size"]

        used_taskbar_strip = False
        first = _detect_pass(thumb, ("coarse", *stage["key"]))
        if first.get("status") == "error":
            return first
        passes.append(_timed_pass(
            "coarse", first, infer_size=[thumb_w, thumb_h], boxes=first.get("boxes", []),
        ))

        # Full-desktop thumbs often yield 0 cpp detections; taskbar targets work on a bottom strip crop.
        taskbar_hint = not payload.get("region") and any(
            k in description.lower()
            for k in ("taskbar", "search bar", "start button", "store", "tray", "icon on")
        )
        if not first.get("boxes") and taskbar_hint and work_h > 200:
            strip_y = int(work_h * 0.85)
            strip = work_image.crop((0, strip_y, work_w, work_h))
            strip_thumb = _resize_for_inference(strip, max(512, min(max_side, 1024)))
            second_coarse = _detect_pass(
                strip_thumb,
                ("taskbar_strip", *stage["key"], strip_y, strip_thumb.width, strip_thumb.height),
            )
            if second_coarse.get("status") != "error" and second_coarse.get("boxes"):
                used_taskbar_strip = True
                local = _scale_boxes_between_sizes(
                    second_coarse["boxes"], strip_thumb.width, strip_thumb.height, strip.width, strip.height
                )
                first = {
                    "status": "found",
                    "boxes": _offset_boxes(local, 0, strip_y),
                    "detections": second_coarse.get("detections") or [],
                    "raw": second_coarse.get("raw"),
                    "infer_size": list(strip_thumb.size),
                    "runtime": second_coarse.get("runtime"),
                    "timing": second_coarse.get("timing") or {},
                    "image_transport": second_coarse.get("image_transport"),
                    "encoded_file_ipc": second_coarse.get("encoded_file_ipc"),
                }
                passes.append(_timed_pass(
                    "taskbar_strip", second_coarse,
                    infer_size=list(strip_thumb.size),
                    strip_region=[0, strip_y, work_w, work_h - strip_y],
                    boxes=first.get("boxes", []),
                ))

        if used_taskbar_strip:
            boxes = first.get("boxes", [])
        else:
            boxes = _scale_boxes_between_sizes(first.get("boxes", []), thumb_w, thumb_h, work_w, work_h)
        final_boxes = boxes

        if strategy in {"refine", "coarse_refine"} and boxes:
            crop_region = _expand_box(boxes[0], (work_w, work_h), refine_pad)
            crop_img, crop_offset = _crop_image(work_image, crop_region)
            crop_infer = _resize_for_inference(crop_img, refine_max_side)
            second = _detect_pass(
                crop_infer,
                ("refine", *stage["key"], *crop_region, crop_infer.width, crop_infer.height),
            )
            if second.get("status") != "error" and second.get("boxes"):
                local = _scale_boxes_between_sizes(
                    second["boxes"], crop_infer.width, crop_infer.height, crop_img.width, crop_img.height
                )
                final_boxes = _offset_boxes(local, crop_offset[0], crop_offset[1])
                passes.append(_timed_pass(
                    "refine", second, infer_size=list(crop_infer.size), refine_region=crop_region,
                ))

        final_boxes = _offset_boxes(final_boxes, offset[0], offset[1])
        box = final_boxes[0] if final_boxes else None
        center = _box_center(box) if box else None
        points = [center] if center else []
        source_detections = first.get("detections") or []
        detections = []
        for index, final_box in enumerate(final_boxes):
            label = ""
            if index < len(source_detections):
                label = str(source_detections[index].get("label", ""))
            detections.append({"label": label, "box": final_box, "center": _box_center(final_box)})

        return {
            "status": "found" if box or center else "not_found",
            "backend": "cpp",
            "description": description,
            "image_path": original_image_path,
            "coordinate_space": "source_image_pixels",
            "box": box,
            "boxes": final_boxes,
            "detections": detections,
            "center": center,
            "points": points,
            "raw": json.dumps(first.get("raw", {}))[:2000],
            "score": 1.0,
            "device": "cpp",
            "generation_mode": mode,
            "max_new_tokens": max_new_tokens,
            "runtime": first.get("runtime", "cli"),
            "timing": first.get("timing") or {},
            "task": task,
            "output_type": output_type,
            "strategy": strategy,
            "passes": passes,
            "work_size": [work_w, work_h],
            "source_size": list(stage["source_size"]),
            "stage_cache_hit": bool(stage.get("cache_hit")),
            "stage_preprocess_ms": float(stage.get("preprocess_ms", 0.0)),
            "image_transport": first.get("image_transport"),
            "encoded_file_ipc": first.get("encoded_file_ipc"),
        }
    except Exception as exc:
        return {"status": "error", "backend": "cpp", "error": str(exc)}

def _load(device: Optional[str] = None, model_id: Optional[str] = None, dtype_name: Optional[str] = None) -> Dict[str, Any]:
    global _MODEL, _PROCESSOR, _TOK, _TORCH, _DEVICE, _MODEL_ID, _DTYPE_NAME
    requested = None if device in {None, "", "auto"} else str(device)
    model_id = model_id or os.getenv("COMPUTER_USE_LOCATE_MODEL", "nvidia/LocateAnything-3B")
    if _MODEL is not None and _MODEL_ID == model_id and (requested is None or requested == _DEVICE):
        return {"status": "already_loaded", "backend": "external", "device": _DEVICE, "model": _MODEL_ID, "dtype": _DTYPE_NAME}
    try:
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer
    except Exception as exc:
        return {"status": "error", "backend": "external", "error": f"torch/transformers unavailable in external python: {exc}", "python": sys.executable}
    cuda_available = bool(torch.cuda.is_available())
    if requested == "cuda" and not cuda_available:
        return {"status": "error", "backend": "external", "error": "CUDA requested but torch.cuda.is_available() is false in external python", "python": sys.executable, "torch": torch.__version__, "cuda_available": cuda_available, "cuda_version": getattr(torch.version, "cuda", None)}
    resolved = requested or ("cuda" if cuda_available else "cpu")
    dtype_name = (dtype_name or os.getenv("COMPUTER_USE_LOCATE_DTYPE") or ("bfloat16" if resolved == "cuda" else "float32")).lower()
    dtype = {"bf16": torch.bfloat16, "bfloat16": torch.bfloat16, "fp16": torch.float16, "float16": torch.float16, "fp32": torch.float32, "float32": torch.float32}.get(dtype_name, torch.bfloat16 if resolved == "cuda" else torch.float32)
    try:
        _TOK = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        _PROCESSOR = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        _MODEL = AutoModel.from_pretrained(model_id, torch_dtype=dtype, trust_remote_code=True).to(resolved).eval()
        _TORCH = torch
        _DEVICE = resolved
        _MODEL_ID = model_id
        _DTYPE_NAME = dtype_name
        return {"status": "loaded", "backend": "external", "device": resolved, "model": model_id, "python": sys.executable, "torch": torch.__version__, "cuda_available": cuda_available, "cuda_version": getattr(torch.version, "cuda", None), "dtype": dtype_name}
    except Exception as exc:
        _MODEL = _PROCESSOR = _TOK = _TORCH = _DEVICE = _MODEL_ID = _DTYPE_NAME = None
        return {"status": "error", "backend": "external", "error": str(exc), "python": sys.executable, "torch": torch.__version__, "cuda_available": cuda_available, "cuda_version": getattr(torch.version, "cuda", None), "device": resolved, "dtype": dtype_name}


def _prompt(description: str, task: str, output_type: str, *, for_cpp: bool = False) -> str:
    task = (task or "gui").lower()
    output_type = (output_type or "box").lower()
    if for_cpp:
        # locate-anything-cli expects the upstream open-vocab template (see fixture_spec.json).
        if task == "detect_text":
            return "Detect all the text in box format."
        if task == "multi":
            if "</c>" in description:
                parts = [p.strip() for p in description.split("</c>") if p.strip()]
            else:
                parts = [p.strip() for p in re.split(r"[,;]|\band\b", description) if p.strip()]
            cats = "</c>".join(parts) if len(parts) > 1 else description.strip()
            return f"Locate all the instances that matches the following description: {cats}."
        # gui / single / point — single category string
        label = description.strip()
        return f"Locate all the instances that matches the following description: {label}."
    if output_type == "point":
        return f"Point to: {description}."
    if task == "text":
        return f"Please locate the text referred as {description}."
    if task == "detect_text":
        return "Detect all the text in box format."
    if task == "multi":
        return f"Locate all the instances that match the following description: {description}."
    if task == "single":
        return f"Locate a single instance that matches the following description: {description}."
    return f"Locate the region that matches the following description: {description}."


def _crop_image(image, region: Optional[Any]):
    if not region:
        return image, (0, 0)
    if isinstance(region, dict):
        x, y, w, h = int(region["x"]), int(region["y"]), int(region["width"]), int(region["height"])
    else:
        x, y, w, h = [int(v) for v in region[:4]]
    x = max(0, min(image.width - 1, x)); y = max(0, min(image.height - 1, y))
    w = max(1, min(image.width - x, w)); h = max(1, min(image.height - y, h))
    return image.crop((x, y, x + w, y + h)), (x, y)


def _resize_for_inference(image, max_side: int):
    infer_image = image.copy()
    if max(infer_image.size) > max_side:
        infer_image.thumbnail((max_side, max_side), infer_image.Resampling.LANCZOS if hasattr(infer_image, "Resampling") else 1)
    return infer_image


def _predict(image, question: str, max_new_tokens: int, generation_mode: str, temperature: float, top_p: float, repetition_penalty: float, do_sample: bool, verbose: bool, prompt_style: str) -> Tuple[str, Dict[str, Any]]:
    prompt_style = (prompt_style or "direct").lower()
    if prompt_style in {"direct", "simple"}:
        inputs = _PROCESSOR(text=f"<image-1> {question}", images=[image], return_tensors="pt")
        dev = next(_MODEL.parameters()).device
        inputs = {k: v.to(dev) if hasattr(v, "to") else v for k, v in inputs.items()}
        kwargs = dict(**inputs, tokenizer=getattr(_PROCESSOR, "tokenizer", _TOK), use_cache=True, max_new_tokens=max_new_tokens)
        # Some remote-code versions accept generation_mode; keep it opportunistic.
        try:
            generated = _MODEL.generate(**kwargs, generation_mode=generation_mode, temperature=temperature, do_sample=do_sample, top_p=top_p, repetition_penalty=repetition_penalty, verbose=verbose)
        except TypeError:
            generated = _MODEL.generate(**kwargs)
        if isinstance(generated, str):
            text = generated
        else:
            text = _PROCESSOR.batch_decode(generated, skip_special_tokens=False)[0]
        return text, {"input_mode": "direct"}

    # Documented chat-template path. It is available as an option but was slower
    # on Windows UI screenshots in local profiling.
    try:
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": question}]}]
        text = _PROCESSOR.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = _PROCESSOR.process_vision_info(messages)
        inputs = _PROCESSOR(text=[text], images=images, videos=videos, return_tensors="pt").to(_DEVICE)
        pixel_values = inputs["pixel_values"].to(next(_MODEL.parameters()).dtype)
        response = _MODEL.generate(
            pixel_values=pixel_values,
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            image_grid_hws=inputs.get("image_grid_hws", None),
            tokenizer=_TOK or _PROCESSOR.tokenizer,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            generation_mode=generation_mode,
            temperature=temperature,
            do_sample=do_sample,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            verbose=verbose,
        )
        answer = response[0] if isinstance(response, tuple) else response
        stats = response[2] if isinstance(response, tuple) and len(response) >= 3 else None
        return str(answer), {"input_mode": "chat_template", "stats": stats}
    except Exception as chat_exc:
        text, meta = _predict(image, question, max_new_tokens, generation_mode, temperature, top_p, repetition_penalty, do_sample, verbose, "direct")
        meta["chat_fallback_error"] = str(chat_exc)
        return text, meta

def _one_pass(image, description: str, *, task: str, output_type: str, max_side: int, max_new_tokens: int, generation_mode: str, temperature: float, top_p: float, repetition_penalty: float, do_sample: bool, verbose: bool, prompt_style: str) -> Dict[str, Any]:
    infer_image = _resize_for_inference(image, max_side)
    question = _prompt(description, task, output_type)
    t0 = time.perf_counter()
    text, meta = _predict(infer_image, question, max_new_tokens, generation_mode, temperature, top_p, repetition_penalty, do_sample, verbose, prompt_style)
    dt = time.perf_counter() - t0
    boxes = _parse_boxes(text, infer_image.size)
    points = _parse_points(text, infer_image.size)
    sx = image.width / infer_image.width
    sy = image.height / infer_image.height
    scaled_boxes = [{"x1": round(b["x1"] * sx), "y1": round(b["y1"] * sy), "x2": round(b["x2"] * sx), "y2": round(b["y2"] * sy)} for b in boxes]
    scaled_points = [{"x": round(p["x"] * sx), "y": round(p["y"] * sy)} for p in points]
    chosen_box = scaled_boxes[0] if scaled_boxes else None
    chosen_point = scaled_points[0] if scaled_points else (_box_center(chosen_box) if chosen_box else None)
    return {"raw": text, "boxes": scaled_boxes, "points": scaled_points, "box": chosen_box, "center": chosen_point, "seconds": round(dt, 3), "question": question, "infer_size": list(infer_image.size), **meta}


def _expand_box(box: Dict[str, int], image_size: Tuple[int, int], pad: int) -> List[int]:
    w, h = image_size
    x1 = max(0, box["x1"] - pad); y1 = max(0, box["y1"] - pad)
    x2 = min(w, box["x2"] + pad); y2 = min(h, box["y2"] + pad)
    return [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]


def _region_around_point(point: Dict[str, int], image_size: Tuple[int, int], radius: int) -> List[int]:
    w, h = image_size
    x, y = int(point["x"]), int(point["y"])
    x1 = max(0, x - radius); y1 = max(0, y - radius)
    x2 = min(w, x + radius); y2 = min(h, y + radius)
    return [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]


def _locate(payload: Dict[str, Any]) -> Dict[str, Any]:
    from PIL import Image

    description = str(payload["description"])
    image_path = str(payload["image_path"])
    threshold = float(payload.get("threshold", 0.3))
    device = payload.get("device")
    model_id = payload.get("model_id")
    task = str(payload.get("task") or os.getenv("COMPUTER_USE_LOCATE_TASK", "gui"))
    output_type = str(payload.get("output_type") or os.getenv("COMPUTER_USE_LOCATE_OUTPUT", "point"))
    strategy = str(payload.get("strategy") or os.getenv("COMPUTER_USE_LOCATE_STRATEGY", "direct"))
    max_side = int(payload.get("max_side") or os.getenv("COMPUTER_USE_LOCATE_MAX_SIDE", "640"))
    refine_max_side = int(payload.get("refine_max_side") or os.getenv("COMPUTER_USE_LOCATE_REFINE_MAX_SIDE", "1024"))
    point_refine_radius = int(payload.get("point_refine_radius") or os.getenv("COMPUTER_USE_LOCATE_POINT_REFINE_RADIUS", "360"))
    max_new_tokens = int(payload.get("max_new_tokens") or os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32"))
    generation_mode = str(payload.get("generation_mode") or os.getenv("COMPUTER_USE_LOCATE_GENERATION_MODE", "hybrid"))
    temperature = float(payload.get("temperature") or os.getenv("COMPUTER_USE_LOCATE_TEMPERATURE", "0.7"))
    top_p = float(payload.get("top_p") or os.getenv("COMPUTER_USE_LOCATE_TOP_P", "0.9"))
    repetition_penalty = float(payload.get("repetition_penalty") or os.getenv("COMPUTER_USE_LOCATE_REPETITION_PENALTY", "1.1"))
    do_sample = str(payload.get("do_sample", os.getenv("COMPUTER_USE_LOCATE_DO_SAMPLE", "false"))).lower() not in {"0", "false", "no", "off"}
    verbose = str(payload.get("verbose", os.getenv("COMPUTER_USE_LOCATE_VERBOSE", "false"))).lower() in {"1", "true", "yes", "on"}
    prompt_style = str(payload.get("prompt_style") or os.getenv("COMPUTER_USE_LOCATE_PROMPT_STYLE", "direct"))

    backend = str(payload.get("backend") or os.getenv("COMPUTER_USE_LOCATE_BACKEND", "cpp")).lower().strip()
    if backend == "auto":
        configured = os.getenv("COMPUTER_USE_LOCATE_BACKEND", "cpp").lower().strip()
        backend = configured if configured != "auto" else "cpp"
    if backend == "cpp":
        if payload.get("region") is not None:
            from speed_grounding import locate_roi
            return locate_roi(payload, _locate_with_cpp)
        return _locate_with_cpp(payload)

    load = _load(device=device, model_id=model_id, dtype_name=payload.get("dtype"))
    if load.get("status") == "error":
        return {"status": "error", "backend": "external", "error": load.get("error"), "load": load}

    full_image = Image.open(image_path).convert("RGB")
    image, offset = _crop_image(full_image, payload.get("region"))
    passes = []
    first = _one_pass(image, description, task=task, output_type=output_type, max_side=max_side, max_new_tokens=max_new_tokens, generation_mode=generation_mode, temperature=temperature, top_p=top_p, repetition_penalty=repetition_penalty, do_sample=do_sample, verbose=verbose, prompt_style=prompt_style)
    passes.append({k: v for k, v in first.items() if k not in {"raw"}})
    final = first

    # For box requests, the best speed/accuracy tradeoff on UI screenshots is:
    # cheap coarse point at low resolution -> crop around the point -> box locate
    # within that smaller crop at higher effective resolution.
    if output_type == "box" and strategy in {"auto", "point_refine"}:
        point_pass = _one_pass(image, description, task=task, output_type="point", max_side=max_side, max_new_tokens=max_new_tokens, generation_mode=generation_mode, temperature=temperature, top_p=top_p, repetition_penalty=repetition_penalty, do_sample=do_sample, verbose=verbose, prompt_style=prompt_style)
        passes.append({k: v for k, v in point_pass.items() if k not in {"raw"}} | {"phase": "coarse_point"})
        point = point_pass.get("center")
        if point:
            crop_region = _region_around_point(point, (image.width, image.height), point_refine_radius)
            crop, crop_offset = _crop_image(image, crop_region)
            second = _one_pass(crop, description, task=task, output_type="box", max_side=refine_max_side, max_new_tokens=max_new_tokens, generation_mode=generation_mode, temperature=temperature, top_p=top_p, repetition_penalty=repetition_penalty, do_sample=do_sample, verbose=verbose, prompt_style=prompt_style)
            if second.get("box"):
                b = second["box"]
                second["box"] = {"x1": b["x1"] + crop_offset[0], "y1": b["y1"] + crop_offset[1], "x2": b["x2"] + crop_offset[0], "y2": b["y2"] + crop_offset[1]}
                second["center"] = _box_center(second["box"])
                second["boxes"] = [second["box"]]
            if second.get("points"):
                second["points"] = [{"x": p["x"] + crop_offset[0], "y": p["y"] + crop_offset[1]} for p in second["points"]]
                if not second.get("center"):
                    second["center"] = second["points"][0]
            passes.append({k: v for k, v in second.items() if k not in {"raw"}} | {"phase": "point_refine_box", "refine_region": crop_region})
            if second.get("box") or second.get("center"):
                final = second

    # Auto-refine only when the first result is a box and is too coarse. Pointing
    # is usually the fastest click target and often needs no second pass.
    if strategy in {"refine", "coarse_refine"}:
        box = first.get("box")
        if box:
            area_ratio = ((box["x2"] - box["x1"]) * (box["y2"] - box["y1"])) / max(1, image.width * image.height)
            too_large = area_ratio > float(payload.get("refine_area_ratio") or os.getenv("COMPUTER_USE_LOCATE_REFINE_AREA_RATIO", "0.20"))
            explicit = strategy in {"refine", "coarse_refine"}
            if too_large or explicit:
                crop_region = _expand_box(box, (image.width, image.height), int(payload.get("refine_pad") or os.getenv("COMPUTER_USE_LOCATE_REFINE_PAD", "80")))
                crop, crop_offset = _crop_image(image, crop_region)
                second = _one_pass(crop, description, task=task, output_type=output_type, max_side=refine_max_side, max_new_tokens=max_new_tokens, generation_mode=generation_mode, temperature=temperature, top_p=top_p, repetition_penalty=repetition_penalty, do_sample=do_sample, verbose=verbose, prompt_style=prompt_style)
                if second.get("box"):
                    b = second["box"]
                    second["box"] = {"x1": b["x1"] + crop_offset[0], "y1": b["y1"] + crop_offset[1], "x2": b["x2"] + crop_offset[0], "y2": b["y2"] + crop_offset[1]}
                    second["center"] = _box_center(second["box"])
                if second.get("points"):
                    second["points"] = [{"x": p["x"] + crop_offset[0], "y": p["y"] + crop_offset[1]} for p in second["points"]]
                    second["center"] = second["points"][0]
                passes.append({k: v for k, v in second.items() if k not in {"raw"}} | {"refine_region": crop_region})
                if second.get("box") or second.get("center"):
                    final = second

    box = final.get("box")
    center = final.get("center")
    points = final.get("points") or ([] if not center else [center])
    boxes = final.get("boxes") or ([] if not box else [box])
    if offset != (0, 0):
        if box:
            box = {"x1": box["x1"] + offset[0], "y1": box["y1"] + offset[1], "x2": box["x2"] + offset[0], "y2": box["y2"] + offset[1]}
        boxes = [{"x1": b["x1"] + offset[0], "y1": b["y1"] + offset[1], "x2": b["x2"] + offset[0], "y2": b["y2"] + offset[1]} for b in boxes]
        if center:
            center = {"x": center["x"] + offset[0], "y": center["y"] + offset[1]}
        points = [{"x": p["x"] + offset[0], "y": p["y"] + offset[1]} for p in points]

    if not box and not center:
        return {"status": "not_found", "backend": "external", "description": description, "raw": final.get("raw"), "image_path": image_path, "device": _DEVICE, "load": load, "passes": passes, "task": task, "output_type": output_type, "strategy": strategy, "prompt_style": prompt_style}
    return {
        "status": "found", "backend": "external", "description": description, "image_path": image_path,
        "box": box, "boxes": boxes, "center": center, "points": points,
        "raw": final.get("raw"), "score": 1.0, "threshold": threshold, "device": _DEVICE, "load": load,
        "task": task, "output_type": output_type, "strategy": strategy, "passes": passes,
        "generation_mode": generation_mode, "max_side": max_side, "refine_max_side": refine_max_side, "max_new_tokens": max_new_tokens, "prompt_style": prompt_style, "point_refine_radius": point_refine_radius,
    }


def _validate_batch_targets(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty list")
    if len(targets) > 16:
        raise ValueError("targets accepts at most 16 entries")
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    seen_descriptions: set[str] = set()
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValueError(f"target {index} must be an object")
        target_id = str(target.get("id", "")).strip()
        description = str(target.get("description", "")).strip()
        if not target_id:
            raise ValueError(f"target {index} requires id")
        if target_id in seen:
            raise ValueError("target ids must be unique")
        if not description:
            raise ValueError(f"target {target_id!r} requires description")
        if "</c>" in description:
            raise ValueError("target descriptions cannot contain the </c> category separator")
        normalized_description = _normalized_label(description)
        if normalized_description in seen_descriptions:
            raise ValueError("target descriptions must be unique after normalization")
        seen.add(target_id)
        seen_descriptions.add(normalized_description)
        normalized.append({"id": target_id, "description": description})
    return normalized


def _normalized_label(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _target_from_result(target: Dict[str, str], result: Dict[str, Any]) -> Dict[str, Any]:
    box = result.get("box")
    center = result.get("center")
    detections = result.get("detections") or []
    label = target["description"]
    if detections and isinstance(detections[0], dict):
        label = str(detections[0].get("label") or label)
    return {
        "id": target["id"],
        "description": target["description"],
        "status": result.get("status", "error"),
        "label": label,
        "box": box,
        "center": center,
        "backend": result.get("backend"),
        "runtime": result.get("runtime"),
        "cache_hit": result.get("cache_hit", False),
        "result_cache": result.get("result_cache"),
        "stage_cache_hit": result.get("stage_cache_hit"),
        "image_transport": result.get("image_transport"),
        "encoded_file_ipc": result.get("encoded_file_ipc"),
    }


def _locate_batch_exact(payload: Dict[str, Any], targets: List[Dict[str, str]]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    passes: List[Dict[str, Any]] = []
    for target in targets:
        request = dict(payload)
        request.pop("targets", None)
        request["action"] = "locate"
        request["description"] = target["description"]
        # Independent prompts retain baseline semantics. The persistent DLL
        # adapter reuses the exact image's prepared vision features.
        result = _locate(request)
        results.append(_target_from_result(target, result))
        for item in result.get("passes") or []:
            if isinstance(item, dict):
                passes.append(dict(item, target_id=target["id"]))
    status = "found" if all(item["status"] == "found" for item in results) else "partial"
    if any(item["status"] == "error" for item in results):
        status = "error"
    elif all(item["status"] == "not_found" for item in results):
        status = "not_found"
    return {"status": status, "targets": results, "passes": passes}


def _locate_batch_one_pass(payload: Dict[str, Any], targets: List[Dict[str, str]]) -> Dict[str, Any]:
    request = dict(payload)
    request.pop("targets", None)
    request["action"] = "locate"
    request["task"] = "multi"
    request["description"] = "</c>".join(target["description"] for target in targets)
    request["max_new_tokens"] = max(
        int(request.get("max_new_tokens") or 32),
        min(256, 32 * len(targets)),
    )
    result = _locate(request)
    by_label: Dict[str, List[Dict[str, Any]]] = {}
    for detection in result.get("detections") or []:
        if not isinstance(detection, dict):
            continue
        by_label.setdefault(_normalized_label(detection.get("label")), []).append(detection)
    mapped: List[Dict[str, Any]] = []
    valid = True
    for target in targets:
        matches = by_label.get(_normalized_label(target["description"]), [])
        if len(matches) != 1:
            valid = False
            mapped.append({
                "id": target["id"], "description": target["description"],
                "status": "ambiguous" if len(matches) > 1 else "not_found",
                "label": None, "box": None, "center": None,
            })
            continue
        detection = matches[0]
        box = detection.get("box")
        if isinstance(box, (list, tuple)) and len(box) >= 4:
            box = {"x1": round(float(box[0])), "y1": round(float(box[1])),
                   "x2": round(float(box[2])), "y2": round(float(box[3]))}
        center = detection.get("center") or (_box_center(box) if isinstance(box, dict) else None)
        mapped.append({
            "id": target["id"], "description": target["description"],
            "status": "found", "label": str(detection.get("label", "")),
            "box": box, "center": center, "backend": result.get("backend"),
            "runtime": result.get("runtime"),
        })
    return {
        "status": "found" if valid else "partial",
        "targets": mapped,
        "passes": result.get("passes") or [],
        "label_mapping_valid": valid,
        "one_pass_result": result,
    }


def _one_pass_key(targets: List[Dict[str, str]]) -> Tuple[str, ...]:
    return tuple(_normalized_label(target["description"]) for target in targets)


def _record_one_pass(targets: List[Dict[str, str]], valid: bool) -> Dict[str, int]:
    key = _one_pass_key(targets)
    stats = _ONE_PASS_STATS.setdefault(key, {"successes": 0, "failures": 0})
    stats["successes" if valid else "failures"] += 1
    return dict(stats)


def _one_pass_eligible(targets: List[Dict[str, str]]) -> Tuple[bool, Dict[str, int]]:
    stats = dict(_ONE_PASS_STATS.get(_one_pass_key(targets), {"successes": 0, "failures": 0}))
    return stats["successes"] >= 2 and stats["failures"] == 0, stats


def _locate_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        targets = _validate_batch_targets(payload)
        mode = str(payload.get("mode") or "exact").strip().lower()
        if mode not in {"auto", "exact", "one_pass"}:
            raise ValueError("mode must be auto, exact, or one_pass")
        if not str(payload.get("image_path", "")).strip():
            raise ValueError("image_path is required")
    except ValueError as exc:
        return {"status": "error", "backend": "external", "error": str(exc)}

    # Hash the immutable source once and share the identity with every exact
    # prompt. This avoids repeated source hashing inside a single batch.
    try:
        payload = dict(payload)
        payload["image_identity"] = tuple(payload.get("image_identity") or _image_identity(str(payload["image_path"])))
    except OSError:
        # Validation and unit-test seams may supply a synthetic path; the real
        # locate call still reports the missing image before native inference.
        payload["image_identity"] = ("unreadable", os.path.abspath(str(payload["image_path"])))

    if mode == "exact":
        result = _locate_batch_exact(payload, targets)
        result.update({
            "mode_requested": mode, "mode_used": "exact", "label_mapping_valid": True,
            "one_pass_eligible": False,
        })
        return result

    if mode == "one_pass":
        one_pass = _locate_batch_one_pass(payload, targets)
        stats = _record_one_pass(targets, bool(one_pass.get("label_mapping_valid")))
        one_pass.update({
            "mode_requested": mode, "mode_used": "one_pass",
            "one_pass_eligible": True, "one_pass_stats": stats,
        })
        return one_pass

    eligible, stats = _one_pass_eligible(targets)
    if not eligible:
        exact = _locate_batch_exact(payload, targets)
        exact.update({
            "mode_requested": mode,
            "mode_used": "exact_adaptive",
            "label_mapping_valid": True,
            "one_pass_eligible": False,
            "one_pass_stats": stats,
            "adaptive_reason": "one-pass requires two prior exact-label successes and no failures",
        })
        return exact

    one_pass = _locate_batch_one_pass(payload, targets)
    valid = bool(one_pass.get("label_mapping_valid"))
    updated_stats = _record_one_pass(targets, valid)
    if valid:
        one_pass.update({
            "mode_requested": mode,
            "mode_used": "one_pass_adaptive",
            "one_pass_eligible": True,
            "one_pass_stats": updated_stats,
        })
        return one_pass

    exact = _locate_batch_exact(payload, targets)
    exact.update({
        "mode_requested": mode,
        "mode_used": "exact_fallback",
        "label_mapping_valid": False,
        "one_pass_eligible": True,
        "one_pass_stats": updated_stats,
        "fallback_reason": "one-pass labels were missing, duplicated, or ambiguous",
        "one_pass_timing": one_pass.get("passes") or [],
    })
    return exact


def _handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    action = payload.get("action", "locate")
    if payload.get("frame_transport") is not None:
        try:
            from multiprocessing import shared_memory
            from PIL import Image
            frame = payload["frame_transport"]
            width, height, size = frame["width"], frame["height"], frame["size"]
            if (any(type(v) is not int for v in (width, height, size)) or
                    width <= 0 or height <= 0 or size != width * height * 3 or size > 128 * 1024 * 1024):
                raise ValueError("invalid shared RGB dimensions")
            segment = shared_memory.SharedMemory(name=frame["name"])
            try:
                if segment.size < size:
                    raise ValueError("short shared RGB buffer")
                pixels = bytes(segment.buf[:size])
            finally:
                segment.close()
            if hashlib.sha256(pixels).hexdigest() != frame["sha256"]:
                raise ValueError("shared RGB digest mismatch")
            payload = dict(payload)
            payload["image_identity"] = ("rgb-v1", width, height, frame["sha256"])
            payload["_frame_image"] = Image.frombytes("RGB", (width, height), pixels)
        except Exception as exc:
            return _finish_response(payload, {"status": "error", "error": str(exc)}, started)
    if action == "prepare_frame":
        # Explicit immutable input only; no capture and no inference/decode.
        try:
            if time.monotonic() >= float(payload.get("_prefetch_deadline", float("inf"))):
                return _finish_response(payload, {"status": "discarded", "code": "stale_frame"}, started)
            stage = _get_cpp_stage(str(payload["image_path"]), payload.get("region"),
                                   int(payload.get("max_side", 1024)),
                                   identity=payload.get("image_identity"), frame_image=payload.get("_frame_image"))
            _, model_path = _cpp_runtime_paths()
            if payload.get("_speculative"):
                runtime = _CPP_DLL_RUNTIME
                if runtime is None:
                    return _finish_response(payload, {"status": "blocked", "code": "resident_native_engine_required"}, started)
            else:
                runtime = _get_cpp_dll_runtime(model_path)
            if runtime is None:
                raise RuntimeError("resident native DLL preparation unavailable")
            image = stage["image"]
            runtime.prepare_rgb(image.tobytes("raw", "RGB"), width=image.width, height=image.height,
                                stride=image.width * 3, signature=("coarse", *stage["key"]))
            response = {"status": "prepared", "runtime": "dll", "backend": "cpp",
                        "infer_size": list(image.size), "image_transport": "raw_rgb", "decode": False}
        except Exception as exc:
            response = {"status": "error", "code": "prepare_unavailable", "error": str(exc),
                        "next_step": "warm_native_backend", "retryable": False}
        return _finish_response(payload, response, started)
    if action == "warm":
        backend = str(payload.get("backend") or os.getenv("COMPUTER_USE_LOCATE_BACKEND", "cpp")).lower().strip()
        if backend == "auto":
            configured = os.getenv("COMPUTER_USE_LOCATE_BACKEND", "cpp").lower().strip()
            backend = configured if configured != "auto" else "cpp"
        if backend == "cpp":
            cli_path, model_path = _cpp_runtime_paths()
            if not (os.path.exists(cli_path) and os.path.exists(model_path)):
                response = {"status": "error", "backend": "cpp", "cli": cli_path, "model": model_path, "error": "cli or model not found"}
                return _finish_response(payload, response, started)
            runtime = _get_cpp_dll_runtime(model_path)
            if runtime is not None:
                response = {
                    "status": "loaded",
                    "backend": "cpp",
                    "runtime": "dll",
                    "model": model_path,
                    "dll": runtime.dll_path,
                    "dll_sha256": getattr(runtime, "dll_sha256", None),
                    "abi_version": runtime.abi_version,
                    "raw_rgb": runtime._prepare_rgb is not None,
                    "device": "CUDA",
                    "persistent": True,
                    "warm": "native Engine and CUDA weights remain resident in the JSONL worker",
                }
                return _finish_response(payload, response, started)
            # Compatibility fallback when a validated shared library is absent.
            import subprocess
            try:
                proc = subprocess.run([cli_path, "info", "--model", model_path], capture_output=True, text=True, timeout=120)
                out = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 0 and ("Backend using device" in out or "loaded ok" in out):
                    response = {"status": "loaded", "backend": "cpp", "runtime": "cli", "cli": cli_path, "model": model_path, "device": "CUDA", "warm": "info succeeded", "dll_fallback_error": _CPP_DLL_LAST_ERROR}
                else:
                    err = out[-500:]
                    response = {"status": "error", "backend": "cpp", "error": err, "cli": cli_path}
            except Exception as exc:
                response = {"status": "error", "backend": "cpp", "error": str(exc), "cli": cli_path}
            return _finish_response(payload, response, started)
        return _finish_response(payload, _load(device=payload.get("device"), model_id=payload.get("model_id"), dtype_name=payload.get("dtype")), started)
    if action == "probe":
        try:
            import torch
            response = {"status": "ok", "backend": "external", "python": sys.executable, "torch": torch.__version__, "cuda_available": bool(torch.cuda.is_available()), "cuda_version": getattr(torch.version, "cuda", None)}
        except Exception as exc:
            response = {"status": "error", "backend": "external", "python": sys.executable, "error": str(exc)}
        return _finish_response(payload, response, started)
    if action == "locate":
        return _finish_response(payload, _locate(payload), started)
    if action == "locate_batch":
        return _finish_response(payload, _locate_batch(payload), started)
    if action == "shutdown":
        _shutdown_cpp_dll_runtime()
        return _finish_response(payload, {"status": "ok", "backend": "external", "action": "shutdown"}, started)
    return _finish_response(payload, {"status": "error", "backend": "external", "error": f"unknown action {action!r}"}, started)


def _finish_response(payload: Dict[str, Any], response: Dict[str, Any], started: float) -> Dict[str, Any]:
    """Attach protocol correlation and consistent total/per-pass telemetry."""
    result = dict(response)
    if payload.get("frame_transport") is not None:
        result["capture_transport"] = "shared_rgb"
    if payload.get("request_id") is not None:
        result["request_id"] = str(payload["request_id"])
    pass_timings: List[Dict[str, Any]] = []
    for index, item in enumerate(result.get("passes") or []):
        if not isinstance(item, dict):
            continue
        duration_ms = item.get("duration_ms")
        if duration_ms is None and item.get("seconds") is not None:
            duration_ms = float(item["seconds"]) * 1000.0
        if duration_ms is None and isinstance(item.get("timing"), dict):
            duration_ms = item["timing"].get("duration_ms")
        if duration_ms is None:
            continue
        pass_timings.append({
            "phase": str(item.get("phase") or f"pass_{index + 1}"),
            "duration_ms": round(float(duration_ms), 3),
        })
    existing_timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
    timing = dict(existing_timing)
    timing["total_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    timing["passes"] = pass_timings or list(timing.get("passes") or [])
    result["timing"] = timing
    return result


def main() -> int:
    if "--server" in sys.argv:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                response = _handle(payload)
                _json(response)
                if payload.get("action") == "shutdown":
                    return 0
            except Exception as exc:
                error = {"status": "error", "backend": "external", "error": str(exc), "python": sys.executable}
                if isinstance(locals().get("payload"), dict) and payload.get("request_id") is not None:
                    error["request_id"] = str(payload["request_id"])
                _json(error)
        return 0
    try:
        payload = json.loads(sys.stdin.read())
        _json(_handle(payload))
        return 0
    except Exception as exc:
        _json({"status": "error", "backend": "external", "error": str(exc), "python": sys.executable})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

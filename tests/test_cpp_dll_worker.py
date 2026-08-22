from __future__ import annotations

import ctypes
import importlib.util
import json
import os
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "windows_computer_use_locate_worker.py"


def load_worker(name: str):
    spec = importlib.util.spec_from_file_location(name, WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeFn:
    def __init__(self, fn):
        self.fn = fn
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.fn(*args)


class FakeDLL:
    def __init__(self):
        self.load_calls = 0
        self.prepare_calls: list[str] = []
        self.prepare_rgb_calls: list[tuple[int, int, int, bytes]] = []
        self.locate_calls: list[str] = []
        self.clear_calls = 0
        self._buffers = []
        self.la_capi_abi_version = FakeFn(lambda: 3)
        self.la_capi_load = FakeFn(self._load)
        self.la_capi_free = FakeFn(lambda ctx: None)
        self.la_capi_prepare_path = FakeFn(self._prepare)
        self.la_capi_prepare_rgb = FakeFn(self._prepare_rgb)
        self.la_capi_locate_prepared_ex = FakeFn(self._locate)
        self.la_capi_clear_prepared = FakeFn(self._clear)
        self.la_capi_free_string = FakeFn(lambda value: None)
        self.la_capi_last_error = FakeFn(lambda ctx: b"")

    def _load(self, model, threads):
        self.load_calls += 1
        return 1234

    def _prepare(self, ctx, path):
        self.prepare_calls.append(path.decode("utf-8"))
        return 0

    def _prepare_rgb(self, ctx, pixels, width, height, stride):
        size = int(height) * int(stride)
        self.prepare_rgb_calls.append((int(width), int(height), int(stride), ctypes.string_at(pixels, size)))
        return 0

    def _locate(self, ctx, prompt, mode, max_new_tokens):
        self.locate_calls.append(prompt.decode("utf-8"))
        payload = {
            "detections": [{"label": prompt.decode("utf-8"), "box": [1.0, 2.0, 11.0, 12.0]}],
            "timing": {"prepare_ms": 3.5, "locate_ms": 7.25},
        }
        buf = ctypes.create_string_buffer(json.dumps(payload).encode("utf-8"))
        self._buffers.append(buf)
        return ctypes.addressof(buf)

    def _clear(self, ctx):
        self.clear_calls += 1


def test_dll_runtime_loads_once_reuses_prepared_image_and_preserves_json(monkeypatch, tmp_path):
    worker = load_worker("theia_cpp_dll")
    fake = FakeDLL()
    monkeypatch.setattr(worker.ctypes, "CDLL", lambda path: fake)
    dll_path = tmp_path / "locate-anything.dll"
    model_path = tmp_path / "model.gguf"
    dll_path.write_bytes(b"dll")
    model_path.write_bytes(b"model")
    screen_path = tmp_path / "screen.png"
    same_screen_path = tmp_path / "same-screen.png"
    screen_path.write_bytes(b"identical encoded pixels")
    same_screen_path.write_bytes(b"identical encoded pixels")

    runtime = worker._LocateAnythingDLL(str(dll_path), str(model_path), threads=2)
    runtime.prepare_path(str(screen_path))
    first = runtime.locate_prepared("Save icon", "hybrid")
    runtime.prepare_path(str(same_screen_path))
    assert runtime.prepare_timing == {}
    second = runtime.locate_prepared("Cancel button", "fast")

    assert fake.load_calls == 1
    assert fake.prepare_calls == [os.path.abspath(screen_path)]
    assert fake.locate_calls == ["Save icon", "Cancel button"]
    assert first["detections"][0]["label"] == "Save icon"
    assert first["timing"] == {"prepare_ms": 3.5, "locate_ms": 7.25}
    assert second["detections"][0]["box"] == [1.0, 2.0, 11.0, 12.0]


def test_dll_runtime_clears_prepared_state_when_image_changes(monkeypatch, tmp_path):
    worker = load_worker("theia_cpp_dll_clear")
    fake = FakeDLL()
    monkeypatch.setattr(worker.ctypes, "CDLL", lambda path: fake)
    dll_path = tmp_path / "locate-anything.dll"
    model_path = tmp_path / "model.gguf"
    dll_path.write_bytes(b"dll")
    model_path.write_bytes(b"model")

    runtime = worker._LocateAnythingDLL(str(dll_path), str(model_path))
    runtime.prepare_path("one.png")
    runtime.prepare_path("two.png")
    runtime.clear()

    assert fake.prepare_calls == [os.path.abspath("one.png"), os.path.abspath("two.png")]
    assert fake.clear_calls == 2


def test_dll_runtime_prepares_raw_rgb_without_file_ipc(monkeypatch, tmp_path):
    worker = load_worker("theia_cpp_dll_rgb")
    fake = FakeDLL()
    monkeypatch.setattr(worker.ctypes, "CDLL", lambda path: fake)
    dll_path = tmp_path / "locate-anything.dll"
    model_path = tmp_path / "model.gguf"
    dll_path.write_bytes(b"dll")
    model_path.write_bytes(b"model")

    runtime = worker._LocateAnythingDLL(str(dll_path), str(model_path))
    rgb = bytes([10, 20, 30] * 4)
    runtime.prepare_rgb(rgb, width=2, height=2, stride=6, signature=("fixture", 1))
    runtime.prepare_rgb(rgb, width=2, height=2, stride=6, signature=("fixture", 1))

    assert fake.prepare_rgb_calls == [(2, 2, 6, rgb)]
    assert fake.prepare_calls == []
    assert runtime.prepared_source == "rgb"


def test_cpp_detector_prefers_dll_and_falls_back_to_cli(monkeypatch, tmp_path):
    worker = load_worker("theia_cpp_detector_selection")
    dll_calls = []
    cli_calls = []

    class Runtime:
        def prepare_path(self, image_path):
            dll_calls.append(("prepare", image_path))

        def locate_prepared(self, prompt, mode, max_new_tokens=32):
            dll_calls.append(("locate", prompt, mode, max_new_tokens))
            return {"detections": [{"label": "Save icon", "box": [1, 2, 3, 4]}]}

    monkeypatch.setattr(worker, "_get_cpp_dll_runtime", lambda model_path: Runtime())
    monkeypatch.setattr(worker, "_cpp_detect_cli", lambda *args, **kwargs: cli_calls.append((args, kwargs)) or {"status": "found"})

    from PIL import Image
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    result = worker._cpp_detect(str(image_path), "Save icon", "hybrid", "model.gguf", "cli.exe")

    assert result["runtime"] == "dll"
    assert dll_calls
    assert cli_calls == []

    monkeypatch.setattr(worker, "_get_cpp_dll_runtime", lambda model_path: None)
    fallback = worker._cpp_detect(str(image_path), "Save icon", "hybrid", "model.gguf", "cli.exe")

    assert fallback["status"] == "found"
    assert cli_calls


def test_cpp_detector_prepares_cached_stage_as_raw_rgb(monkeypatch):
    worker = load_worker("theia_cpp_raw_stage")
    calls = []

    class Runtime:
        def prepare_rgb(self, rgb, *, width, height, stride, signature):
            calls.append(("prepare_rgb", len(rgb), width, height, stride, signature))

        def locate_prepared(self, prompt, mode, max_new_tokens=32):
            calls.append(("locate", prompt, mode, max_new_tokens))
            return {"detections": [{"label": "Save", "box": [1, 2, 3, 4]}]}

    monkeypatch.setattr(worker, "_get_cpp_dll_runtime", lambda model_path: Runtime())
    monkeypatch.setattr(
        worker,
        "_cpp_detect_cli",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("raw DLL path must not use CLI/file IPC")),
    )
    image = Image.new("RGB", (20, 10), "white")

    result = worker._cpp_detect_image(
        image,
        "Save",
        "hybrid",
        "model.gguf",
        "cli.exe",
        max_new_tokens=32,
        signature=("stage", 1),
    )

    assert result["runtime"] == "dll"
    assert result["image_transport"] == "raw_rgb"
    assert calls[0] == ("prepare_rgb", 600, 20, 10, 60, ("stage", 1))


def test_cpp_warm_keeps_the_native_engine_resident(monkeypatch):
    worker = load_worker("theia_cpp_warm_dll")

    class Runtime:
        dll_path = "locate_anything.dll"
        abi_version = 3
        _prepare_rgb = object()

    monkeypatch.setenv("COMPUTER_USE_LOCATE_BACKEND", "cpp")
    monkeypatch.setattr(worker.os.path, "exists", lambda path: True)
    monkeypatch.setattr(worker, "_get_cpp_dll_runtime", lambda model_path: Runtime())

    result = worker._handle({"action": "warm", "request_id": "warm-1"})

    assert result["status"] == "loaded"
    assert result["runtime"] == "dll"
    assert result["persistent"] is True
    assert result["abi_version"] == 3
    assert result["raw_rgb"] is True
    assert result["request_id"] == "warm-1"


def test_dll_runtime_rejects_wrong_abi(monkeypatch, tmp_path):
    worker = load_worker("theia_cpp_dll_bad_abi")
    fake = FakeDLL()
    fake.la_capi_abi_version = FakeFn(lambda: 1)
    monkeypatch.setattr(worker.ctypes, "CDLL", lambda path: fake)
    dll_path = tmp_path / "locate-anything.dll"
    model_path = tmp_path / "model.gguf"
    dll_path.write_bytes(b"dll")
    model_path.write_bytes(b"model")

    try:
        worker._LocateAnythingDLL(str(dll_path), str(model_path))
    except RuntimeError as exc:
        assert "ABI 1" in str(exc)
    else:
        raise AssertionError("wrong ABI must be rejected")


def test_multi_separator_preserves_and_inside_category():
    worker = load_worker("theia_cpp_prompt_categories")
    prompt = worker._prompt("Save and close</c>Cancel", "multi", "box", for_cpp=True)
    assert "Save and close</c>Cancel" in prompt

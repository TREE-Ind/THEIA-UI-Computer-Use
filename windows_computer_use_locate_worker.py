"""External LocateAnything worker for windows_computer_use.

Runs in a separate Python interpreter so CUDA Torch can live outside the Hermes
runtime venv. Protocol: JSON stdin/stdout, or newline-delimited JSON with
``--server``. No installs, no Hermes imports, no mutation of caller env.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_MODEL = None
_PROCESSOR = None
_TOK = None
_TORCH = None
_DEVICE = None
_MODEL_ID = None
_DTYPE_NAME = None


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
    return {"x": max(0, min(width, int(x))), "y": max(0, min(height, int(y)))}


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


def _prompt(description: str, task: str, output_type: str) -> str:
    task = (task or "gui").lower()
    output_type = (output_type or "box").lower()
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


def _handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action", "locate")
    if action == "warm":
        return _load(device=payload.get("device"), model_id=payload.get("model_id"), dtype_name=payload.get("dtype"))
    if action == "probe":
        try:
            import torch
            return {"status": "ok", "backend": "external", "python": sys.executable, "torch": torch.__version__, "cuda_available": bool(torch.cuda.is_available()), "cuda_version": getattr(torch.version, "cuda", None)}
        except Exception as exc:
            return {"status": "error", "backend": "external", "python": sys.executable, "error": str(exc)}
    if action == "locate":
        return _locate(payload)
    if action == "shutdown":
        return {"status": "ok", "backend": "external", "action": "shutdown"}
    return {"status": "error", "backend": "external", "error": f"unknown action {action!r}"}


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
                _json({"status": "error", "backend": "external", "error": str(exc), "python": sys.executable})
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

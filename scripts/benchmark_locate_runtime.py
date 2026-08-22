#!/usr/bin/env python
"""Standalone LocateAnything worker performance and coordinate-parity benchmark.

The worker is started only by :func:`main`; importing this module has no side
effects and never launches a process.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Sequence


class Target(NamedTuple):
    id: str
    description: str


class WorkerServer:
    """Small synchronous client for the worker's newline-delimited JSON server."""

    def __init__(
        self,
        worker_python: str,
        worker_script: str,
        *,
        popen_factory: Any = subprocess.Popen,
    ) -> None:
        self.worker_python = worker_python
        self.worker_script = worker_script
        self._popen_factory = popen_factory
        self._process: Any = None
        self._request_number = 0
        self.startup_ms: float | None = None

    def start(self) -> "WorkerServer":
        if self._process is not None:
            return self
        started = time.perf_counter()
        self._process = self._popen_factory(
            [self.worker_python, self.worker_script, "--server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.startup_ms = round((time.perf_counter() - started) * 1000, 3)
        return self

    def request(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        if self._process is None:
            raise RuntimeError("worker server has not been started")
        if self._process.poll() is not None:
            raise RuntimeError(f"worker server exited with code {self._process.poll()}")
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("worker server pipes are unavailable")

        self._request_number += 1
        request_id = str(payload.get("request_id") or f"bench-{self._request_number:06d}")
        request = {**payload, "request_id": request_id}
        started = time.perf_counter()
        self._process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self._process.stdin.flush()
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"worker server closed stdout (exit={self._process.poll()})")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            response_id = response.get("request_id")
            if response_id is not None and str(response_id) != request_id:
                continue
            wall_ms = (time.perf_counter() - started) * 1000
            return response, round(wall_ms, 3)

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                self.request({"action": "shutdown"})
                process.wait(timeout=5)
        except Exception:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
        finally:
            self._process = None

    def __enter__(self) -> "WorkerServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def query_nvidia_smi(*, runner: Any = subprocess.run) -> dict[str, Any]:
    """Return GPU/VRAM data, or an unavailable record instead of failing."""
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = runner(command, capture_output=True, text=True, timeout=10)
        if completed.returncode != 0:
            reason = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
            return {"available": False, "reason": reason}
        gpus: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            fields = [field.strip() for field in line.split(",", 3)]
            if len(fields) != 4:
                continue
            gpus.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "memory_total_mib": int(fields[2]),
                    "memory_used_mib": int(fields[3]),
                }
            )
        if not gpus:
            return {"available": False, "reason": "nvidia-smi returned no parseable GPUs"}
        return {"available": True, "gpus": gpus}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def parse_targets(values: Sequence[str]) -> list[Target]:
    """Parse repeated ``id=description`` values and reject ambiguous labels."""
    targets: list[Target] = []
    seen: set[str] = set()
    for value in values:
        target_id, separator, description = value.partition("=")
        target_id = target_id.strip()
        description = description.strip()
        if not separator or not target_id or not description:
            raise ValueError(f"target must use non-empty id=description syntax: {value!r}")
        if target_id in seen:
            raise ValueError(f"duplicate target id: {target_id}")
        seen.add(target_id)
        targets.append(Target(target_id, description))
    if not targets:
        raise ValueError("at least one --target id=description is required")
    return targets


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Benchmark LocateAnything through its persistent JSONL --server protocol."
    )
    parser.add_argument("--worker-python", default=sys.executable)
    parser.add_argument(
        "--worker-script",
        default=str(root / "windows_computer_use_locate_worker.py"),
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--target", dest="targets", action="append", required=True, metavar="ID=DESCRIPTION")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--baseline")
    parser.add_argument(
        "--write-baseline",
        nargs="?",
        const="__USE_BASELINE_PATH__",
        metavar="PATH",
        help="Write parity coordinates (uses --baseline path when PATH is omitted).",
    )
    parser.add_argument("--backend", default="cpp")
    parser.add_argument("--refine", action="store_true", help="Also benchmark the refine strategy.")
    parser.add_argument("--parity-tolerance", "--tolerance", dest="parity_tolerance", type=int, default=0)
    parser.add_argument("--output", help="Also write the full JSON report to this path.")
    return parser


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _timing_stats(values: Sequence[float]) -> dict[str, float | None]:
    return {"p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)}


def _coordinate(response: dict[str, Any]) -> dict[str, int] | None:
    point = response.get("center")
    if not point and response.get("points"):
        point = response["points"][0]
    if point and "x" in point and "y" in point:
        return {"x": int(round(float(point["x"]))), "y": int(round(float(point["y"])))}
    box = response.get("box")
    if not box and response.get("boxes"):
        box = response["boxes"][0]
    if box and all(key in box for key in ("x1", "y1", "x2", "y2")):
        return {
            "x": int((round(float(box["x1"])) + round(float(box["x2"]))) // 2),
            "y": int((round(float(box["y1"])) + round(float(box["y2"]))) // 2),
        }
    return None


def _sample(response: dict[str, Any], wall_ms: float, *, target_id: str | None = None) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "wall_ms": round(float(wall_ms), 3),
        "status": response.get("status"),
        "worker_timing": response.get("timing"),
    }
    if target_id is not None:
        sample["target_id"] = target_id
    coordinate = _coordinate(response)
    if coordinate is not None:
        sample["coordinate"] = coordinate
    if response.get("error"):
        sample["error"] = response["error"]
    return sample


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    wall_values = [float(sample["wall_ms"]) for sample in samples]
    worker_values = [
        float(sample["worker_timing"]["total_ms"])
        for sample in samples
        if isinstance(sample.get("worker_timing"), dict)
        and isinstance(sample["worker_timing"].get("total_ms"), (int, float))
    ]
    return {
        "count": len(samples),
        "wall_ms": _timing_stats(wall_values),
        "worker_total_ms": _timing_stats(worker_values),
        "samples": samples,
    }


def _locate_payload(target: Target, image_path: str, backend: str, strategy: str = "direct") -> dict[str, Any]:
    return {
        "action": "locate",
        "image_path": image_path,
        "description": target.description,
        "backend": backend,
        "task": "gui",
        "output_type": "point",
        "strategy": strategy,
    }


def _model_from_response(response: dict[str, Any]) -> str | None:
    model = response.get("model") or response.get("model_id")
    if model:
        return str(model)
    load = response.get("load")
    if isinstance(load, dict) and load.get("model"):
        return str(load["model"])
    return None


def run_benchmark(
    worker: Any,
    *,
    targets: Sequence[Target],
    image_path: str,
    image_size: tuple[int, int],
    runs: int,
    backend: str,
    include_refine: bool = False,
    gpu_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all benchmark phases against an already-started JSONL worker client."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    if not targets:
        raise ValueError("at least one target is required")

    observed_responses: list[dict[str, Any]] = []
    final_coordinates: dict[str, dict[str, int]] = {}

    def locate(target: Target, strategy: str = "direct") -> tuple[dict[str, Any], dict[str, Any]]:
        response, wall_ms = worker.request(_locate_payload(target, image_path, backend, strategy))
        observed_responses.append(response)
        sample = _sample(response, wall_ms, target_id=target.id)
        coordinate = sample.get("coordinate")
        if strategy == "direct" and coordinate is not None:
            final_coordinates[target.id] = coordinate
        return response, sample

    _, cold_sample = locate(targets[0])
    _, first_warm_sample = locate(targets[0])

    steady_targets: dict[str, Any] = {}
    for target in targets:
        samples = [locate(target)[1] for _ in range(runs)]
        steady_targets[target.id] = _summarize(samples)

    pair_samples: list[dict[str, Any]] = []
    if len(targets) >= 2:
        for _ in range(runs):
            requests = [locate(targets[0])[1], locate(targets[1])[1]]
            worker_timings = [sample.get("worker_timing") for sample in requests]
            worker_total = sum(
                float(timing["total_ms"])
                for timing in worker_timings
                if isinstance(timing, dict) and isinstance(timing.get("total_ms"), (int, float))
            )
            pair_samples.append(
                {
                    "wall_ms": round(sum(float(sample["wall_ms"]) for sample in requests), 3),
                    "worker_timing": {"total_ms": round(worker_total, 3), "requests": worker_timings},
                    "requests": requests,
                }
            )

    batch_samples: list[dict[str, Any]] = []
    batch_supported = len(targets) >= 2
    batch_reason: str | None = None
    if batch_supported:
        batch_payload = {
            "action": "locate_batch",
            "image_path": image_path,
            "targets": [{"id": target.id, "description": target.description} for target in targets],
            "backend": backend,
            "task": "multi",
            "output_type": "point",
            "strategy": "direct",
            "generation_mode": "fast",
        }
        for _ in range(runs):
            response, wall_ms = worker.request(batch_payload.copy())
            observed_responses.append(response)
            if response.get("status") == "error" and any(
                marker in str(response.get("error", "")).lower()
                for marker in ("unknown action", "unsupported", "not implemented")
            ):
                batch_supported = False
                batch_reason = str(response.get("error"))
                batch_samples = []
                break
            batch_samples.append(_sample(response, wall_ms))
    else:
        batch_reason = "requires at least two targets"

    refine_targets: dict[str, Any] | None = None
    if include_refine:
        refine_targets = {}
        for target in targets:
            refine_targets[target.id] = _summarize([locate(target, "refine")[1] for _ in range(runs)])

    actual_backend = next((str(response["backend"]) for response in observed_responses if response.get("backend")), backend)
    model = next((value for response in observed_responses if (value := _model_from_response(response))), None)
    image_width, image_height = image_size
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "image": {"path": image_path, "width": int(image_width), "height": int(image_height)},
        "environment": {
            "process_mode": "persistent_jsonl_server",
            "backend": actual_backend,
            "model": model,
            "nvidia_smi": gpu_info or {"available": False, "reason": "not queried"},
        },
        "configuration": {"runs": runs, "refine": include_refine},
        "benchmarks": {
            "cold": _summarize([cold_sample]),
            "first_warm": _summarize([first_warm_sample]),
            "steady_state_direct": {"targets": steady_targets},
            "two_independent_same_image": _summarize(pair_samples),
            "multi_pbd_batch": {
                "supported": batch_supported,
                "reason": batch_reason,
                **_summarize(batch_samples),
            },
        },
        "parity_snapshot": {
            "schema_version": 1,
            "image": {"width": int(image_width), "height": int(image_height)},
            "targets": {
                target.id: {"label": target.description, "coordinate": final_coordinates.get(target.id)}
                for target in targets
            },
        },
    }
    if refine_targets is not None:
        report["benchmarks"]["refine"] = {"targets": refine_targets}
    return report


def compare_parity(
    current: dict[str, Any], baseline: dict[str, Any], *, tolerance: int
) -> dict[str, Any]:
    """Compare target labels and final pixel coordinates against a baseline."""
    if tolerance < 0:
        raise ValueError("parity tolerance must be non-negative")
    current_snapshot = current.get("parity_snapshot", current)
    baseline_snapshot = baseline.get("parity_snapshot", baseline)
    current_targets = current_snapshot.get("targets", {})
    baseline_targets = baseline_snapshot.get("targets", {})
    mismatches: list[dict[str, Any]] = []

    for target_id in sorted(set(current_targets) | set(baseline_targets)):
        actual = current_targets.get(target_id)
        expected = baseline_targets.get(target_id)
        if expected is None:
            mismatches.append({"target_id": target_id, "kind": "unexpected_target"})
            continue
        if actual is None:
            mismatches.append({"target_id": target_id, "kind": "missing_target"})
            continue
        if actual.get("label") != expected.get("label"):
            mismatches.append(
                {
                    "target_id": target_id,
                    "kind": "label",
                    "expected": expected.get("label"),
                    "actual": actual.get("label"),
                }
            )
        actual_coordinate = actual.get("coordinate")
        expected_coordinate = expected.get("coordinate")
        if actual_coordinate is None or expected_coordinate is None:
            if actual_coordinate != expected_coordinate:
                mismatches.append(
                    {
                        "target_id": target_id,
                        "kind": "missing_coordinate",
                        "expected": expected_coordinate,
                        "actual": actual_coordinate,
                    }
                )
            continue
        actual_xy = {axis: int(actual_coordinate[axis]) for axis in ("x", "y")}
        expected_xy = {axis: int(expected_coordinate[axis]) for axis in ("x", "y")}
        delta = {axis: abs(actual_xy[axis] - expected_xy[axis]) for axis in ("x", "y")}
        if max(delta.values()) > tolerance:
            mismatches.append(
                {
                    "target_id": target_id,
                    "kind": "coordinate",
                    "expected": expected_xy,
                    "actual": actual_xy,
                    "delta_px": delta,
                }
            )

    return {
        "status": "failed" if mismatches else "passed",
        "tolerance_px": tolerance,
        "mismatches": mismatches,
    }


def parity_exit_code(parity: dict[str, Any]) -> int:
    return 2 if parity.get("status") == "failed" else 0


def image_dimensions(path: str | Path) -> tuple[int, int]:
    """Read image dimensions without importing Pillow during module import."""
    from PIL import Image

    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _write_json(path: str | Path, value: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        targets = parse_targets(args.targets)
        if args.runs < 1:
            raise ValueError("--runs must be at least 1")
        if args.parity_tolerance < 0:
            raise ValueError("--parity-tolerance must be non-negative")
        image_path = str(Path(args.image).resolve())
        if not Path(image_path).is_file():
            raise ValueError(f"image not found: {image_path}")
        size = image_dimensions(image_path)
        gpu_info = query_nvidia_smi()

        worker = WorkerServer(args.worker_python, args.worker_script)
        with worker:
            report = run_benchmark(
                worker,
                targets=targets,
                image_path=image_path,
                image_size=size,
                runs=args.runs,
                backend=args.backend,
                include_refine=args.refine,
                gpu_info=gpu_info,
            )
        report["environment"].update(
            {
                "worker_python": args.worker_python,
                "worker_script": str(Path(args.worker_script).resolve()),
                "process_startup_ms": worker.startup_ms,
            }
        )

        if args.baseline:
            baseline = _read_json(args.baseline)
            report["parity"] = compare_parity(
                report["parity_snapshot"], baseline, tolerance=args.parity_tolerance
            )
        else:
            report["parity"] = {
                "status": "not_checked",
                "tolerance_px": args.parity_tolerance,
                "mismatches": [],
            }

        if args.write_baseline:
            baseline_path = args.write_baseline
            if baseline_path == "__USE_BASELINE_PATH__":
                if not args.baseline:
                    raise ValueError("--write-baseline without PATH requires --baseline PATH")
                baseline_path = args.baseline
            _write_json(baseline_path, report["parity_snapshot"])
            report["baseline_written"] = str(Path(baseline_path).resolve())

        if args.output:
            _write_json(args.output, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return parity_exit_code(report["parity"])
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

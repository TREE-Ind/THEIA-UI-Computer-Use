"""Local real-CUDA transport parity smoke; no GUI actions or cloud requests."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import windows_computer_use as ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--description', default='Firefox three horizontal lines browser menu button at upper right')
    args = parser.parse_args()
    report = {}
    ui.SCRATCH_DIR = Path(args.report).resolve().parent
    ui.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        report['warm'] = ui._warm(backend='cpp', device='cuda')
        shot = ui._capture_screen(scope='active_window')
        report['capture'] = shot
        targets = [{'id': 'menu', 'description': args.description}]
        options = dict(targets=targets, image_path=shot['image_path'], backend='cpp', device='cuda',
                       mode='exact', max_side=1024, max_new_tokens=32, generation_mode='hybrid',
                       strategy='direct', output_type='point')
        report['shared_first'] = ui._locate_batch(**options)
        report['shared_repeat'] = ui._locate_batch(**options)
        ui._CAPTURE_RGB_REGISTRY.clear()
        report['png_reference'] = ui._locate_batch(**options)
        def coordinates(result):
            return [(t.get('status'), t.get('center'), t.get('box')) for t in result.get('targets', [])]
        report['coordinate_parity'] = coordinates(report['shared_first']) == coordinates(report['png_reference'])
        report['capture_timings'] = []
        for materialize in (True, False):
            for _ in range(3):
                started = time.perf_counter()
                frame = ui._capture_screen(scope='active_window', _materialize=materialize)
                report['capture_timings'].append({'materialized': materialize,
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
                    'capture_region': frame['capture_region']})
        options['image_path'] = frame['image_path']
        report['memory_only'] = ui._locate_batch(**options)
        report['memory_path_absent'] = not Path(frame['image_path']).exists()
        report['verified'] = (report['memory_path_absent'] and
            report['memory_only'].get('capture_transport') == 'shared_rgb' and
            report['memory_only'].get('status') == 'found' and report['coordinate_parity'] and
            report['shared_first'].get('capture_transport') == 'shared_rgb' and
            all(t.get('status') == 'found' and t.get('runtime') == 'dll'
                for t in report['shared_first'].get('targets', [])) and
            bool(report['shared_first'].get('targets')))
    finally:
        with ui._EXTERNAL_WORKER_CALL_LOCK:
            ui._dispose_external_worker_locked()
        Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())

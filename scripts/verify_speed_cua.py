"""Read-only live CUA adapter probe against a test-owned public window; no GPU engine.
Run with installed Hermes Python, PYTHONPATH/PYTHONHOME unset. Writes report under plugin.
"""
import concurrent.futures
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import windows_computer_use as ui
import speed_accessibility as ax


def main():
    import tkinter as tk
    root = tk.Tk()
    root.title('THEIA Public Speed Fixture')
    root.geometry('600x400+80+80')
    root.configure(background='white')
    tk.Label(root, text='THEIA PUBLIC READ ONLY FIXTURE', background='white').pack(pady=30)
    tk.Button(root, text='Details panel button').pack()
    dynamic = tk.Label(root, text='Public content A', background='white')
    dynamic.place(x=100, y=250)
    ui.SCRATCH_DIR = ROOT / 'artifacts' / 'public-fixture'
    ui.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    root.update()
    root.lift()
    root.focus_force()
    root.update()
    # Exercise actual registered handler after direct plugin integration import.
    class Context:
        def __init__(self): self.tools = {}
        def register_tool(self, **kw): self.tools[kw['name']] = kw
    ctx = Context()
    ui.register_tools(ctx)
    started = time.monotonic()
    report = {'driver_command':ax.discover_driver_command(), 'new_tools_registered': sorted(
        name for name in ctx.tools if name in {'computer_use_accessibility_candidates',
        'computer_use_prefetch_frame','computer_use_track_regions','computer_use_verify_target'}),
        'default_adapter_class':type(ax.installed_backend()).__name__}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ctx.tools['computer_use_accessibility_candidates']['handler'],
                                 {'window':'THEIA Public Speed Fixture'})
            deadline = time.monotonic()+45
            while not future.done() and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            report['accessibility'] = json.loads(future.result(timeout=2))
        def call(name, args): return json.loads(ctx.tools[name]['handler'](args))
        def public_capture():
            active = ui._active_window()
            if not active or active.get('title') != 'THEIA Public Speed Fixture':
                raise RuntimeError('fixture lost foreground; refusing private capture')
            return call('computer_use_capture_screen', {'scope':'active_window'})
        first = public_capture()
        w,h=first['width'],first['height']
        regions={'toolbar':[0,0,w,180], 'content':[0,200,w,h-200]}
        report['regions_initial']=call('computer_use_track_regions', {'image_path':first['image_path'],
                                      'regions':regions, 'tracker_id':'live-public'})
        dynamic.configure(text='Public content B - updated')
        root.update()
        second = public_capture()
        report['regions_changed']=call('computer_use_track_regions', {'image_path':second['image_path'],
                                      'regions':regions, 'tracker_id':'live-public'})
        report['prefetch_opt_out']=call('computer_use_prefetch_frame', {'opt_in':False})
        report['semantic_wrong_window']=call('computer_use_verify_target', {
            'target':{'id':'done','description':'Details heading'},'window':'THEIA Missing Fixture'})
        report['duration_ms'] = round((time.monotonic()-started)*1000,3)
        report['gpu_engines_started'] = 0
        report['private_window_captured'] = False
    finally:
        root.destroy()
    target = ROOT / 'artifacts' / 'speed-live-cua.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['accessibility'].get('status') == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())

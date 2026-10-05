"""Existing daemon AX-only public fixture probe: no screenshots or GPU calls."""
import sys,json,time,concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import speed_accessibility as ax
import windows_computer_use as ui

def main():
    import tkinter as tk
    root=tk.Tk(); root.title('THEIA Public AX Contract Fixture')
    tk.Label(root,text='Public AX fixture').pack()
    tk.Button(root,text='Details public button').pack()
    root.update(); root.lift(); root.focus_force(); root.update()
    active=ui._active_window()
    if not active or active['title']!='THEIA Public AX Contract Fixture':
        root.destroy(); raise RuntimeError('public fixture not active')
    backend=ax.installed_backend()
    report={'transport_args':backend.transport_args,'driver':backend.command,'screenshot_requested':False}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            def probe():
                args=dict(pid=active['process_id'],window_id=active['handle'],include_screenshot=False,max_elements=200)
                raw=backend.call_tool('get_window_state',args)
                # Record contract shape only, never value/markdown.
                report['structured_keys']=sorted(raw)
                report['element_keys']=[sorted(e) for e in raw.get('elements',[])]
                report['coordinate_space']=raw.get('coordinate_space')
                report['candidate_result']=ax.AccessibilityAdapter(backend).candidates(pid=active['process_id'],window_id=active['handle'],opt_in=True,public_context=True)
                report['persistent_proxy_reused']=backend.thread.is_alive()
            future=pool.submit(probe)
            while not future.done(): root.update(); time.sleep(.01)
            future.result()
    finally:
        backend.close(); root.destroy()
    target=ROOT/'artifacts'/'speed-ax-daemon-contract.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    assert report['candidate_result']['status']=='ok'

if __name__=='__main__': main()

"""Read-only installed native CUA API smoke; NOT a GUI speed benchmark."""
import sys, json, time, concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import speed_accessibility as ax
import windows_computer_use as ui
import tkinter as tk
from tools.computer_use.cua_backend import sanitized_cua_driver_env
from tools.environments.local import _sanitize_subprocess_env

def main():
    env=_sanitize_subprocess_env(sanitized_cua_driver_env())
    report={'native_api':'installed cua-driver MCP over existing daemon', 'benchmark':False,
            'sanitizer_provider_secret_absent':'OPENAI_API_KEY' not in env,
            'telemetry_defaults':{k:env.get(k) for k in ('CUA_DRIVER_RS_TELEMETRY_ENABLED',)}}
    root=tk.Tk(); root.title('THEIA Safety Review Public Fixture')
    tk.Label(root,text='Public fixture only').pack()
    tk.Button(root,text='Public details').pack()
    root.update(); root.lift(); root.focus_force(); root.update()
    active=ui._active_window()
    backend=None
    try:
        if not active or active.get('title')!='THEIA Safety Review Public Fixture':
            raise RuntimeError('fixture not active; no API read attempted')
        backend=ax.installed_backend()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(ax.AccessibilityAdapter(backend).candidates,pid=active['process_id'],
                               window_id=active['handle'],opt_in=True,public_context=True)
            while not future.done(): root.update(); time.sleep(.01)
            result=future.result()
            report['candidate_status']=result['status']
            report['code']=result.get('code')
            report['candidate_count']=len(result.get('candidates',[]))
            report['snapshot_provenance_verified']=all(c.get('snapshot_id')==result.get('snapshot_id') and
                c.get('id_provenance')=='snapshot_local_element_index' for c in result.get('candidates',[]))
            report['screenshot_requested']=result.get('screenshot_requested')
            report['pixels_exported']=result.get('pixels_exported')
            report['required_schema']=getattr(backend,'contract_schema',{}).get('required')
            report['schema_properties']=sorted(getattr(backend,'contract_schema',{}).get('properties',{}))
            future=pool.submit(ax.AccessibilityAdapter(backend).candidates,pid=active['process_id'],
                               window_id=active['handle'],opt_in=True,public_context=True)
            while not future.done(): root.update(); time.sleep(.01)
            report['second_call_status']=future.result()['status']
            report['persistent_proxy_reused']=backend.thread.is_alive()
    finally:
        if backend:
            backend.close()
            report['proxy_closed']=not backend.thread.is_alive()
        root.destroy()
    (ROOT/'artifacts'/'speed-safety-native-api.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    assert report['candidate_status']=='ok' and report['second_call_status']=='ok' and report['proxy_closed']
if __name__=='__main__': main()

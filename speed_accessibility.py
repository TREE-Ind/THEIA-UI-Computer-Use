"""Installed SDK daemon proxy only; no acquisition, private UIA, or runtime ownership.
Installed Hermes backend lacks public transport override; start() acquires packages.
"""
import threading
import math
import re

class ContractError(RuntimeError): pass

class AdapterError(RuntimeError):
    """Allowlisted transport verdict; raw exceptions never leave the adapter."""
    CODES = {'cua_daemon_transport_unavailable', 'cua_transport_quarantined', 'cua_transport_lock_timeout'}

    def __init__(self, code):
        self.code = code if code in self.CODES else 'cua_daemon_transport_unavailable'
        super().__init__(self.code)

def structured_result(result):
    raw=result.model_dump(by_alias=True)
    if raw.get('isError') or any(c.get('type')=='image' for c in raw.get('content',[])):
        raise ContractError('cua_driver_contract_error_or_unexpected_image')
    if not isinstance(raw.get('structuredContent'),dict):
        raise ContractError('cua_structured_contract_missing')
    return raw['structuredContent']

class AccessibilityAdapter:
    def __init__(self, backend):
        self.backend=backend
        self.lock=threading.Lock()

    def candidates(self, *, pid, window_id, opt_in=False, public_context=False):
        def error(code):
            return dict(status='blocked',code=code,retryable=False,next_step='inspect_existing_daemon_contract_no_auto_install_or_restart')
        if opt_in is not True or public_context is not True: return error('public_context_opt_in_required')
        if type(pid) is not int or type(window_id) is not int or min(pid,window_id)<=0: return error('invalid_window_identity')
        try:
            with self.lock:
                raw=self.backend.call_tool('get_window_state',dict(pid=pid,window_id=window_id,include_screenshot=False,max_elements=200))
        except ContractError: return error('cua_structured_contract_invalid')
        except AdapterError as exc: return error(exc.code)
        except Exception: return error('cua_daemon_transport_unavailable')
        if not isinstance(raw,dict) or not isinstance(raw.get('elements'),list): return error('cua_structured_contract_invalid')
        snapshot = raw.get('snapshot_id')
        if (raw.get('pid') != pid or raw.get('window_id') != window_id or
                not isinstance(snapshot, str) or not re.fullmatch(r's[0-9a-fA-F]{8,64}', snapshot)):
            return error('cua_structured_contract_invalid')
        candidates=[]
        seen=set()
        geometryless_elements_omitted=0
        for e in raw['elements'][:200]:
            if not isinstance(e,dict): return error('cua_structured_contract_invalid')
            if e.get('pid',pid)!=pid or e.get('window_id',window_id)!=window_id: continue
            index = e.get('element_index')
            if (type(index) is not int or index < 0 or index in seen or
                    e.get('element_token') != f'{snapshot}:{index}'):
                return error('cua_structured_contract_invalid')
            seen.add(index)
            # Installed Firefox snapshots include structural nodes with NO frame.
            # Omit those nodes, never invent bounds or weaken malformed-frame checks.
            if 'frame' not in e:
                geometryless_elements_omitted += 1
                continue
            frame=e['frame']
            if (not isinstance(frame,dict) or
                    not all(type(frame.get(k)) in (int,float) and -2**31 <= frame[k] < 2**31
                            and math.isfinite(frame[k]) for k in ('x','y','w','h')) or
                    frame['w'] < 0 or frame['h'] < 0):
                return error('cua_structured_contract_invalid')
            candidates.append(dict(id=str(e.get('element_index')),label=e.get('label',''),role=e.get('role'),
                bounds=[frame[k] for k in ('x','y','w','h')],enabled=e.get('enabled'),selected=e.get('selected'),
                pid=pid,window_id=window_id,element_token=e.get('element_token'),snapshot_id=snapshot,
                id_provenance='snapshot_local_element_index',source='installed_cua_daemon_structured',
                coordinate_space=raw.get('coordinate_space','driver_unmapped'),coordinate_provenance='driver_reported_no_transform',visual_validation_required=True))
        return dict(status='ok',candidates=candidates,geometryless_elements_omitted=geometryless_elements_omitted,snapshot_id=snapshot,walk_limit=200,may_be_truncated=raw.get('total_element_count',len(raw['elements']))>=200,screenshot_requested=False,pixels_exported=False)

def discover_driver_command():
    import os
    import shutil
    from pathlib import Path
    explicit = os.getenv('HERMES_CUA_DRIVER_CMD')
    if explicit:
        return explicit
    found = shutil.which('cua-driver')
    if found:
        return found
    # Windows installs can ship an extensionless PE, omitted by shutil.which/PATHEXT.
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        candidate = Path(directory.strip('"')) / 'cua-driver'
        if candidate.is_file():
            return str(candidate)
    return None


class InstalledDaemonBackend:
    """Persistent public MCP SDK stdio proxy to the existing standard daemon."""
    def __init__(self, command):
        self.command=command
        self.transport_args=['mcp','--socket',r'\\.\pipe\cua-driver']
        self.thread=None
        self.ready=threading.Event()
        self.failure=None
        self.session=None
        self.lock=threading.Lock()

    def _run(self):
        import asyncio
        async def main():
            self.loop=asyncio.get_running_loop()
            self.closed=asyncio.Event()
            self.task=asyncio.current_task()
            try:
                if self.failure:
                    return
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                from tools.computer_use.cua_backend import sanitized_cua_driver_env
                # Core currently suppresses sanitizer import errors and falls back to
                # inherited env. Require and reapply the sanitizer: never that fallback.
                from tools.environments.local import _sanitize_subprocess_env
                env = _sanitize_subprocess_env(sanitized_cua_driver_env())
                if not isinstance(env, dict):
                    raise RuntimeError('cua_environment_sanitizer_unavailable')
                env.pop('PYTHONPATH', None)
                env.pop('PYTHONHOME', None)
                async with stdio_client(StdioServerParameters(command=self.command,args=self.transport_args,env=env)) as (r,w):
                    async with ClientSession(r,w) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        tools = [t.model_dump(by_alias=True) for t in listing.tools]
                        matches = [t for t in tools if t.get('name') == 'get_window_state']
                        if len(matches) != 1:
                            raise ContractError('cua_read_only_schema_missing')
                        schema = matches[0].get('inputSchema', {})
                        properties = schema.get('properties', {})
                        required = schema.get('required', [])
                        expected = {'pid':'integer', 'window_id':'integer',
                                    'include_screenshot':'boolean', 'max_elements':'integer'}
                        if (schema.get('type') != 'object' or
                                not {'pid','window_id'} <= set(required) <= set(expected) or
                                any(properties.get(k, {}).get('type') != v for k,v in expected.items()) or
                                any('enum' in properties[k] and value not in properties[k]['enum']
                                    or 'const' in properties[k] and properties[k]['const'] != value
                                    for k,value in {'include_screenshot':False,'max_elements':200}.items()) or
                                properties['max_elements'].get('minimum', 1) > 200 or
                                properties['max_elements'].get('maximum', 200) < 200):
                            raise ContractError('cua_read_only_schema_invalid')
                        self.contract_schema = schema
                        self.session=session
                        self.ready.set()
                        await self.closed.wait()
            except asyncio.CancelledError:
                self.failure=self.failure or 'transport_closed'
            except Exception as exc:
                self.failure=self.failure or type(exc).__name__
            finally:
                self.session=None
                self.ready.set()
        asyncio.run(main())

    def call_tool(self, name, args, *, timeout=15):
        import asyncio, time
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ContractError('cua_invalid_timeout')
        deadline=time.monotonic()+timeout
        if name!='get_window_state' or args.get('include_screenshot') is not False: raise ContractError('cua_read_only_contract_violation')
        if not self.lock.acquire(timeout=max(0,deadline-time.monotonic())): raise AdapterError('cua_transport_lock_timeout')
        try:
            if self.failure: raise AdapterError('cua_transport_quarantined')
            if self.thread is None:
                self.thread=threading.Thread(target=self._run,daemon=True,name='theia-cua-proxy')
                self.thread.start()
            if not self.ready.wait(max(0,deadline-time.monotonic())) or self.failure or self.session is None:
                self.failure=self.failure or 'initialize_timeout'
                self._request_close(cancel=True)
                raise AdapterError('cua_daemon_transport_unavailable')
            future=asyncio.run_coroutine_threadsafe(self.session.call_tool(name,args),self.loop)
            try: result=future.result(timeout=max(0,deadline-time.monotonic()))
            except Exception:
                self.failure='call_failed'
                future.cancel()
                self._request_close(cancel=True)
                raise AdapterError('cua_daemon_transport_unavailable') from None
            return structured_result(result)
        finally: self.lock.release()

    def _request_close(self, cancel=False):
        loop = getattr(self,'loop',None)
        if loop is None or loop.is_closed():
            return
        def signal():
            self.closed.set()
            task = getattr(self,'task',None)
            if cancel and task is not None and not task.done():
                task.cancel()
        try:
            loop.call_soon_threadsafe(signal)
        except RuntimeError:
            pass  # loop completed between is_closed and signal

    def close(self):
        self.failure=self.failure or 'transport_closed'
        self._request_close(cancel=True)
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(3)


def installed_backend():
    import importlib.util
    if importlib.util.find_spec('mcp') is None: raise RuntimeError('cua_sdk_not_installed_no_acquisition')
    command=discover_driver_command()
    if not command: raise RuntimeError('cua_driver_not_installed_no_acquisition')
    return InstalledDaemonBackend(command)

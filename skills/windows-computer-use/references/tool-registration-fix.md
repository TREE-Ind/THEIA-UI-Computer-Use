# Tool registration repair notes

This reference records the module/package shadowing and upgrade-loss patterns we have hit when making Windows desktop automation work as a registered Hermes toolset.

## Symptoms
- Hermes emits: `Warning: Unknown toolsets: windows_computer_use`
- Tool is absent from the enable/disable toggle list after an upgrade.
- Registry discovery shows the expected tool count but the toolset name is missing or rejected.

## Root cause patterns
- Updating Hermes can remove manual edits in `tools/` and configurators.
- A `tools/windows_computer_use.py` shim can coexist with a `tools/windows_computer_use/` package. That breaks imports because Python resolves one form and silently skips the other. Keep exactly one form.
- Registry tool-name shadowing rejects duplicate registration attempts under different toolsets.
- Hermes auto-discovery uses an AST gate: `tools/*.py` must contain direct top-level `registry.register(...)` calls. Calls nested under `if`, functions, loops, or aliases like `_registry.register(...)` are skipped.
- Import the registry object, not the module: use `from tools.registry import registry`, then call `registry.register(...)`. `from tools import registry` imports the `tools.registry` module, which has no module-level `register` function and causes discovery-time import failures.

Additional runtime blockers found in desktop sessions:
- The desktop stack may launch both `.../hermes-agent/venv/Scripts/python.exe` and `C:/Python311/python.exe` slash-worker/dashboard subprocesses. Install/check Windows computer-use dependencies in both runtimes, not only the shell's default `python`.
- If logs say `Could not import tool module tools.windows_computer_use: Missing Windows desktop control dependency: No module named 'pyautogui'`, schemas will not be exposed and the agent will say it cannot use the toolset.
- LocateAnything-3B needs the model stack in the runtime that executes tools: `torch`, `transformers==4.57.1`, `peft`, `accelerate`, `sentencepiece`, `lmdb`, `decord`, `hf_xet`, `opencv-python` (`cv2`), and `torchvision` matching the installed `torch`.
- Both `AutoProcessor.from_pretrained(...)` and `AutoModel.from_pretrained(...)` need `trust_remote_code=True` for `nvidia/LocateAnything-3B`.

Verification contract:
- No `tools/windows_computer_use/` package directory exists when using the flat `tools/windows_computer_use.py` module.
- `python -m py_compile tools/windows_computer_use.py` passes.
- `tools.registry._module_registers_tools(Path('tools/windows_computer_use.py'))` returns `True`.
- `tools.registry.discover_builtin_tools()` returns `tools.windows_computer_use`.
- `model_tools.get_tool_definitions(enabled_toolsets=['windows_computer_use'])` emits all expected `computer_use_*` schemas.
- In every Python runtime used by desktop/slash workers, importing `pyautogui`, `PIL`, `torch`, `torchvision`, `cv2`, `transformers`, and `peft` succeeds.
- `model_tools.handle_function_call('computer_use_warm', {}, enabled_toolsets=['windows_computer_use'], skip_pre_tool_call_hook=True)` returns `{"status": "loaded", "device": ...}`.
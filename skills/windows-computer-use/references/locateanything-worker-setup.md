# LocateAnything Worker Setup

THEIA uses LocateAnything visual grounding by default for natural-language UI
targeting. Basic mouse/keyboard/screenshot tools remain available as the fallback
while the worker installs or if visual grounding is unavailable.

## Isolation rule

Do not install CUDA PyTorch into the live Hermes environment. THEIA creates an
isolated worker venv so Hermes still runs if ML dependencies break.

## Automatic setup

On plugin load, THEIA starts a best-effort background bootstrap unless
`THEIA_AUTO_INSTALL_LOCATE_WORKER=false` is set. The bootstrap uses:

```powershell
python .\scripts\setup_locate_worker.py --torch auto
```

Default worker location:

- Windows: `%LOCALAPPDATA%\hermes\theia-ui-computer-use\locate-worker\.venv`
- macOS/Linux: `$HERMES_HOME/theia-ui-computer-use/locate-worker/.venv`

The toolset auto-discovers that interpreter. Set `COMPUTER_USE_LOCATE_PYTHON`
only when you manage a custom worker venv yourself.

## Manual repair / eager install

From the plugin repo:

```powershell
python .\scripts\setup_locate_worker.py --torch auto
python .\scripts\doctor.py --install-locate --locate
```

Torch selection:

- `auto` — default; CUDA 12.1 when `nvidia-smi` exists, CPU/default otherwise
- `cpu` — force CPU wheels where applicable
- `cu121`, `cu124`, `cu126` — force a CUDA wheel index
- `default` — use PyPI/default platform wheels
- `skip` — install non-torch LocateAnything deps only

## Warm and test

Inside Hermes:

```text
computer_use_warm()
computer_use_capture_screen()
computer_use_locate(description="the Start button", output_type="point")
```

Expected behavior:

- First calls may report `status=installing` while the worker venv is being built.
- Persistent worker calls should be faster after warmup.
- If the worker fails, basic action tools should still remain available.

## Good defaults

For UI clicking:

```text
output_type="point"
strategy="direct"
prompt_style="direct"
max_side=640
max_new_tokens=32
generation_mode="hybrid"
do_sample=false
```

Use `output_type="box"` or refinement strategies only when you need region bounds
or the direct point is unreliable.

## Failure handling

If locate fails:

1. Capture a fresh screenshot.
2. Use a clearer description with visible label + app context.
3. Try a smaller region screenshot.
4. If the worker reports `installing`, wait or use basic coordinate/pixel tools.
5. Fall back to manual coordinates only when safe.
6. Report that visual grounding is unavailable if the worker/dependencies are broken.

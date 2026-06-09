# THEIA Computer Use installed

**THEIA — The Human Environment Intelligence Aperture** is installed.

Next steps:

```powershell
hermes plugins enable hermes-windows-computer-use
hermes tools enable windows_computer_use
python scripts/doctor.py
```

Restart Hermes after enabling the plugin/toolset.

## Basic dependencies

Current Hermes Agent plugin installs read THEIA's `pip_dependencies` metadata
from `plugin.yaml` and install the lightweight basic dependencies into the
Python environment currently running Hermes Agent. THEIA also keeps a
best-effort first-load fallback for older Hermes builds or blocked installs.

This covers the basic desktop-control stack: PyAutoGUI, Pillow, PyGetWindow,
and pywin32 on Windows only. LocateAnything is also bootstrapped automatically
into an isolated worker venv outside Hermes. Set
`THEIA_AUTO_INSTALL_BASIC_DEPS=false` or
`THEIA_AUTO_INSTALL_LOCATE_WORKER=false` to disable automatic dependency setup
in audited or air-gapped environments.

If auto-install is disabled or blocked, run:

```powershell
python scripts/doctor.py --install-basic
```

## Optional visual grounding

For LocateAnything/CUDA, use the isolated worker installer. This intentionally
keeps heavy ML packages out of the live Hermes environment:

```powershell
.\scripts\install_locate_worker.ps1 -Python C:\Python312\python.exe -Cuda cu121
```

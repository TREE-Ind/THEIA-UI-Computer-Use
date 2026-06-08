# Windows Computer Use installed

Next steps:

```powershell
hermes plugins enable hermes-windows-computer-use
hermes tools enable windows_computer_use
python scripts/doctor.py
```

Restart Hermes after enabling the plugin/toolset.

For visual grounding/CUDA, use the isolated worker installer:

```powershell
.\scripts\install_locate_worker.ps1 -Python C:\Python312\python.exe -Cuda cu121
```

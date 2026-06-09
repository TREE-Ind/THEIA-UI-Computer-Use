# Fresh Install Checklist

Use this after the plugin has just been installed and before attempting real desktop work.

## 1. Confirm the plugin is installed and enabled

```powershell
hermes plugins list --plain --no-bundled
hermes tools list | findstr /i windows_computer_use
```

Expected signs:

- `hermes-windows-computer-use` appears as enabled.
- `windows_computer_use` appears in the tools list.

If the toolset was just enabled, restart Hermes or the gateway before continuing:

```powershell
hermes gateway restart
```

For CLI sessions, exit and relaunch Hermes.

## 2. Confirm basic Python dependencies

From the plugin directory:

```powershell
python scripts/doctor.py
```

Expected signs:

- OS is Windows, macOS, or Linux with a usable GUI session.
- `plugin.yaml`, `__init__.py`, tool module, and worker exist.
- Tool registration reports 20+ tools.
- `pyautogui`, `PIL`, and `pygetwindow` import.
- Mouse position can be read.

If basic dependencies are missing:

```powershell
python -m pip install -r requirements-basic.txt
```

## 3. Start with dry-run if the user is unsure

Use dry-run for first contact on an unfamiliar machine:

```text
computer_use_set_dry_run(true)
computer_use_capture_screen()
computer_use_get_active_window()
```

Switch to live mode only after the user expects real mouse/keyboard actions:

```text
computer_use_set_dry_run(false)
```

## 4. Run the minimal live smoke test

Only after the user approves live control:

1. Capture the screen.
2. Get active window.
3. Move the mouse a tiny safe distance or click an inert area.
4. Capture again.
5. Report what changed.

Do not use destructive keyboard shortcuts or click unknown dialogs during smoke tests.

## 5. Decide whether LocateAnything is needed

Basic mode can operate by coordinates, windows, pixels, and screenshots. Use LocateAnything when you need natural-language visual grounding like:

- “Click the blue Save button.”
- “Find the search box.”
- “Locate the timeline playhead.”

If LocateAnything is not installed, basic desktop automation can still work. The locate tools should return a clear JSON error instead of hiding the whole toolset.

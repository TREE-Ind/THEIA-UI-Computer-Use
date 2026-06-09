# Troubleshooting

## Plugin installed but toolset missing

Run:

```powershell
hermes plugins list --plain --no-bundled
hermes tools list
```

Fix checklist:

1. Enable the plugin:
   ```powershell
   hermes plugins enable hermes-windows-computer-use
   ```
2. Enable the toolset:
   ```powershell
   hermes tools enable windows_computer_use
   ```
3. Restart Hermes/gateway:
   ```powershell
   hermes gateway restart
   ```
4. Start a new session. Tool changes do not apply mid-conversation.

## Basic dependencies missing

From the plugin repo:

```powershell
python -m pip install -r requirements-basic.txt
python scripts/doctor.py
```

## LocateAnything unavailable

This should not hide the whole toolset. Only locate/find-click should fail gracefully.

Fix checklist:

1. Confirm external worker env vars.
2. Confirm worker Python exists.
3. Run the worker installer.
4. Restart Hermes after environment changes.
5. Try `computer_use_warm(backend="external")`.

## Mouse/keyboard actions do nothing

Check:

- Is dry-run enabled?
- Is the target app active and visible?
- Is the machine locked, minimized, or on a secure desktop prompt?
- Are coordinates on screen?
- Is another modal intercepting input?

Use:

```text
computer_use_set_dry_run(false)
computer_use_get_active_window()
computer_use_capture_screen()
```

## Wrong thing clicked

Do not repeat immediately. Instead:

1. Capture the current screen.
2. Verify active window.
3. Use a more specific locate description.
4. Consider region-constrained capture/locate.
5. Use `output_type="box"` if the target area matters.

## Stuck mouse button or modifier key

Always recover with:

```text
computer_use_release_all()
```

Then capture again before continuing.

## Plugin development pitfall

Do not create both a flat module and a package directory with the same name, such as:

```text
tools/windows_computer_use.py
tools/windows_computer_use/__init__.py
```

Python may import the package first and skip the flat module registration side effects. The plugin repo uses a root plugin entrypoint plus sibling module to avoid this.

# Blender UI object insertion workflow

Use this when the user asks to operate Blender via UI-based Windows computer use rather than scripts, Python console, or terminal automation.

## Pattern

1. Open Blender visually:
   - Try `computer_use_open_app({"command":"Blender 4.3"})` or the requested version.
   - If it does not visibly surface Blender, use the Windows Start/Search UI: `Win`, type the Blender version/name, then `Enter`.
   - Verify with `computer_use_capture_screen` / active window title, e.g. `Blender 4.3.x`.
2. Remove the default cube when the target is a clean simple object scene:
   - With the default cube selected, press `x`, then `Enter` to confirm deletion.
3. Add a sphere using Blender UI search:
   - Press `F3` to open Blender operator search.
   - Type `uv sphere`.
   - Press `Enter` to run the Add Mesh: UV Sphere operator.
4. Verify visually:
   - Capture the screen.
   - Prefer `computer_use_locate` with a description like `the sphere object in the Blender 3D viewport`.
   - Report the visual confirmation and, if available, the located center/box.

## Pitfalls

- Do not use Blender Python, terminal commands, or file edits when the user explicitly requests UI-based computer use.
- `computer_use_open_app` can return success before the app is visible; always re-capture and verify the active window before manipulating Blender.
- If a transient blank/no-title active window appears while Blender starts, wait/re-capture instead of assuming failure.

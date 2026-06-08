# Hermes Windows Computer Use Plugin

A self-contained Hermes Agent plugin that adds a `windows_computer_use`
toolset for Windows desktop automation: screenshots, window focus, mouse,
keyboard, drag/scroll gestures, pixel checks, and optional LocateAnything-3B
visual UI grounding.

## What it unlocks

Hermes can operate GUI software the way a human does: see the screen, pick a
target, click/type/drag/scroll, verify what changed, and repeat. This is most
useful when there is no clean API, no browser automation hook, or the workflow
crosses multiple desktop applications.

## Install from GitHub

Once this repo is published:

```powershell
hermes plugins install owner/hermes-windows-computer-use --enable
hermes tools enable windows_computer_use
hermes skills list
```

Restart Hermes or the gateway after enabling:

```powershell
hermes gateway restart
```

> During local development you can install from a local git remote/path if
> your Hermes build supports it, or clone this repo directly into
> `%LOCALAPPDATA%\hermes\plugins\hermes-windows-computer-use`.

## Dependency modes

### Basic mode

Basic mode supports screenshots and live mouse/keyboard actions. Install the
lightweight dependencies into the Python environment that runs Hermes:

```powershell
python -m pip install -r requirements-basic.txt
```

### LocateAnything mode

Visual grounding is intentionally isolated. Do **not** force CUDA PyTorch into
the live Hermes venv. Create an external worker venv instead:

```powershell
.\scripts\install_locate_worker.ps1 -Python C:\Python312\python.exe -Cuda cu121
```

Then set:

```powershell
setx COMPUTER_USE_LOCATE_BACKEND external
setx COMPUTER_USE_LOCATE_PYTHON "$env:LOCALAPPDATA\hermes\windows-computer-use\.venv\Scripts\python.exe"
setx COMPUTER_USE_LOCATE_PERSISTENT true
```

Start a new Hermes session after changing environment variables.

## Toolset

The plugin registers these tools under the `windows_computer_use` toolset:

- `computer_use_capture_screen`
- `computer_use_warm`
- `computer_use_locate`
- `computer_use_find_click`
- `computer_use_move`, `computer_use_click`, `computer_use_double_click`
- `computer_use_type`, `computer_use_press`, `computer_use_hotkey`
- `computer_use_scroll`, `computer_use_drag`, `computer_use_drag_path`
- `computer_use_mouse_down`, `computer_use_mouse_up`, `computer_use_release_all`
- `computer_use_pixel`, `computer_use_pixel_matches`
- `computer_use_open_app`, `computer_use_focus_window`, `computer_use_get_active_window`
- `computer_use_set_dry_run`

## Canonical agent workflow

1. Open/focus the app.
2. Capture the screen.
3. Locate or find-click the target.
4. Act with mouse/keyboard primitives.
5. Verify the result with a new capture, active-window check, or pixel check.
6. Repeat until done.

## Safety notes

- PyAutoGUI is live by default unless `COMPUTER_USE_DRY_RUN=true`.
- Always pair `mouse_down` with `mouse_up`, or call `release_all` if interrupted.
- Coordinate-taking tools validate that points are on-screen.
- Broken LocateAnything/CUDA dependencies should not hide the basic toolset.

## Doctor

Run:

```powershell
python .\scripts\doctor.py
```

Optional LocateAnything check:

```powershell
python .\scripts\doctor.py --locate
```

## Skill documentation

The plugin bundles `skills/windows-computer-use/SKILL.md` and reference docs.
On plugin load, it copies the skill into the active Hermes profile only if the
skill does not already exist. Existing user-customized skill docs are not
overwritten.

To force-install the bundled skill:

```powershell
python .\scripts\install_skill.py --force
```

## Critical packaging pitfall

Keep this plugin as a plugin directory with root `__init__.py`; do not install
a separate `tools/windows_computer_use/` package beside a flat
`tools/windows_computer_use.py` file. In Hermes' built-in tool discovery, that
package-shadowing pattern can prevent tool registration.

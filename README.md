# THEIA Computer Use

**THEIA — The Human Environment Intelligence Aperture**

A self-contained UI computer-use plugin that gives **Hermes Agent** a visual
perception and control layer for Windows, macOS, and Linux: screenshots,
window focus, mouse, keyboard, drag/scroll gestures, pixel checks, and optional
LocateAnything-3B
visual UI grounding.

![THEIA Computer Use infographic](assets/windows-computer-use-infographic.png)

## What it unlocks

THEIA lets **Hermes Agent** operate GUI software the way a human does: see the
screen, perceive the interface, pick a target, click/type/drag/scroll, verify
what changed, and repeat. This is most useful when there is no clean API, no
browser automation hook, or the workflow crosses multiple desktop applications.

> **See the interface. Understand the environment. Act through the screen.**

## How THEIA works with Hermes Agent

Hermes Agent already has language reasoning, tool calling, skills, memory,
file access, terminal access, web research, scheduled jobs, subagents, and
optional messaging-platform access. THEIA adds the missing **visual interface
aperture**: a way for Hermes Agent to perceive and operate normal desktop
software through the same screen a human uses.

In practice, THEIA contributes two things:

1. **A UI computer-use toolset** — screenshot capture, active-window checks,
   visual locating, mouse/keyboard actions, drag/scroll gestures, pixels, and
   dry-run controls.
2. **A bundled operator skill** — reusable guidance that teaches Hermes Agent
   the safe loop for GUI work: `see → target → act → verify → repeat`.

That means Hermes Agent can combine normal agent capabilities with desktop UI
control. For example:

| Hermes Agent capability | What THEIA adds | Combined result |
|---|---|---|
| Reasoning + planning | Screen perception and UI actions | Break a messy desktop workflow into verified steps |
| Skills | Fresh-install UI operation guidance | Reuse safer GUI workflows across sessions |
| Memory | User/app preferences | Remember preferred apps, workflows, and guardrails |
| File tools | GUI export/import verification | Create or edit files, then confirm them in desktop apps |
| Terminal tools | Dependency checks and local scripts | Install/diagnose prerequisites, then operate the UI |
| Web/browser tools | Existing logged-in browser sessions | Use APIs/browser automation where possible, screen control where needed |
| Cron jobs | Scheduled UI checks/actions | Run recurring local workflows that require a visible app |
| Subagents | Parallel research/planning | Let one agent plan while another operates the desktop |

THEIA is most valuable in the "messy middle" where APIs stop helping: legacy
software, creative tools, vendor dashboards, admin consoles, apps with no SDK,
local-only utilities, and workflows that cross several windows.

## Example workflows

### Operate software with no API

Hermes Agent can use THEIA to open an app, inspect the screen, find the right
button or field, act, and verify the result. This is useful for internal tools,
legacy enterprise apps, installers, desktop utilities, and line-of-business
software that only exposes a GUI.

### Use the user's already-logged-in apps

If the user is already logged into a browser, dashboard, or desktop app, Hermes
Agent can work in that existing session instead of asking for new credentials or
requiring an API token. The agent can focus the window, navigate, click, type,
and verify visible outcomes.

### Combine research with UI execution

Hermes Agent can research instructions or documentation with web tools, write a
step-by-step plan, then use THEIA to carry out the GUI portions on the desktop.
For example: read setup docs, open an installer, choose options, verify the app
launches, and save a summary.

### Turn one-off UI work into reusable skills

After Hermes Agent successfully completes a complex GUI workflow, it can save a
skill describing the reliable steps and pitfalls. THEIA provides the screen
interaction layer; Hermes Agent's skill system turns the experience into a
repeatable operating procedure.

### Verify outcomes instead of trusting clicks

THEIA encourages Hermes Agent to prove each milestone: capture a fresh
screenshot, check the active window, inspect a pixel/toggle state, or verify an
output file. This makes GUI automation less brittle than blind click scripts.

## Private UI computer use

THEIA can be used for **completely private local UI computer use** when paired
with a local/private Hermes Agent setup.

The plugin itself runs on the desktop machine and controls the local desktop
with local Python libraries such as PyAutoGUI and Pillow. Basic mode does not
require cloud visual grounding, remote browser sessions, or third-party UI
automation services.

For private operation:

1. Run Hermes Agent locally on the Windows, macOS, or Linux machine.
2. Use a local or private model/provider for Hermes Agent if prompts and screen
   descriptions must stay private.
3. Keep THEIA in **basic mode** for local screenshots, mouse, keyboard, window,
   pixel, and verification tools.
4. If visual grounding is needed, run LocateAnything through the isolated local
   worker instead of a hosted vision service.
5. Disable toolsets you do not want in the session, such as web, browser,
   image generation, or messaging tools.
6. Avoid sending screenshots or sensitive UI text to cloud models unless your
   chosen model/provider and policies allow it.

Useful privacy-oriented commands:

```powershell
hermes tools enable windows_computer_use
hermes tools disable web
hermes tools disable browser
hermes tools disable image_gen
hermes tools disable messaging
```

Then start a fresh Hermes Agent session so tool changes take effect.

For maximum privacy, use:

- a local Hermes Agent profile,
- local/private model inference,
- THEIA basic mode or local external LocateAnything worker,
- no web/browser/messaging toolsets unless explicitly needed,
- dry-run mode for demonstrations or audits before live control.

```text
computer_use_set_dry_run(true)   # inspect intended actions without acting
computer_use_set_dry_run(false)  # enable live local desktop control
```

## Install from GitHub

```powershell
hermes plugins install https://github.com/TREE-Ind/THEIA-UI-Computer-Use.git --enable
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

### Basic mode: automatic during plugin install

Basic mode supports screenshots, active-window checks, pixel checks, and live
mouse/keyboard actions.

Current Hermes Agent plugin installs read THEIA's `pip_dependencies` metadata
from `plugin.yaml` and/or the top-level `requirements.txt`, then install the
lightweight basic dependencies into the Python environment currently running
Hermes Agent. THEIA also keeps a small
best-effort dependency check on first plugin load as a fallback for older Hermes
Agent builds or blocked installs.

Installed automatically when missing:

- `pyautogui`
- `pillow`
- `pygetwindow`
- `python3-xlib` on Linux only
- `pywin32` on Windows only

Opt out for audited or air-gapped environments:

```powershell
setx THEIA_AUTO_INSTALL_BASIC_DEPS false
```

Manual fallback from the installed plugin directory:

```powershell
python -m pip install -r requirements.txt
```

### LocateAnything mode: automatic, default, and isolated

THEIA uses LocateAnything visual grounding as the default path for
`computer_use_locate` and `computer_use_find_click`. Basic coordinate, pixel,
mouse, and keyboard tools remain available as the fallback while visual
grounding is installing or unavailable.

The heavy visual-grounding stack is **not** installed into the live Hermes venv.
On plugin load, THEIA starts a best-effort background bootstrap that creates an
isolated worker venv and installs LocateAnything dependencies there. The toolset
auto-discovers that worker when it is ready.

Default worker location:

- Windows: `%LOCALAPPDATA%\hermes\theia-ui-computer-use\locate-worker\.venv`
- macOS/Linux: `$HERMES_HOME/theia-ui-computer-use/locate-worker/.venv`

Manual repair or eager install from the plugin directory:

```powershell
python .\scripts\setup_locate_worker.py --torch auto
python .\scripts\doctor.py --install-locate --locate
```

Torch install policy is controlled by `THEIA_LOCATE_TORCH`:

- `auto` — default; CUDA 12.1 wheel when `nvidia-smi` is available, CPU/default otherwise
- `cpu` — force PyTorch CPU wheels where applicable
- `cu121`, `cu124`, `cu126` — force a CUDA wheel index
- `default` — use PyPI/default platform wheels
- `skip` — install non-torch LocateAnything deps only

Opt out for audited, air-gapped, or manually managed environments:

```powershell
setx THEIA_AUTO_INSTALL_LOCATE_WORKER false
```

If you already manage a worker venv yourself, set `COMPUTER_USE_LOCATE_PYTHON`
to that interpreter. `COMPUTER_USE_LOCATE_BACKEND` defaults to `auto`, which
prefers the isolated worker and falls back only when needed.

## Toolset

The stable toolset id remains `windows_computer_use` for compatibility,
but the PyAutoGUI-backed basic controls support Windows, macOS, and Linux. The
plugin registers these tools:

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
3. Locate or find-click the target with LocateAnything visual grounding.
4. If LocateAnything is still installing/unavailable, fall back to basic coordinate/pixel primitives.
5. Act with mouse/keyboard primitives.
6. Verify the result with a new capture, active-window check, or pixel check.
7. Repeat until done.

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

If automatic basic dependency installation was disabled or blocked, repair it
manually with:

```powershell
python .\scripts\doctor.py --install-basic
```

LocateAnything worker install/status check:

```powershell
python .\scripts\doctor.py --install-locate --locate
```

## Skill documentation

The plugin officially registers the bundled skill through `ctx.register_skill`,
so Hermes exposes it as a plugin skill. It also copies
`skills/theia-ui-computer-use/SKILL.md` into the active profile as a
compatibility convenience only if the skill does not already exist. Existing user-customized skill docs are not
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

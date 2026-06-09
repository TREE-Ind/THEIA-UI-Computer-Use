---
name: windows-computer-use
description: |
  THEIA — The Human Environment Intelligence Aperture. Cross-platform UI perception
  and computer use: capture the screen, locate UI elements, click, type, drag,
  scroll, verify state, and optionally use LocateAnything-3B visual grounding.
version: 1.1.0
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [desktop, computer-use, gui, visual, windows, macos, linux]
    category: desktop
    related_skills: [hermes-agent]
---

# THEIA Computer Use

**THEIA — The Human Environment Intelligence Aperture**

Use this skill when an agent needs visual perception and control of the
desktop through the `windows_computer_use` toolset installed by the
`hermes-windows-computer-use` plugin.

This skill is written for fresh installs and normal end users. It focuses on
safe, repeatable GUI operation: see the interface, understand the environment,
act through the screen, and verify the result.

## Core rule

Use registered `windows_computer_use` tools. Do not run ad-hoc desktop-control
scripts from the terminal when the toolset is available.

## Canonical workflow

Use the loop below for almost every desktop task:

```text
see → target → act → verify → repeat
```

1. **See:** `computer_use_capture_screen()` and, when useful,
   `computer_use_get_active_window()`.
2. **Target:** use `computer_use_locate()` for a point/box or
   `computer_use_find_click()` for simple low-risk locate+click.
3. **Act:** click, type, press, hotkey, scroll, or drag with the smallest useful
   action.
4. **Verify:** capture again, check active window, inspect a pixel/state, locate
   the expected result, or verify the created file/output.
5. **Repeat:** base the next action on the new screen, not stale assumptions.

Prefer `computer_use_locate` / `computer_use_find_click` over generic
`vision_analyze` for interactive desktop control. Use generic image analysis
only when the desktop toolset is unavailable or when the task is purely visual
understanding, not controlling the desktop.

## Tool quick reference

| Need | Tools |
|---|---|
| Capture/inspect | `computer_use_capture_screen`, `computer_use_get_active_window`, `computer_use_pixel`, `computer_use_pixel_matches` |
| Visual targeting | `computer_use_locate`, `computer_use_find_click`, `computer_use_warm` |
| Mouse | `computer_use_move`, `computer_use_click`, `computer_use_double_click`, `computer_use_scroll` |
| Drag/hold | `computer_use_drag`, `computer_use_drag_relative`, `computer_use_drag_path`, `computer_use_mouse_down`, `computer_use_mouse_up`, `computer_use_release_all` |
| Keyboard | `computer_use_type`, `computer_use_press`, `computer_use_hotkey`, `computer_use_key_down`, `computer_use_key_up` |
| Apps/windows | `computer_use_open_app`, `computer_use_focus_window` |
| Safety/config | `computer_use_set_dry_run`, `computer_use_release_all` |

## Fresh-install references

Load these references as needed:

- `references/fresh-install-checklist.md` — verify plugin/tool/dependency readiness.
- `references/agent-operating-loop.md` — detailed see→target→act→verify loop.
- `references/targeting-and-clicking.md` — locating UI elements and clicking safely.
- `references/text-keyboard-shortcuts.md` — typing, shortcuts, and modifier-key patterns.
- `references/gestures-drag-scroll.md` — sliders, timelines, drawing, scrolling, and drag paths.
- `references/verification-and-safety.md` — evidence, dry-run, and destructive-action guardrails.
- `references/locateanything-worker-setup.md` — optional external worker setup and defaults.
- `references/troubleshooting.md` — common post-install and runtime failures.
- `references/starter-workflows.md` — simple app/browser/search/toggle workflows.

## Safety defaults

- Start with dry-run if the user is evaluating the plugin on a new machine.
- Switch to live actions only when the user expects real mouse/keyboard control.
- Never click destructive or externally visible actions without clear user intent.
- After interrupted hold/modifier gestures, call `computer_use_release_all()`.
- Do not claim success based only on a click; verify the result.

## LocateAnything guidance

LocateAnything is optional. The basic action layer should work without it.
If visual grounding is needed, prefer an isolated external worker so CUDA/PyTorch
dependencies do not mutate or break the live Hermes runtime.

Good UI-clicking defaults:

```text
backend="external"
output_type="point"
strategy="direct"
prompt_style="direct"
max_side=640
max_new_tokens=32
generation_mode="hybrid"
do_sample=false
```

Use boxes or refinement only when the task needs region bounds or direct point
location is unreliable.

## Verification checklist

Before reporting success:

- [ ] Correct app/window is active or visibly present.
- [ ] The intended target was located or otherwise verified.
- [ ] The action result was checked with a fresh screenshot/window/pixel/output.
- [ ] Any file/output path was verified if the task created or exported something.
- [ ] No held mouse button or modifier key remains active.
- [ ] Any uncertainty is stated plainly instead of hidden.

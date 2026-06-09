# Agent Operating Loop

The safest pattern is:

```text
see → target → act → verify → repeat
```

Do not batch many GUI actions from memory. Desktop state changes constantly.

## Step 1 — See

Capture the full screen or a focused region:

```text
computer_use_capture_screen()
computer_use_capture_screen(region=[x, y, width, height])
```

Also check context:

```text
computer_use_get_active_window()
```

## Step 2 — Target

Choose one targeting method:

| Method | Use when |
|---|---|
| `computer_use_locate` | Need coordinates for a described UI element |
| `computer_use_find_click` | Want locate + click in one step |
| `computer_use_pixel_matches` | Need a cheap color/state check |
| Known coordinates | You just captured and verified the target |
| Active window title | You need to confirm the app/page context |

Prefer `computer_use_locate` / `computer_use_find_click` over generic image analysis for interactive desktop control.

## Step 3 — Act

Use the smallest action that advances the task:

- `computer_use_click`
- `computer_use_double_click`
- `computer_use_type`
- `computer_use_press`
- `computer_use_hotkey`
- `computer_use_scroll`
- `computer_use_drag`

For complex hold gestures, use:

```text
computer_use_mouse_down(...)
computer_use_move(...)
computer_use_mouse_up(...)
```

Always call `computer_use_release_all()` if a hold or modifier sequence is interrupted.

## Step 4 — Verify

After any meaningful action, verify with at least one of:

- New screenshot.
- Active window title.
- Pixel check.
- Locate result for expected new element.
- File existence or app output if the GUI action created something.

Never claim success based only on having clicked.

## Step 5 — Repeat

Use the new screenshot as the source of truth for the next action. If the screen does not match expectations, stop and explain what is visible before continuing.

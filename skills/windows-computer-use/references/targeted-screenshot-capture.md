# Targeted screenshot capture workflow

Use this when the user wants a screenshot of a specific on-screen item or post.

## Workflow

1. Surface the correct window first (`Alt+Tab`, taskbar, or `computer_use_focus_window`).
2. Verify the target is actually visible with `computer_use_capture_screen`.
3. If the target is on screen, invoke the OS snipping overlay (`Win+Shift+S` is the standard path) or the machine's configured printscreen hotkey.
4. Drag a rectangle tightly around the confirmed target area.
5. Capture/inspect the result and, if needed, crop the saved screenshot from the verified full-screen capture.

## Pitfall

Do not snip from stale context. A screenshot command can easily capture Hermes or another foreground app if the browser was not re-verified immediately beforehand.

## Verification

Before reporting success, confirm both:
- the active window title matches the intended app/page, and
- the visible content on screen includes the target item.

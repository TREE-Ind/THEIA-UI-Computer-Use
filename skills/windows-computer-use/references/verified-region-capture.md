# Verified region screenshot workflow

Use this when the user asks for a screenshot of a specific UI element or post inside a desktop app.

## Workflow

1. Confirm the target element is actually visible on screen with `computer_use_capture_screen`.
2. Use `computer_use_locate` / `computer_use_find_click` if needed to ground the target before taking the screenshot.
3. Open the Windows snipping overlay with `Win+Shift+S`.
4. Capture only the target region by dragging a rectangle around the visible element.
5. Re-check the active window or overlay state if the snip appears to have captured the wrong app.
6. If the tool returns a full-screen image instead of the requested region, crop the verified screenshot from the captured desktop image only after confirming the target is on-screen.

## Pitfall

Do not return a screenshot taken from the wrong window just because the target was expected to be there. Verify the active desktop state first, then snip or crop.

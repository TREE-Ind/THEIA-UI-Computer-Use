# Browser handoff example: X search from a Windows desktop session

## Situation

A browser-backed task started from inside Hermes, but the target browser was already open on the Windows desktop behind the app.

## Useful pattern

1. Use `computer_use_get_active_window` / `computer_use_capture_screen` to see what actually has focus.
2. If Hermes is in front of the browser, use `Alt+Tab` or the taskbar to surface the existing Edge window.
3. Use `Ctrl+L` to focus the address bar.
4. Type the target URL with `computer_use_type`.
5. Press `Enter` with `computer_use_hotkey` or `computer_use_press` equivalent in the Windows toolset.
6. Re-capture the screen and confirm the page title / visible content changed.
7. For X, prefer the direct live search URL with `f=live` instead of relying on the in-page search box and tabs after a query has already been entered.
8. If the in-page search box opens a suggestion dropdown, press `Escape` and continue with direct navigation.

## Example from this session

- Opened Edge via the taskbar instead of relying on a separate browser tool.
- Surfaced an existing Edge window with `Alt+Tab`.
- Navigated to:
  `https://x.com/search?q=robotics&src=typed_query&f=live`
- Verified that the page title changed to an X search results page for `robotics` and visible posts included robotics-related mentions.

## Notes

- This is useful when a browser tab already exists in a running desktop session.
- It avoids losing context by launching a duplicate browser window.
- Always verify the target page after navigation; a successful URL entry is not enough.

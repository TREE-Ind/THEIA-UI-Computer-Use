# Starter Workflows

These are generic workflows a freshly installed Hermes agent can use immediately.

## Open an app and verify

1. `computer_use_open_app(command="notepad")`
2. `computer_use_get_active_window()`
3. `computer_use_capture_screen()`
4. Verify Notepad is visible before typing.

## Type into a safe document

1. Open Notepad or another disposable editor.
2. Click the text area or use the active window.
3. `computer_use_type(text="Hello from Hermes")`
4. Capture and verify the text appears.

Do not save or overwrite files unless the user asked.

## Browser navigation with current login session

1. Focus the existing browser if the user says they are logged in.
2. `computer_use_hotkey(keys=["ctrl", "l"])`
3. `computer_use_type(text="https://example.com")`
4. `computer_use_press(keys="Enter")`
5. Verify title/content changed.

## Search inside an app

1. Focus app.
2. Use `Ctrl+F` or locate the search box.
3. Type query.
4. Press Enter if needed.
5. Verify search results, not just that text was typed.

## Toggle a setting

1. Navigate to the relevant settings page.
2. Locate the exact labeled toggle.
3. Click once.
4. Capture the toggle state.
5. Report the final visible state.

If multiple similar toggles exist, do not guess.

## Extract visible information

1. Capture screen or relevant region.
2. Use locate/vision only to understand visible UI.
3. If text is selectable, use keyboard shortcuts to copy only when safe.
4. Verify the copied/observed content before summarizing.

## Use a desktop app with no API

1. Break the task into small UI milestones.
2. For each milestone, use see → target → act → verify.
3. Prefer built-in shortcuts where reliable.
4. Save/export only after verifying destination and filename.
5. Report evidence: visible status, output path, screenshot, or active window.

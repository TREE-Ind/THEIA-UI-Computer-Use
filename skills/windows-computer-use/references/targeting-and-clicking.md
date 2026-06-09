# Targeting and Clicking

Use this when the user asks Hermes to click, select, open, toggle, or press something visible on the desktop.

## Preferred targeting order

1. Focus the correct app or window.
2. Capture the screen.
3. Locate the element by description.
4. Click the returned point.
5. Capture again and verify.

## Focus first

```text
computer_use_focus_window(title="App name")
computer_use_get_active_window()
```

If focus fails, use `computer_use_open_app` or an OS-level shortcut such as `Alt+Tab`, then verify.

## Locate then click

Use `computer_use_locate` when you want to inspect coordinates first:

```text
computer_use_locate(description="the Search box", output_type="point")
computer_use_click(x=..., y=...)
```

Use `computer_use_find_click` for simple, low-risk clicks:

```text
computer_use_find_click(description="the blue Save button")
```

## Ask for boxes when the region matters

Use `output_type="box"` when you need a rectangle for cropping, dragging, or verifying a larger UI area:

```text
computer_use_locate(description="the document preview pane", output_type="box")
```

## Click safety rules

- Do not click unknown modal buttons without reading/verifying the dialog.
- Do not click destructive controls unless the user asked for that exact action.
- Avoid clicking while the app is visibly loading.
- Prefer clicking the center of a located button or field, not the edge.
- If the locate result seems off-screen or implausible, re-capture and retry with a clearer description.

## Good descriptions

Good:

- “the search input field at the top of the Settings window”
- “the blue Export button in the upper right”
- “the checkbox next to Enable captions”

Weak:

- “the thing”
- “button”
- “there”

Include app context, visual label, position, and role when possible.

## Verification examples

After clicking:

- A menu should open → capture and verify menu items are visible.
- A checkbox should toggle → inspect the visible state.
- A link should navigate → verify title/content changed.
- A button should save/export → verify a status message or output file.

# Text Entry and Keyboard Shortcuts

Use keyboard actions when they are safer than mouse targeting, especially for search boxes, dialogs, and app-wide commands.

## Text entry sequence

1. Verify the correct app/window is active.
2. Click or shortcut into the field.
3. Clear existing text if needed.
4. Type.
5. Press Enter/Tab if needed.
6. Verify the result.

Example:

```text
computer_use_hotkey(keys=["ctrl", "l"])
computer_use_type(text="https://example.com")
computer_use_press(keys="Enter")
```

## Common shortcuts

| Goal | Shortcut |
|---|---|
| Select all | `Ctrl+A` |
| Copy | `Ctrl+C` |
| Paste | `Ctrl+V` |
| Cut | `Ctrl+X` |
| Save | `Ctrl+S` |
| Open file | `Ctrl+O` |
| Find/search | `Ctrl+F` |
| Address/location bar | `Ctrl+L` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Y` or `Ctrl+Shift+Z` |
| Close tab/window | `Ctrl+W` or `Alt+F4` |
| Switch windows | `Alt+Tab` |

## Modifier hold pattern

For shortcuts or selections that require a held key:

```text
computer_use_key_down(key="shift")
computer_use_click(x=..., y=...)
computer_use_key_up(key="shift")
```

If anything interrupts the sequence:

```text
computer_use_release_all()
```

## Text safety rules

- Do not type secrets into unknown fields.
- Do not press Enter in a chat/message composer unless the user intended to send.
- Prefer `Ctrl+L` for browser navigation instead of trying to click the address bar.
- In forms, use screenshots to verify the typed value landed in the correct field.
- If a field autocomplete/dropdown appears, press `Escape` before switching tactics.

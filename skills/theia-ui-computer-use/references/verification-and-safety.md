# Verification and Safety

Desktop automation needs explicit verification. The agent should prove outcomes, not just report actions.

## Evidence to collect

Most action results should include evidence like:

- `dry_run`
- before/after mouse position
- active window title
- screenshot path or region
- pixel/color result
- locate confidence/result

If these fields disappear after an upgrade, treat it as a tool regression.

## Verify by task type

| Task | Verification |
|---|---|
| Open an app | active window title + screenshot |
| Click a button | resulting dialog/page/state is visible |
| Toggle setting | the actual toggle state changed |
| Fill a field | the value appears in the intended field |
| Save/export | output file exists or app shows success |
| Navigate webpage | URL/title/content changed |
| Drag/resize | visual position/size changed |

## Use region screenshots

For targeted checks, capture a small region:

```text
computer_use_capture_screen(region=[x, y, width, height])
```

This reduces noise and makes repeated verification easier.

## Destructive action guardrails

Pause and ask the user before:

- Deleting files.
- Sending messages/emails/posts.
- Purchasing/submitting forms.
- Changing security/privacy settings.
- Closing unsaved work.
- Clicking buttons labeled Delete, Remove, Reset, Submit, Send, Purchase, Pay, or Confirm.

## Dry-run mode

Use dry-run when exploring a new machine or demonstrating intended actions:

```text
computer_use_set_dry_run(true)
```

Return to live actions only when intended:

```text
computer_use_set_dry_run(false)
```

## If the screen is unexpected

Stop and report what is visible. Do not invent state or continue blindly.

Good response pattern:

> I expected the Save dialog, but the screen still shows the editor and a modal asking whether to discard changes. I need your confirmation before clicking either option.

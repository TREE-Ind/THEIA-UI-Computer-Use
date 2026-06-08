# Windows computer-use infographic generation

Use this reference when the user asks for a visual explanation, infographic, poster, or shareable overview of the `windows_computer_use` toolset.

## Proven pattern

1. Use the `baoyu-infographic` workflow rather than a plain image prompt.
2. Prefer `dense-modules` + `pop-laboratory` for a technical toolset guide:
   - portrait aspect ratio
   - 6-7 coordinate-labeled modules
   - blueprint/lab grid background
   - teal functional blocks, fluorescent pink warnings, yellow highlights
   - command chips and exact parameter callouts
3. Write source/analysis/structured-content/prompt files under an `infographic/<topic>/` project directory.
4. Generate with the configured image provider, then inspect the result visually before delivering.
5. If the result looks like a generic robot/mascot instead of an infographic, retry with stronger negative requirements: "NOT a decorative illustration", "NOT a single robot mascot", "must include modules, command names, arrows, parameters, warnings, and quick reference strip".
6. Deliver local images as `MEDIA:<absolute path>` instead of Markdown image links when the platform blocks local Windows paths.

## Content blocks that worked well

Title block:
- `WINDOWS COMPUTER USE TOOLSET`
- `Visual UI grounding + live PyAutoGUI actions`
- `Hermes Agent • LocateAnything-3B • PyAutoGUI • Windows`

Seven-module structure:
- A-01 `WHAT IT IS`: `windows_computer_use`, LocateAnything-3B grounds UI, PyAutoGUI executes live actions.
- B-02 `CAPTURE → LOCATE → ACT → VERIFY`: open/focus app, capture screen, locate/find-click, click/type/press/drag/scroll, verify active window or pixels, repeat.
- C-03 `PRIMITIVE MAP`: capture, grounding, mouse, keyboard, gestures, verify/safety command chips.
- D-04 `GROUNDING DEFAULTS`: `output_type=point`, `strategy=direct`, `prompt_style=direct`, `max_side=640`, `max_new_tokens=32`, `generation_mode=hybrid`, `do_sample=false`.
- E-05 `LIVE BY DEFAULT`: PyAutoGUI live execution, dry-run only when explicit, pair `mouse_down` + `mouse_up`, use `release_all` if interrupted, evidence fields.
- F-06 `DON'T BREAK REGISTRATION`: flat module vs shadow package pitfall, CUDA external worker best practice.
- G-07 `REAL APP WORKFLOWS`: Shotcut, Paint, Blender, Microsoft Store, browser handoff.

## Verification checklist

Before final response, inspect the generated image for:
- readable title and subtitle
- multiple labeled modules, not a single mascot
- visible workflow loop
- visible command names
- visible LocateAnything defaults
- visible warning/safety section
- visible registration/CUDA pitfall section
- pop-laboratory visual language (grid, coordinates, teal/pink/yellow, technical labels)

## Delivery checklist

- Copy the final image from the cache into the infographic project directory as `infographic.png`.
- Report layout, style, aspect, model/provider, and created files.
- For Windows local paths, prefer `MEDIA:C:\...\infographic.png` for the image attachment.
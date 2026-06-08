---
name: windows-computer-use
description: |
  Windows desktop automation — locate, click, type, drag, scroll, capture,
  and more — driven visually with LocateAnything-3B and PyAutoGUI.
version: 1.0.0
platforms: [windows]
metadata:
  hermes:
    tags: [windows, desktop, computer-use, gui, visual]
    category: desktop
    related_skills: [browser]
---

# Windows Computer Use

Use this skill when you need to control the Windows desktop visually.

Use registered `windows_computer_use` tools only. Never run `computer_use_cli.py` from the terminal.

## Canonical workflow

1. `computer_use_open_app` / `computer_use_focus_window`
2. `computer_use_capture_screen`
3. `computer_use_locate` or `computer_use_find_click` for Windows UI grounding
4. `computer_use_click` / `computer_use_double_click` / `computer_use_type` /
   `computer_use_press` / `computer_use_hotkey` / `computer_use_scroll` /
   `computer_use_drag` / `computer_use_drag_relative` / `computer_use_drag_path`
5. For complex gestures, use `computer_use_mouse_down` + `computer_use_move`/`computer_use_move_relative` + `computer_use_mouse_up`; call `computer_use_release_all` if a hold gesture is interrupted.
6. Repeat capture/locate as needed; use `computer_use_get_active_window`, `computer_use_pixel`, or `computer_use_pixel_matches` to confirm context/state

Important: for Windows desktop automation, prefer `computer_use_locate` / `computer_use_find_click` over generic `vision_analyze`. Use `vision_analyze` only when the Windows toolset is unavailable or you need non-interactive image understanding that is not tied to desktop control.

## PyAutoGUI gesture capabilities

Use the richer PyAutoGUI primitives when basic click/drag is not enough:

- `computer_use_move` / `computer_use_move_relative`: hover or reposition without clicking.
- `computer_use_mouse_down` / `computer_use_mouse_up`: manual click-and-hold gestures; always pair them or use `computer_use_release_all` for cleanup.
- `computer_use_drag`: absolute held-button drag from A to B.
- `computer_use_drag_relative`: drag from the current cursor position by an offset.
- `computer_use_drag_path`: hold a mouse button and move through multiple points for sliders, selection boxes, drawing, or finicky timeline gestures.
- `computer_use_press`, `computer_use_key_down`, `computer_use_key_up`: repeated keys and modifier-held workflows such as Shift-drag/Ctrl-click. Use `computer_use_release_all` after interrupted modifier/hold sequences.
- `computer_use_pixel` / `computer_use_pixel_matches`: cheap visual verification without invoking LocateAnything.
- `computer_use_capture_screen` supports optional `region=[x, y, width, height]` for focused verification screenshots.

All coordinate-taking action tools should validate coordinates with `pyautogui.onScreen` and return evidence fields (`dry_run`, before/after positions, active window).

## Search-and-open verification

When a click is meant to open a search result or app listing, do not stop at the click. Re-capture the screen and confirm the active window title or visible page content changed to the expected destination before reporting success.

For Windows Settings toggles, verify the actual switch state in the screenshot rather than trusting the window title alone. Some Settings pages expose closely related toggles side by side; confirm the label and the pill state that changed before reporting success. For the Xbox Game Bar page specifically, the top toggle labeled `Allow your controller to open Game Bar` is the one to switch off.

When the user wants a screenshot of a specific post, object, or region, first verify the target is visible on the current screen, then use the OS snipping overlay or printscreen flow to drag a tight rectangle around the confirmed target. Do not snip from stale context. See `references/targeted-screenshot-capture.md`.

For Microsoft Store-style flows, see `references/microsoft-store-search-workflow.md`.
For Shotcut media import and timeline placement, see `references/shotcut-media-import.md`.
For Shotcut export fallback with bundled ffmpeg and input validation, see `references/shotcut-export-ffmpeg-fallback.md`.
For verified region screenshots / post crops, see `references/verified-region-capture.md`.
For a verified Shotcut workflow to add an audio track, see `references/shotcut-audio-track.md`.
For a verified Shotcut workflow to add audio filters such as High Pass to an A1 WAV clip, see `references/shotcut-audio-filters.md`.
For Microsoft Paint drawing workflows, including canvas-size/selection-handle pitfalls and freehand `drag_path` circles, see `references/microsoft-paint-drawing.md`.
For Microsoft Photos image-filter requests, including the direct Pillow edit + backup workflow and the background-removal-tab pitfall, see `references/photos-image-filter-workflow.md`.
For Blender UI-based object insertion, including opening Blender by Start/Search fallback, deleting the default cube, adding a UV sphere with `F3` operator search, and visual verification, see `references/blender-ui-object-add.md`.
For Photopea social-cover work, including the verified FB Page Cover preset path and dimensions, see `references/photopea-facebook-cover-workflow.md`.
For disabling Xbox Game Bar in Windows Settings, see `references/game-bar-disable-workflow.md`.
For Discord desktop search tasks, including avoiding the chat composer and reading search result cards, see `references/discord-search-workflow.md`.
For generating a high-density technical infographic that explains this toolset with GPT Image 2 + `baoyu-infographic`, including prompt structure and verification checklist, see `references/infographic-generation.md`.

## Browser handoff and already-open apps

If the task is a browser-backed desktop flow, prefer the live Windows browser window already on screen instead of opening a second browser instance. If the user says they are already logged into the browser, keep using that session. If focus is lost inside Hermes or another app, use `Alt+Tab`, the taskbar, or `computer_use_focus_window` to surface the existing browser, then use `Ctrl+L` + `computer_use_type` + `Enter` to navigate. Verify success by checking the browser tab title / active window title after navigation.

For X search flows, the direct live URL is often more reliable than clicking around inside the page after typing into the search field:
`https://x.com/search?q=<query>&src=typed_query&f=live`
If the in-page search box opens a suggestions dropdown or otherwise captures input, clear it with `Escape` and fall back to `Ctrl+L` + direct navigation. After load, confirm the `Latest` tab is actually selected before collecting results.

For a worked example of the X search handoff, see `references/browser-handoff-x-search.md`.

## Live backend paths (Windows)

- Hermes runtime: `C:\Users\joshu\AppData\Local\Hermes\hermes-agent\tools\windows_computer_use.py`
- Optional workspace mirror: `C:\Users\joshu\AppData\Local\hermes\hermes-agent\tools\windows_computer_use.py`

Keep exactly ONE backend form. Do not create both `tools/windows_computer_use.py` and `tools/windows_computer_use/__init__.py`.
If a package directory exists, Python imports it first, which silently prevents the flat module from registering tools.

## Runtime behavior and LocateAnything-3B loader

PyAutoGUI execution is live by default. `computer_use_set_dry_run(true)` is only for explicit no-op testing. Action results should include `dry_run`, `before_position`, `after_position`, and `active_window`; missing evidence is a backend regression. On Windows, `computer_use_scroll` should use the native Win32 wheel-event backend by default after restart and report `backend`, `native_sent`, and/or `pyautogui_sent` in its result; if those fields are missing, the running Hermes process has not reloaded the patched module yet.

LocateAnything and PyTorch are loaded lazily by `computer_use_warm`, `computer_use_locate`, and `computer_use_find_click`. Do not modify `sys.path`, force user-site Python packages, run CUDA repair scripts, or mutate the live Hermes runtime/venv from this module or an active agent session. Broken ML dependencies must not prevent the Windows toolset from registering or appearing in `hermes tools list`; the toolset check should only require Windows and individual ML calls should return JSON errors if optional dependencies are unavailable.

CUDA must run via the isolated external worker path when possible, not by changing the Hermes venv. Configure/use:

```text
backend="external"
python="C:\\Python312\\python.exe"
```

or environment variables:

```text
COMPUTER_USE_LOCATE_BACKEND=external
COMPUTER_USE_LOCATE_PYTHON=C:\\Python312\\python.exe
COMPUTER_USE_LOCATE_PERSISTENT=true
COMPUTER_USE_LOCATE_MAX_SIDE=640
COMPUTER_USE_LOCATE_MAX_NEW_TOKENS=32
COMPUTER_USE_LOCATE_GENERATION_MODE=hybrid
COMPUTER_USE_LOCATE_DO_SAMPLE=false
COMPUTER_USE_LOCATE_STRATEGY=direct
COMPUTER_USE_LOCATE_PROMPT_STYLE=direct
```

The external worker is `tools/windows_computer_use_locate_worker.py`; it communicates JSON over stdin/stdout and keeps CUDA Torch isolated from Hermes. Persistent mode keeps the model loaded in a side process. Profiling on this machine showed cold load around 19–32s. For agentic clicking, the measured best default is direct point grounding: `output_type="point"`, `strategy="direct"`, `prompt_style="direct"`, `max_side=640`, `max_new_tokens=32`, `generation_mode="hybrid"`, `do_sample=false`; warm external-CUDA calls are commonly ~0.4–0.6s after the first query, with occasional ~2–3s first-query overhead. Max-side 768/1024 and chat-template mode were slower on Windows UI screenshots; full-screen 1024 was ~29s and 1280 was ~41–45s. Use higher max-side, `output_type="box"`, or `strategy="point_refine"` only explicitly when you need region bounds and can tolerate slower/less stable results.

Use `AutoProcessor`/`AutoModel` with `trust_remote_code=True` on both calls.

```python
from transformers import AutoProcessor, AutoModel
model_id = "nvidia/LocateAnything-3B"
processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
model = AutoModel.from_pretrained(
    model_id,
    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    trust_remote_code=True,
).to(device).eval()
```

LocateAnything processor/generate contract:
- Downscale large screenshots before inference to avoid CPU OOM; scale boxes back to desktop coordinates.
- Prompt must include an image placeholder such as `<image-1>` for the direct processor path. For GUI clicking prefer the LocateAnything point template `Point to: [PHRASE].`; for region bounds use `Locate the region that matches the following description: [PHRASE].`. The model-card chat-template path is available as `prompt_style="chat_template"`, but local profiling found `prompt_style="direct"` faster and more reliable for Windows UI screenshots.
- Pass images as a list: `processor(text=prompt, images=[image], return_tensors="pt")`.
- Call `model.generate(..., tokenizer=processor.tokenizer, use_cache=True, max_new_tokens=int(os.getenv("COMPUTER_USE_LOCATE_MAX_NEW_TOKENS", "32")))`; lower token caps reduce repeated text and improve speed.
- `generate()` returns decoded text directly for this model; only call `batch_decode` if the return value is not a string.
- Parse both plain numeric boxes (`<box>10 20 30 40</box>`) and coordinate-token boxes (`<box><241><956><266><1000></box>`). Coordinate tokens are usually normalized 0..1000.

Required runtime: torch, torchvision, opencv-python, transformers==4.57.1, peft, accelerate, sentencepiece, lmdb, decord, hf_xet, pyautogui, pillow, pygetwindow.

## Tool visibility / session checklist

If `windows_computer_use` shows configured but no `computer_use_*` tools are callable:
1. Quit Hermes fully, including background Electron/system-tray instances
2. Reopen with `hermes desktop`
3. Immediately re-check the tool list before retrying actions

Do not keep retrying the same failing tool path. If the fallback path is not needed immediately, just acknowledge and stop.
For tool registration/repair after Hermes upgrades, see `references/tool-registration-fix.md`.

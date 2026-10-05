---
name: theia-ui-computer-use
description: Use when controlling desktop UIs with THEIA. Prefer persistent C++ LocateAnything, immutable multi-target grounding, and preflighted non-destructive action batches.
version: 2.0.0
author: Hermes Agent + Joshua
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [desktop, computer-use, gui, visual-grounding, locateanything, batching, windows, macos, linux]
    category: desktop
    related_skills: [hermes-agent]
---

# THEIA Computer Use

## Overview

THEIA is the desktop perception-and-control layer provided by the
`hermes-windows-computer-use` plugin. It captures immutable screenshots,
grounds symbolic targets with LocateAnything, executes bounded GUI actions or
restricted action programs, and verifies the resulting state.

Use registered `computer_use_*` tools instead of ad-hoc PyAutoGUI or desktop
scripts whenever the plugin is available.

## Local invocation and transport recovery

Use **one local call per invocation** of `tool_call`: its `calls` array must
contain exactly one THEIA entry. A two-entry local array is rejected before
execution. Do not confuse router batching with `computer_use_batch.steps` or
`computer_use_locate_batch.targets` (those arrays are supported by the plugin).

```json
{"calls":[{"name":"computer_use_prefetch_frame","arguments":{"status_only":true}}]}
```

A second tool needs a second invocation. An independent-call parallel wrapper
may contain separate one-entry `tool_call` invocations only for truly independent
read-only work. Never parallelize warm/recovery with grounding or actions, or
parallelize dependent desktop actions. Never change the core router contract.

`worker_admission_timeout` is busy/deadline exhaustion **before submission**, not
a broken transport: inspect status and explicitly retry with a fresh stage only
when the worker is available. Do not recover a healthy busy worker.
`stale_frame` after `response_drained=true` means the correlated speculative
response was drained but is too old to use, not a cancellation or quarantine.
The two-second freshness TTL still gates admission/usability; it cannot cancel
a native preparation already submitted. Transport drain has a separate bounded
worker timeout and retains exclusive serialization until completion.

For `worker_transport_timeout`, `worker_transport_error`, or
`worker_transport_quarantined`, stop actions. `native_call_cancelled=false` is
honest: timing out did not stop native work. Never silently warm, retry live
unbounded, switch to another engine, or restart the gateway. After source
activation, read `computer_use_worker_status` without screenshots. With current
user authorization invoke `computer_use_recover_worker(authorize=true)` in the
foreground: it disposes ONLY the owned quarantined isolated worker, confirms
exit before clearing quarantine, and starts no replacement. If busy or exit
unconfirmed, hand off; quarantine remains. Then separately warm and obtain
fresh capture/grounding before any action. Parent helpers/schemas require a
later authorized activation; editing worker source or skills is not live
handler activation. Do not claim recovery from a source-only test.

## Core invariants

1. **Fresh pixels before acting.** Known-target THEIA tools acquire them internally;
   explicit screenshots are for unknown-content reasoning or materialized evidence.
2. **Use fresh coordinates.** Coordinates belong only to the exact screenshot
   from which they were derived.
3. **Prefer native grounding.** On a validated Windows CUDA deployment, use
   `backend="cpp"` and verify `runtime="dll"`, `persistent=true`, and CUDA.
4. **Batch perception before actions.** Resolve independent targets together
   with `computer_use_locate_batch`; do not repeatedly encode the same image.
5. **Default to a batch for every eligible stage.** If a stage contains two or
   more known, harmless actions and later coordinates remain valid, use
   `computer_use_batch` rather than individual tools. Only split when the UI
   could change, the action is consequential, or verification is required
   between actions.
6. **Use restricted action code for repetition.** For 13–48 fixed-screen,
   harmless primitive actions or literal repeated navigation, use
   `computer_use_execute_code`; it compiles safe code into preflighted batches.
   It is never arbitrary Python and never replaces a dynamic workflow.
7. **Stage dynamic workflows.** After any action that may change layout,
   recapture and resolve a new stage. Never reuse stale symbolic coordinates.
8. **Verify outcomes.** A successful click or batch is not evidence that the UI
   reached the intended state.

## Canonical workflow

```text
capture immutable stage
  → resolve all independent targets together
  → batch every eligible harmless action (or compile repeated safe code)
  → execute one preflighted stage
  → recapture after any possible UI change
  → verify
  → repeat
```

### 1. Acquire fresh pixels internally (default)

For a known target, call `computer_use_locate`, `computer_use_locate_batch`,
`computer_use_find_click`, or a symbolic `computer_use_batch` directly with
`backend="cpp"` and **omit `image_path`**. `computer_use_observe_stage` and
`computer_use_verify_target` also acquire fresh local pixels internally.
No separate `computer_use_capture_screen` call or caller prefetch opt-in is
needed. This applies to private local UI too; it never implicitly invokes Jev.

THEIA uses bounded immutable RGB memory and shared-memory native transport,
queues resident-worker preparation within the acquisition handler, and uses
foreground preparation when the worker is cold. There is no always-on capture,
second engine, image-quality reduction, or relaxed two-second prefetch gate.
Full exact pixels and window/layout identity are rechecked before symbolic
input. Changed pixels fail closed; do not auto-retry with stale coordinates.

**Unknown content is different:** if Hermes must read an unfamiliar screen,
reason about a modal, or deliver visual evidence, explicitly capture a
materialized image and inspect it. A memory-only `.rgb` handle is not a file
and does not let Hermes claim to have seen unknown screen content. An explicit
`image_path` remains supported for immutable diagnostics; it is not evidence
of the current live UI until revalidated.

“No separate capture tool” means fused internal pixel acquisition, not
“No pixels acquired.” After layout changes use another fused call, not a
historical screenshot. Verify known postconditions using `verify_target`;
verify external side effects directly too.

### 2. Ground targets

- One target: `computer_use_locate()`.
- Several independent targets on the same image:
  `computer_use_locate_batch()`.
- Source and destination for one drag: `computer_use_find_drag()`.
- Locate and immediately click only when a fresh single click is clearly safe:
  `computer_use_find_click()`.

Never guess coordinates when visual grounding is available.

### 3. Act — batch-first decision

- **Two through twelve known harmless actions on a truly static screen:** use
  `computer_use_batch()` only when every action before the final step is
  non-invalidating (for example, cursor moves followed by one final click).
  A click, double-click, type, key press, scroll, focus change, or wait ends the
  grounded stage; only an optional trailing wait may follow.
- **Thirteen through forty-eight fixed harmless actions, especially repeated
  navigation:** use `computer_use_execute_code()` with `static_screen=true`.
- **One action, dynamic UI, or a stage needing visual evidence between actions:**
  use the individual mouse/keyboard tool, then recapture.
- Symbolic static stage: provide `targets` (omit `image_path` for fresh internal pixels),
  `static_screen=true`, and use `target_id` in click steps.

### 4. Verify

Use `computer_use_verify_target` for a known visible postcondition: fresh memory
pixels are automatic. Use a materialized screenshot and inspection for unknown
content. If an operation creates a file, also verify the file directly.

## Tool quick reference

| Need | Preferred tool |
|---|---|
| Capture and inspect | `computer_use_capture_screen`, `computer_use_get_active_window` |
| Warm persistent native engine | `computer_use_warm(backend="cpp")` |
| Ground one target | `computer_use_locate` |
| Ground up to 16 targets from one image | `computer_use_locate_batch` |
| Locate and click one safe target | `computer_use_find_click` |
| Locate a drag pair | `computer_use_find_drag` |
| Execute up to 12 harmless steps | `computer_use_batch` |
| Execute 13–48 repeated harmless fixed-stage steps | `computer_use_execute_code` |
| Mouse/keyboard primitives | `computer_use_click`, `computer_use_type`, `computer_use_press`, `computer_use_hotkey`, `computer_use_scroll`, drag tools |
| Recover interrupted holds | `computer_use_release_all` |
| Verify lightweight state | capture, `computer_use_pixel`, `computer_use_pixel_matches` |

## Persistent C++ LocateAnything

On the validated local Windows/CUDA installation, use these accuracy-preserving
defaults:

```text
backend="cpp"
device="cuda"
output_type="point"
strategy="direct"
prompt_style="direct"
max_side=1024
max_new_tokens=32
generation_mode="hybrid"
do_sample=false
```

Call `computer_use_warm(backend="cpp", device="cuda")` when cold-start latency
matters. A successful native warm response should identify:

```text
backend: cpp
runtime: dll
device: CUDA
persistent: true
```

The persistent JSONL worker owns one serialized native Q5 engine. It accepts
ABI v2 for rolling compatibility and ABI v3 for the raw-RGB preparation path,
keeps CUDA weights resident, and can retain a prepared visual representation
for the exact immutable screenshot. ABI v3 raw transport must report
`image_transport="raw_rgb"` and `encoded_file_ipc=false`. Serialization is
expected: several Q5 engines must not compete for GPU memory.

The preferred model is `locate-anything-q5_0.gguf`. Do not trade accuracy for
speed by lowering resolution, changing quantization, weakening prompts, or
reducing decode limits unless the user explicitly requests that trade-off.

### Runtime evidence

For live diagnostics, inspect target-level telemetry. The expected evidence is
`backend="cpp"`, `runtime="dll"`, `persistent=true`, a correlated
`request_id`, and `stale_responses_discarded=0`.

A top-level `backend="external"` may identify the JSONL transport wrapper;
target-level `backend="cpp"` plus `runtime="dll"` identifies actual native
inference. Never call a request persistent merely because the worker process is
persistent: confirm the runtime field so CLI fallback is not mistaken for DLL
reuse.

### Prepared-image reuse

The first request for a new screenshot may report image load, preprocessing,
vision, and projector phases. Later independent prompts on the exact same image
should omit those phases and decode against the cached prepared representation.

Reuse is valid only when the cache identity matches the screenshot content,
crop, resize dimensions, preprocessing, model/quantization identity, and
inference mode. Refinement crops are new images and require separate
preparation.

## `computer_use_locate_batch`

Use `computer_use_locate_batch` for up to 16 independent symbolic targets from
one immutable screenshot.

Each target needs a unique stable `id` and an unambiguous `description`:

```json
{
  "targets": [
    {"id": "new_session", "description": "New session button in left sidebar"},
    {"id": "capabilities", "description": "Capabilities button in left sidebar"}
  ],

  "backend": "cpp",
  "mode": "exact",
  "output_type": "point",
  "strategy": "direct",
  "max_side": 1024,
  "max_new_tokens": 32,
  "generation_mode": "hybrid"
}
```

### Locate modes

- **`exact` — default for acting:** independent prompts against one cached image
  representation. This is the accuracy-preserving baseline.
- **`auto` — calibrated optimization:** starts exact unless the same normalized
  target set has already produced two explicit successful `one_pass`
  calibrations. Once eligible, ambiguous labels immediately fall back to exact
  and disable speculation for that target set.
- **`one_pass` — diagnostics only unless mapping is proven:** accept only when
  every requested target maps exactly once to one returned label.

When correctness matters, use `exact`. Do not force one-pass results whose
`label_mapping_valid` is false. An `exact_fallback` is a safety success, not a
performance failure.

Duplicate normalized descriptions are rejected because a positional zip would
silently assign one detection to multiple target IDs. Ordinary words such as
“and” inside a target description are not category delimiters.

## `computer_use_batch`

`computer_use_batch` executes up to 12 steps only after the entire stage passes
preflight. Every step must set `risk="non_destructive"`.

Allowed actions are:

```text
move, move_relative, click, double_click, type,
press (navigation keys only), scroll, focus_window, wait
```

Use `stop_on_failure=true` unless harmless independent steps genuinely may
continue after one failure. `wait.duration_ms` is bounded to 0–10000 ms.

### Never batch

Never batch submission, posting, sending, purchase/payment, deletion,
authentication, credentials, security/permission changes, app launches,
destructive actions, or held/drag gestures. Do not batch Enter when it could
submit. Keep consequential actions separate so the agent can inspect and obtain
clear intent at the decision boundary.

Typed fields must be visibly non-sensitive. The safety preflight rejects
credential, payment, security, and other sensitive field purposes and redacts
typed content from telemetry.

## `computer_use_execute_code`

Use this speed path only after a capture established a **fixed** safe screen and
the action program has no decision, observation, target lookup, or layout
change between steps. It accepts a tiny restricted Python-like syntax and
compiles it to the same safe primitives as `computer_use_batch`; it does **not**
run imports, file/network access, arbitrary expressions, assignments, function
definitions, or arbitrary Python.

Provide `static_screen=true`. Calls use keyword arguments only; allowed calls
are `move`, `move_relative`, `click`, `double_click`, `type`, `press`, `scroll`,
`focus_window`, and `wait`. Literal `for _ in range(n)` loops are allowed. The
expanded plan is capped at 48 non-destructive actions and fully preflighted
before the first action.

```json
{
  "static_screen": true,
  "code": "for _ in range(3):\n    move(x=400, y=300)\nwait(duration_ms=150)"
}
```

Use `computer_use_batch`, not action code, for ordinary two-to-twelve-step
preparation. Use separate captured stages when an action scrolls, filters,
opens a menu/dialog, navigates, animates, resizes, or otherwise changes what a
later coordinate means. Never place Send, Submit, Enter-to-submit, Delete,
Purchase, authentication, credential handling, permission/security work, or
held/drag gestures in action code.

### Symbolic static-screen batch

To click grounded targets without manually copying coordinates:

1. Let the symbolic action tool acquire fresh immutable pixels internally (omit image_path).
2. Supply `targets` with authoritative descriptions.
3. Set `static_screen=true`.
4. Reference one final target using `target_id` in a click step.
5. Provide a truthful `target_hint` and a structured `safe_purpose` that both
   match the authoritative target description.
6. End the stage after the click (an optional trailing wait is allowed), then
   use a new fused observation before typing, navigation, or another action.

```json
{
  "targets": [
    {"id": "search", "description": "Search text field"}
  ],

  "locate_mode": "exact",
  "static_screen": true,
  "backend": "cpp",
  "stop_on_failure": true,
  "steps": [
    {
      "action": "click",
      "risk": "non_destructive",
      "target_id": "search",
      "target_hint": "Search text field",
      "safe_purpose": "focus_input"
    }
  ]
}
```

The preflight evaluates the authoritative target description as well as
caller-supplied hints. A harmless hint cannot disguise a target such as
“Confirm purchase.”

### Static-screen rule

`static_screen=true` is a factual assertion, not a performance hint. Do not set
it when an earlier click, type, scroll, focus change, wait, animation, dialog,
navigation, window move, or dynamic update might alter target positions.

If the screen may change, split the workflow:

```text
stage A: capture → locate → safe action
recapture
stage B: locate new state → safe action
recapture → verify
```

## Coordinates and crops

- Full-screen captures return screen-pixel coordinates.
- Region captures carry origin metadata; tool responses map detections back to
  source/screen coordinates.
- Use the returned `center` for point actions unless the task requires a box.
- Use `output_type="box"` for bounds, selection regions, or drag geometry.
- Recapture after scrolling, navigation, typing that filters results, opening a
  menu/dialog, window movement, or any animation that can shift layout.

## Direct file facts

When the user asks for duration, size, codec, page count, dimensions, modified
time, or another direct local-file property, prefer metadata/file tools. Do not
open applications and infer facts from partial UI state unless the task is
specifically about the visible application.

## Common pitfalls

1. **Warming `cpp`, then locating with another backend.** Pass
   `backend="cpp"` explicitly on warm, locate, locate-batch, and symbolic action
   batches.
2. **Capturing all monitors for one window.** Capture the active window region
   to preserve target detail at `max_side=1024`.
3. **Reusing stale coordinates.** Any layout-changing action ends the immutable
   stage; recapture immediately.
4. **Calling repeated single-target locates.** Resolve independent targets with
   `computer_use_locate_batch(mode="exact")` so visual preparation is shared.
5. **Assuming one-pass labels are correct.** Require exactly-once mapping or use
   exact fallback.
6. **Trusting only `target_hint`.** Safety depends on the authoritative symbolic
   description too.
7. **Batching a submit boundary.** Separate consequential final actions from
   harmless preparation.
8. **Claiming success from a click.** Verify the resulting state with a fresh
   capture or direct artifact check.
9. **Ignoring interrupted holds.** Call `computer_use_release_all()` after a
   failed or interrupted hold/drag sequence.
10. **Treating `not_found` as a backend failure.** Check `runtime`, telemetry,
    screenshot detail, target wording, and crop before changing backends.

## References

Load only the branch-specific reference needed:

- `references/batch-and-persistent-locate.md` — complete schemas, recipes,
  telemetry interpretation, and stage design for native locate and action
  batching.
- `references/agent-operating-loop.md` — detailed see → target → act → verify.
- `references/targeting-and-clicking.md` — individual locate/click patterns.
- `references/verification-and-safety.md` — destructive-action boundaries and
  evidence requirements.
- `references/gestures-drag-scroll.md` — non-batched held/drag workflows.
- `references/cpp-gui-grounding-debug.md` — empty detections and prompt/crop
  diagnosis.
- `references/cpp-coordinate-grounding.md` — mapping and stale-worker diagnosis.
- `references/locate-anything-cpp-upgrade.md` — native CUDA build/deployment.
- `references/troubleshooting.md` — plugin and worker failures.
- `references/starter-workflows.md` — simple application workflows.
- `references/live-panel-gesture-lifecycle.md` — stateful HUD gestures.

## Verification checklist

Before reporting completion:

- [ ] Correct window and current bounds were verified.
- [ ] Every acted-on coordinate came from the current immutable stage.
- [ ] `backend="cpp"` requests show target-level `runtime="dll"` when native
      persistence is required.
- [ ] Independent same-image targets used `computer_use_locate_batch`.
- [ ] One-pass mapping was accepted only when exactly-once and unambiguous.
- [ ] Every action batch passed full preflight before action one.
- [ ] No consequential or sensitive action was hidden inside a batch.
- [ ] Dynamic layout changes caused a recapture and new stage.
- [ ] The result was verified with fresh UI or artifact evidence.
- [ ] No held input state remains.

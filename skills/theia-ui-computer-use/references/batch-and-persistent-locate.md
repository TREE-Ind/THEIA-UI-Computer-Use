# Batch and Persistent Locate Reference

## Default native THEIA acquisition

For a known target, omit image_path and call the fused THEIA tool directly.
Fresh pixels are acquired internally in memory, not by a separate agent screenshot
round trip. Use locate_batch/observe_stage for grounding, find_click or symbolic
batch for safe input, and verify_target for known postconditions. Private local
UI is allowed; Jev is never implicit. Exact current pixels/window identity gate
symbolic actions. A changed/ambiguous screen requires a new stage, not stale ROI.
Only unknown-content visual reasoning or deliverable evidence requires explicit
computer_use_capture_screen followed by honest image inspection. The older
explicit-image recipes below are diagnostics, not mandatory acquisition steps.



Use this reference when designing a multi-target stage, diagnosing native
LocateAnything persistence, or deciding whether GUI actions may safely share a
batch.

## Decision table

| Situation | Tool/mode |
|---|---|
| One target, dynamic screen | `computer_use_locate`, then one action |
| Several independent targets, same screenshot | `computer_use_locate_batch(mode="exact")` |
| Explore whether one-pass mapping works | `computer_use_locate_batch(mode="auto")` |
| Benchmark one-pass only | `computer_use_locate_batch(mode="one_pass")`; do not act unless mapping is valid |
| Several harmless steps, fixed coordinates | `computer_use_batch` |
| Harmless clicks on symbolic targets, truly static screen | `computer_use_batch` with `targets`, `target_id`, `static_screen=true` |
| Click/type changes layout | Separate stages with a fresh capture between them |
| Submit, purchase, delete, authenticate, send | Never batch; inspect and act separately with clear intent |

## Native warm and one-target locate

Warm once when cold-start latency matters:

```json
{
  "backend": "cpp",
  "device": "cuda"
}
```

Expected warm evidence:

```text
status=loaded
backend=cpp
runtime=dll
device=CUDA
persistent=true
```

One-target locate against an explicit immutable image:

```json
{
  "description": "New session button in left sidebar",
  "image_path": "C:/.../screen.png",
  "backend": "cpp",
  "device": "cuda",
  "output_type": "point",
  "task": "single",
  "strategy": "direct",
  "max_side": 1024,
  "max_new_tokens": 32,
  "generation_mode": "hybrid",
  "prompt_style": "direct",
  "do_sample": false
}
```

Use concise visible descriptions. If a request returns `not_found` while
`backend=cpp`, `runtime=dll`, and native timing is present, the backend worked;
reconsider screenshot scope/detail and wording before changing runtimes.

## Locate-batch schema

`computer_use_locate_batch` accepts:

- `targets`: 1–16 `{id, description}` objects.
- `image_path`: exact immutable screenshot; captures once if omitted.
- `mode`: `exact`, `auto`, or `one_pass`.
- `backend`: prefer `cpp` on the validated native deployment.
- `output_type`: `point` or `box`.
- `strategy`: `direct`, `refine`, or `coarse_refine`.
- `max_side`: normally 1024.
- `max_new_tokens`: normally 32.
- `generation_mode`: `hybrid`, `fast`, or `slow`; preserve `hybrid` unless a
  deliberate accuracy/performance change was requested.

Accuracy-preserving example:

```json
{
  "targets": [
    {"id": "new_session", "description": "New session button in left sidebar"},
    {"id": "capabilities", "description": "Capabilities button in left sidebar"}
  ],
  "image_path": "C:/.../screen.png",
  "mode": "exact",
  "backend": "cpp",
  "device": "cuda",
  "output_type": "point",
  "strategy": "direct",
  "max_side": 1024,
  "max_new_tokens": 32,
  "generation_mode": "hybrid"
}
```

### Reading locate-batch results

Check:

1. Overall `status` and each target's `status`.
2. Each target's `backend`, `runtime`, `box`, and `center`.
3. `mode_requested` versus `mode_used`.
4. `label_mapping_valid`.
5. `fallback_reason` and `one_pass_timing` when auto falls back.
6. `request_id`, `persistent`, and `stale_responses_discarded`.
7. Native pass timing and whether image preparation phases disappeared on
   exact-image reuse.

`mode_used="exact_fallback"` means the model rejected ambiguous one-pass
mapping and reran independent prompts against the cached image. This is the
correct safety behavior.

### Timing interpretation

- Cold warmup: DLL load, Q5 model load, and CUDA weight residency.
- First image request: image load, preprocess, vision, projector, and decode.
- Cached exact-image request: prompt/decode/parse without vision preparation.
- `duration_ms`: native pass or wrapper stage duration.
- `timing.total_ms`: end-to-end worker-side time.

Do not compare timings from different screenshot sizes or target/mode settings
as though they were equivalent.

## Safe action-batch schema

`computer_use_batch` accepts 1–12 ordered steps. Every step requires:

```json
{"action": "...", "risk": "non_destructive"}
```

Allowed actions and key fields:

| Action | Fields |
|---|---|
| `move` | `x`, `y`, optional `duration`, `tween` |
| `move_relative` | `dx`, `dy`, optional `duration`, `tween` |
| `click` / `double_click` | `x`,`y` or `target_id`; `target_hint`; left button only |
| `type` | `text`, `field_hint`, optional `interval` |
| `press` | navigation `keys`, optional `presses`, `interval` |
| `scroll` | `clicks` (-20..-1 or 1..20), optional paired `x`,`y` |
| `focus_window` | `title`, optional `exact` |
| `wait` | `duration_ms` from 0 through 10000 |

Top-level fields:

- `stop_on_failure`: default and preferred `true`.
- `targets`: optional, up to 16 symbolic descriptions.
- `image_path`: immutable screenshot for symbolic resolution.
- `locate_mode`: `exact`, `auto`, or `one_pass`; use `exact` before actions.
- `static_screen`: must be `true` when symbolic targets are supplied.
- `backend`: pass `cpp` when native grounding is required.

### Fixed-coordinate harmless batch

```json
{
  "stop_on_failure": true,
  "steps": [
    {
      "action": "click",
      "risk": "non_destructive",
      "x": 420,
      "y": 300,
      "target_hint": "Non-destructive filter control"
    },
    {
      "action": "wait",
      "risk": "non_destructive",
      "duration_ms": 300
    }
  ]
}
```

Use this only when every coordinate remains valid throughout the batch.

### Symbolic harmless batch

```json
{
  "targets": [
    {"id": "search", "description": "Search text field"}
  ],
  "image_path": "C:/.../screen.png",
  "locate_mode": "exact",
  "static_screen": true,
  "backend": "cpp",
  "stop_on_failure": true,
  "steps": [
    {
      "action": "click",
      "risk": "non_destructive",
      "target_id": "search",
      "target_hint": "Search text field"
    },
    {
      "action": "type",
      "risk": "non_destructive",
      "text": "open issues",
      "field_hint": "Non-sensitive search query"
    }
  ]
}
```

Before using this shape, verify that typing cannot filter, navigate, resize, or
otherwise invalidate any later symbolic coordinates. If it can, make typing the
last step or create a new stage afterward.

## Whole-plan preflight

No step executes until all steps and symbolic targets pass validation.
Preflight checks include:

- step count and bounded waits;
- allowed action set;
- explicit `risk="non_destructive"`;
- safe keys and left-button clicks;
- truthful visible target/field purpose;
- authoritative symbolic target descriptions;
- blocked destructive/high-impact language;
- blocked credential, payment, authentication, security, and sensitive fields;
- valid symbolic target IDs and successful coordinate resolution;
- `static_screen=true` for symbolic batches.

A caller-provided `target_hint` is not trusted over the symbolic description.
Both are inspected.

## Stage-design examples

### Good: static inspection controls

Capture a static preferences panel, resolve two tabs, then click one harmless
tab and move the pointer to another location. Verify afterward.

### Bad: menu then menu item from one screenshot

Clicking the menu changes layout; the menu item did not exist in the original
coordinate space. Use two stages:

```text
capture → locate menu → click
capture expanded menu → locate item → click
capture → verify
```

### Bad: search then result

Typing changes result positions. Use:

```text
capture → locate search field → click/type
wait for stable state
capture → locate result → inspect/click if safe
capture → verify
```

### Bad: preparation plus final submission

Do not put a Send, Post, Purchase, Delete, Confirm, Sign in, or Enter-to-submit
step in the harmless batch. Batch only reversible preparation, then inspect the
final state and handle the consequential boundary separately.

## Failure handling

- **Worker/runtime failure:** check `runtime`, DLL path, ABI, CUDA dependencies,
  and any fallback reason. Do not report CLI latency as persistent-DLL latency.
- **Worker EOF/crash:** the parent should dispose/restart promptly; correlated
  request IDs prevent stale responses from being accepted.
- **One-pass ambiguity:** use exact fallback.
- **Target not found:** narrow the capture, improve visible wording, or use
  `output_type="box"`; do not guess coordinates.
- **Partial batch:** do not act on unresolved targets unless the plan explicitly
  excludes them and remains safe.
- **Screen changed:** discard every coordinate and recapture.

## Completion evidence

A completed native symbolic-batch workflow should establish:

- the exact screenshot path and dimensions;
- requested backend and target-level actual runtime;
- coordinate space and target centers/boxes;
- locate mode actually used and mapping validity;
- action-batch preflight success before action one;
- step results with typed content redacted;
- a fresh post-action verification capture;
- no held mouse buttons or modifiers.

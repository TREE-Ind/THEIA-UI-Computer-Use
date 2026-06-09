# Gestures, Dragging, and Scrolling

Use this for sliders, timelines, drawing canvases, selection boxes, file drags, and scroll-heavy apps.

## Choose the right tool

| Tool | Use when |
|---|---|
| `computer_use_scroll` | Move page/list content vertically |
| `computer_use_drag` | Straight drag from one absolute point to another |
| `computer_use_drag_relative` | Drag from current cursor by an offset |
| `computer_use_drag_path` | Multi-point drawing or finicky UI path |
| `computer_use_mouse_down` + move + up | Manual hold sequence with extra control |

## Scroll recipe

1. Move cursor over the scrollable region if needed.
2. Scroll a small amount.
3. Capture and verify content moved.
4. Repeat.

Avoid huge scroll jumps unless the user asked to skip far down.

## Slider recipe

1. Locate the slider track and handle.
2. Drag the handle a short distance.
3. Verify the displayed value or visual state.
4. Adjust again if needed.

Prefer multiple small drags over one large unverified drag.

## Timeline recipe

For video/audio editors or similar timelines:

1. Verify the timeline region.
2. Locate the clip/playhead/handle.
3. Use `drag` or `drag_path` with conservative movement.
4. Verify the new position visually or via timecode.

## Drawing recipe

For drawing on a canvas:

1. Verify the canvas bounds.
2. Use `drag_path` for curves or shapes.
3. Keep points inside the canvas.
4. Capture after drawing.

## Recovery

If the pointer/button seems stuck or a modifier was held:

```text
computer_use_release_all()
```

Then re-capture before continuing.

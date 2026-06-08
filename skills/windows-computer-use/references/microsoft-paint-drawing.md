# Microsoft Paint drawing workflow notes

Use this reference when asked to open Paint and draw a visible object using Windows UI control only.

## Reliable sequence

1. Open Paint with `computer_use_open_app({"command":"mspaint"})` and verify `active_window.title` contains `Paint`.
2. Capture the screen and locate the **actual white canvas bounds** before drawing. Do not assume coordinates from a previous Paint session; Paint may reopen with a tiny canvas or a selected/resizable canvas object.
3. If the canvas is tiny, enlarge it first by dragging the lower-right canvas handle, then recapture and verify the new white canvas area is large enough for the requested drawing.
4. Select the intended drawing tool and color explicitly:
   - For a clean geometric circle: select the oval/ellipse shape, black outline/color, then Shift-drag inside the verified canvas bounds.
   - For a simple “draw a circle” request where exact geometry is less important: select the pencil tool and black color, then use `computer_use_drag_path` with points that form a circle entirely inside the verified canvas.
5. Avoid drawing while Paint is in canvas-resize/selection-handle mode. If handles remain visible around the whole canvas, clicking/dragging may resize or select rather than draw. Click a drawing tool/color again and start the stroke well inside the white canvas.
6. Verify with a final capture. Prefer tight region capture around the canvas or object when possible so the drawn line is visible and not lost in a full-screen screenshot.

## Pitfalls observed

- The ellipse shape button in the toolbar can be confused with already-drawn/selected handles. After selecting the shape, verify the next drag begins on the white canvas and produces visible ink, not just selection handles.
- A tiny default canvas (for example around 64 × 66 px) makes large drag gestures appear to do nothing because the stroke starts outside the drawable area. Enlarge the canvas before drawing.
- Repeated Escape/click attempts may not dismiss Paint canvas handles. If handles persist, treat them as a state signal: recapture, enlarge/position the canvas if needed, and then explicitly reselect the tool and color before attempting another stroke.
- Do not claim success until a final screenshot visibly shows the requested drawing. If the final verification is blocked by an iteration/tool limit, report that limitation honestly.

# Shotcut: add an audio filter to a WAV clip on A1

Session-verified workflow for adding a High Pass filter to an audio clip already placed on the Shotcut timeline.

## Verified steps

1. Focus Shotcut and make sure the timeline clip is selected.
   - Visible evidence: the clip on `A1` has a red outline.
   - If needed, click the waveform clip body, not just the track header.
2. Open the **Filters** panel/tab.
   - If the left panel currently shows Playlist, click the **Filters** tab at the bottom of the left pane.
3. Confirm the selected clip name appears at the top of the Filters panel.
   - Example: `Old_School_Drive_2026-06-05T181200.wav`.
4. Click the **+** button in the Filters panel toolbar.
5. In the filter chooser, type the filter name into the search field.
   - For this session: `high pass`.
6. Double-click the matching filter result.
   - For High Pass, the result appears as `High Pass` with an audio icon.
7. Re-capture and verify the filter was added.
   - Visible evidence: under `Audio`, the Filters panel lists `High Pass` and shows controls such as `Cutoff frequency`, `Rolloff rate`, and Dry/Wet percentage.

## Pitfalls

- Clicking the top toolbar **Filters** button may show the panel, but the filter is added to the currently selected object. Select the timeline clip first and verify the clip name appears in the Filters panel.
- A single click on a filter result may only select it; double-click the result to add it.
- Do not report success from the search result alone. Verify the added filter list and its parameter controls are visible.
# Discord search workflow

Use this when the user asks to find/read a Discord post from the already-open desktop app, especially with an instruction not to send messages.

## Safe workflow

1. Focus the existing Discord window with `computer_use_focus_window(title="Discord", exact=false)`.
2. Capture the screen and identify the top Discord search box. Do **not** click the message composer at the bottom.
3. If visual grounding targets the wrong field, capture a top-strip region and use the visible coordinates manually. In Discord desktop, the search box is usually in the top channel header, to the right of the channel name and icons.
4. Click the search box, type the query, and press Enter.
   - Exact-phrase searches can use quotes, e.g. `"TREE Industries"`.
5. Capture results and read the latest/top result first. Discord search results may show embedded social posts; capture/scroll within the result card to read continuation text.
6. If more text is hidden below the first crop, scroll inside the results pane, not the channel list or message composer. Capture a focused region around the result card for OCR/vision.
7. Summarize what was visible and include the result date/time and channel when available.

## Pitfalls

- The chat composer is visually prominent near the bottom; never type there for search tasks.
- LocateAnything can confuse the top search box with other input fields when a second app/window is visible. Prefer a top-region capture and manual coordinate click if the point lands near the bottom/composer.
- Discord search may return multiple matches; unless the user asks otherwise, the top result is the latest when results are in the default ordering. Verify the visible date/time.
- Streamer Mode can truncate usernames; avoid overclaiming the full sender name if Discord hides it.

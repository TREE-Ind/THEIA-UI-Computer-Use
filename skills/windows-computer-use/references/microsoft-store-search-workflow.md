# Microsoft Store search workflow

Observed workflow for launching Store search and opening the first result:

1. Click the Microsoft Store / Store icon on the taskbar or Start surface.
2. If Windows opens a Search/Start window instead of the Store app, continue there — the search field is still usable.
3. Type the query into the visible search box and press Enter.
4. Locate the first result with `computer_use_locate` before clicking it.
5. After clicking, capture the screen again and verify the active window title changed to the expected result page before reporting success.

Pitfall to watch:
- The UI surface may change from Store to Search/Edge-like result pages after Enter. Always re-capture and re-locate rather than assuming the original window remains active.

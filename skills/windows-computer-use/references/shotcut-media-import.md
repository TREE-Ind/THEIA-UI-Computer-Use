# Shotcut media import and timeline placement

Use this workflow when a user asks to open a local video/audio file in Shotcut and place it on the timeline.

## Reliable sequence

1. Identify and validate the target file first when the request is relative, such as "latest WAV in Downloads" or "last two videos in Videos".
   - Use file search / filesystem metadata to pick the newest matching file before touching the UI.
   - For WAV files, match `*.wav` / `*.wave`; on Windows, Downloads is typically `C:\Users\joshu\Downloads` for this user.
   - For MP4/video files, validate candidates with Shotcut's bundled `ffprobe.exe` when possible. If the newest file is incomplete/unreadable (common with active OBS recordings; `moov atom not found`), skip to the newest valid completed file and report that substitution clearly.
2. Open Shotcut and choose **Open File** (`Ctrl+O` is a fast path).
3. In the file dialog, either navigate to the target folder or focus the filename field (`Alt+N`) and type/paste the full absolute path, then press **Enter**.
4. After the dialog closes, confirm Shotcut loaded the file.
   - For audio-only files, the source/player area may show black/transparent video preview, the time ruler updates to the clip duration, and the audio meters may move; the playlist may still be empty.
5. If the clip is not yet in the playlist/media bin, click the **Playlist** tab and use the **+** button in the playlist toolbar to add the currently loaded source to the playlist.
6. Drag the imported playlist item/thumbnail onto the destination timeline track.
   - For an audio-only file, drag the playlist item onto the `A1` track body, not the player/source preview.
7. Verify the clip is visible on the intended timeline track before reporting success.
   - For WAV clips, visible evidence is a green waveform clip on `A1` with the filename label.

## Practical notes

- If the open dialog stays in front after a selection, do not assume import failed; sometimes the filename label needs to be selected more explicitly.
- For local videos, drag-from-playlist-to-timeline is often the fastest path after import.
- For audio-only files, importing can load the source without automatically creating a playlist item. Dragging from the source/player preview may do nothing; add the source to Playlist first, then drag the playlist thumbnail to the audio track.
- Always re-capture the screen after each major step so you can confirm the app state actually changed.
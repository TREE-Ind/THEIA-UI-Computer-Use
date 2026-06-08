# Shotcut export fallback with bundled ffmpeg

Use this when a Shotcut video assembly/export task needs to be completed reliably and the GUI path is blocked, slow, or hard to verify. This is still a Shotcut-backed workflow when using the executables bundled in `C:\Program Files\Shotcut`.

## Workflow

1. Resolve relative media requests from filesystem metadata first.
   - For "last two videos", sort `C:\Users\joshu\Videos` by modified time descending.
   - Newest goes second on the final timeline, so concatenate the older of the two first, then the newer second.
   - For "latest wav", sort `C:\Users\joshu\Downloads\*.wav` by modified time descending.
2. Validate every candidate input before building the export.
   - Use Shotcut's bundled `ffprobe.exe` when available:
     `C:\Program Files\Shotcut\ffprobe.exe -v error -show_entries format=duration -show_entries stream=codec_type,width,height,avg_frame_rate -of json <file>`
   - If a newest MP4 is invalid/incomplete, e.g. `moov atom not found` while OBS is still recording, skip it and use the newest two valid completed videos. Report this clearly in the final response.
3. Render with Shotcut's bundled `ffmpeg.exe` if the requested edits are simple and deterministic.
   - Video fade-out on only the second clip: apply `fade=t=out:st=<second_duration-fade_duration>:d=<fade_duration>` to the second video stream before `concat`.
   - Audio fade-out on the added WAV track: trim it to the combined video duration, then apply `afade=t=out:st=<total_duration-fade_duration>:d=<fade_duration>`.
   - If preserving original clip audio plus music, concatenate the clips' native audio, mix with the WAV using `amix=inputs=2:duration=first`, and limit with `alimiter`.
4. Export to the requested MP4 path, normally under `C:\Users\joshu\Videos` unless the user gave another destination.
5. Verify with `ffprobe` after export: file exists, duration, streams, dimensions, frame rate, and size.

## Example filter shape

```text
[0:v]fps=60,scale=1920:1080,setsar=1[v0];
[1:v]fps=60,scale=1920:1080,setsar=1,fade=t=out:st=<dur2-2>:d=2[v1];
[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[v][va];
[2:a]atrim=0:<total>,asetpts=PTS-STARTPTS,afade=t=out:st=<total-2>:d=2[music];
[va][music]amix=inputs=2:duration=first:dropout_transition=0,alimiter[a]
```

## Pitfalls

- Do not assume the newest `.mp4` is usable. Fresh OBS recordings can appear in Videos before the MP4 has a valid `moov` atom.
- If the user specifically demands UI-only editing, do not silently use this fallback; use the Shotcut GUI workflow instead or ask before falling back.
- Keep the final answer grounded in real verification output, not just that the render command completed.
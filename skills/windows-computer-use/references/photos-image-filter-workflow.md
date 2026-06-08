# Microsoft Photos image filter workflow

Use this when the user asks to edit the currently open image in Microsoft Photos and apply a filter.

## Pattern

1. Capture the desktop and confirm the image is open in Photos.
2. If the user simply wants a visual filter and not a specific Photos UI effect, prefer editing the underlying image file directly with Pillow, then let Photos refresh/reopen the saved file. This is faster and more reliable than fighting Photos' transient edit tabs.
3. Locate the file path from the Photos title/visible filename plus likely user folders (`Downloads`, `Desktop`, `Pictures`). Search narrowly by exact filename rather than scanning the whole home directory.
4. Before overwriting, create a sibling backup such as `<stem>_original_backup.<ext>` if it does not already exist.
5. Apply a legible filter that preserves text/readability for infographics: autocontrast, modest color/contrast/sharpness boost, subtle split-tone/cyber teal-violet overlay, light vignette, and final unsharp mask.
6. Save back to the original path unless the user explicitly asked for a separate output file.
7. If Photos is in edit mode, click `Cancel`/back out after direct file editing so it returns to normal view and refreshes from disk. Verify visually that the displayed image reflects the saved filter.

## Pitfalls

- In Photos edit mode, the background/removal icon can look like a generic filter/effects tab. Clicking it may select the image background and apply a blue diagonal overlay, which is not the requested cool filter. If that happens, cancel out rather than saving the Photos edit.
- Do not scan all of `C:\Users\<user>` for a filename when likely folders are enough; broad searches may time out.
- For text-heavy images, avoid heavy blur, destructive saturation, or opaque overlays. Preserve readability first.

## Minimal Pillow recipe

```python
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

src = Path(r'C:\Users\joshu\Downloads\infographic.jpg')
backup = src.with_name(src.stem + '_original_backup' + src.suffix)
if not backup.exists():
    backup.write_bytes(src.read_bytes())

img = Image.open(src).convert('RGB')
base = ImageOps.autocontrast(img, cutoff=1)
base = ImageEnhance.Color(base).enhance(1.18)
base = ImageEnhance.Contrast(base).enhance(1.12)
base = ImageEnhance.Sharpness(base).enhance(1.35)
# Add a subtle cool overlay/vignette as needed, then sharpen for readability.
base = base.filter(ImageFilter.UnsharpMask(radius=1.1, percent=80, threshold=3))
base.save(src, quality=95, subsampling=0)
```

## Gotchas

### osxphotos

- `PhotosDB()` loads the entire SQLite database on init (~20s for 120k photos). There's no way around this — use `from_date` filter on `.photos()` to limit results after loading.
- `.photos(from_date=...)` filters by **date taken**, not date added. Sort by `photo.date_added` yourself if you want most recently added.
- `photo.ismissing` is `True` for iCloud-only files. The `path` property returns `None` for these.
- `photo.export()` without `use_photos_export=True` silently returns `[]` for missing/iCloud-only files. Always use `use_photos_export=True` — it works for both local and iCloud files.
- `photo.isphoto` and `photo.ismovie` are the way to distinguish photos from videos. There's no built-in filter for this on `.photos()`.
- No built-in "has no keywords" query — you must filter `not p.keywords` in Python after loading.

### PhotoScript

- `photoscript.Photo(uuid)` can fail with `ValueError: Invalid photo id` for some iCloud-only items. Use it only for writing metadata, not for export.
- Photos.app must be running for any PhotoScript/AppleScript operations.
- Writes are slow — each AppleScript call is a round-trip to Photos.app.

### Image formats

- HEIC is the default iPhone photo format. Pillow can't read it natively — requires `pillow-heif` with `pillow_heif.register_heif_opener()` called before `Image.open()`.
- Always convert to JPEG before sending to LM Studio. HEIC causes `400 - Failed to predict` errors.

### LM Studio / Qwen

- Qwen 3.5 includes `<think>...</think>` blocks in responses by default. Must strip with regex before parsing JSON.
- LM Studio ignores the `chat_template_kwargs: {"enable_thinking": False}` API parameter. The only reliable server-side fix is editing the Jinja template in LM Studio to add `{%- set enable_thinking = false %}`.
- Responses may be wrapped in markdown code fences (`` ```json ... ``` ``). Strip those before `json.loads()`.

### Video processing

- Videos require `ffmpeg` (system dependency) for frame extraction.
- Use `ffprobe` to get duration, then `ffmpeg -ss <timestamp> -i <file> -frames:v 1` for each frame.
- Large videos (100+ MB) take time to download from iCloud via `use_photos_export=True`. Set a generous timeout (300s).
- All 10 frames are sent as separate `image_url` entries in a single LLM request — this can be a large payload.

### Concurrency

- `PhotoScript` writes use AppleScript which is single-threaded in Photos.app. Parallel writes may cause issues — serialize metadata writes even when processing in parallel.
- `osxphotos.PhotosDB()` should only be instantiated once and shared across threads.

# Failures and edge cases

Every failure and edge case the labeler has run into, from the first version in March 2026 to 0.10.2 on 26 Nov 2026: what happened, why, and what was done about it. It is written for whoever labels a library like this next, including the iOS app this labeler's job is moving to, so the same problems don't have to be found again.

Sources: the git history, `daemon.log` (11 May to 26 Nov 2026), `metrics.db`, `migrate.log`, and notes kept while working on the labeler. The numbers come from one library of about 129,000 photos and 8,500 videos in iCloud Photos, on a Mac set to *Optimize Mac Storage*, so almost every original is only in iCloud (8,449 of 8,460 videos on 24 Nov 2026).

Each entry gives the version and commit that dealt with it. **Open** means 0.10.2 still behaves that way.

## Contents

- [What it adds up to](#what-it-adds-up-to)
- [How a photo or video reaches the labeler](#how-a-photo-or-video-reaches-the-labeler)
- [iCloud downloads](#icloud-downloads)
- [PhotoKit](#photokit)
- [Photos.app and AppleScript](#photosapp-and-applescript)
- [photolibraryd and the Photos database](#photolibraryd-and-the-photos-database)
- [osxphotos and finding work](#osxphotos-and-finding-work)
- [Video files and ffmpeg](#video-files-and-ffmpeg)
- [Whisper and transcripts](#whisper-and-transcripts)
- [LLM servers and replies](#llm-servers-and-replies)
- [Keywords](#keywords)
- [metrics.db](#metricsdb)
- [The daemon, launchd and Homebrew](#the-daemon-launchd-and-homebrew)
- [Memory and speed](#memory-and-speed)
- [Still open](#still-open)
- [Timeline of the worst episodes](#timeline-of-the-worst-episodes)

## What it adds up to

| # | Rule | Why |
|---|---|---|
| 1 | Skip an item for good only for a reason the item itself has: a file that was there and had no video stream, or a reply the content filter cut off twice. A download that didn't arrive, or an app that wasn't answering, is tried again on a later run. | 130 videos were skipped forever because iCloud hadn't sent them (fixed in 0.10.2). On 27 Oct a hung Photos.app made every iCloud video look broken. |
| 2 | Ask Photos for small versions (1024 px photos, 720p videos), start many requests at once, use whichever arrives first, and give each a timeout. When the time is up, let the download keep going and come back to the item later instead of cancelling it. | A 4K original is 360-700 MB and iCloud sent 0.16-4.7 MB/s. Cold photos took 1.8 s each one at a time and 0.22 s each with 32 started ahead. One stuck video used to hold up every other video for 15 minutes, and a cancelled download starts from zero. |
| 3 | Put many changes into one Photos save. | photolibraryd saves one change at a time, and a save that adds or removes a keyword loads every photo that has it: about 1 s per photo saved alone, 0.45 s for 10 photos in one save. |
| 4 | Release each item's images as soon as it is done. | Without an autorelease pool around each export the daemon kept 3.6 MB per photo and reached 19 GB. |
| 5 | Stop the queue on server and account errors instead of failing the item. | Running out of credits, a model with no image input, and "no model loaded" were logged as more than 14,000 item failures. **Open.** |
| 6 | Limit how many runs an item is retried, keep that count, and show what is stuck. | Timeouts and connection errors are retried forever: one video 1,818 times over 11 days while nothing else ran. **Open.** |
| 7 | Find out whether an item can be read and written before spending an LLM request on it. | Photos that Photos.app's scripting couldn't see were labeled about 25,000 times and never written. |
| 8 | Write the caption before the keywords, so an item never has the new model tag next to an old caption. | |
| 9 | Keep `trans:` keywords when rewriting keywords, and keep every keyword lowercase and without commas. | Photos keeps each casing as its own keyword (13,557 keywords had more than one) and its Info window splits keywords at commas. |
| 10 | Filter what Whisper writes. | 540 of 699 transcripts were made-up text before the filters. |
| 11 | Don't load the whole library to find work. | Loading it took about 20 s for 120,000 photos in March and 2-10 minutes by November. |
| 12 | Don't throw away keywords typed by hand when relabeling. | A relabel keeps only `trans:` keywords, with no backup. **Open.** |

## How a photo or video reaches the labeler

Videos, as of 0.10.3 (`_resolve_video_path` in `exporter.py`):

```
720p version through PhotoKit (VIDEO_PREFETCH = 4 started ahead, the first one ready is used)
  │
  ├─ a file with a video stream ──────────────────────────────► label it
  ├─ no answer in VIDEO_EXPORT_TIMEOUT (300 s), first time ───► to the end of the batch, download keeps going
  ├─ no answer in 300 s again, iCloud-only ───────────────────► VideoNotDownloaded: next cycle
  ├─ the download failed (no asset), iCloud-only ─────────────► VideoNotDownloaded: next cycle
  └─ nothing, an AVComposition (slow motion), or no stream
        │
        ▼
     Photos export of the original (osxphotos, use_photos_export=True, 300 s)
        ├─ returned nothing, iCloud-only ─── force-quit and reopen Photos.app, export once more
        ├─ a file with a video stream ──────────────────────────► label it
        └─ a 691-999 byte file with no stream, or nothing
              │
              ▼
           the original on the Mac (photo.path)
              ├─ has a video stream ─────────────────────────────► label it
              ├─ the 720p file or the original was there, no stream ► "No usable video source": skipped for good
              └─ neither was there ──────────────────────────────► VideoNotDownloaded: next cycle
```

Photos (`export_photo_as_base64`):

```
1024 px through PhotoKit (PHOTO_PREFETCH = 32 started ahead, PHOTO_EXPORT_TIMEOUT = 30 s)
  └─ none: Photos export (osxphotos) → the original on the Mac → Photos' own derivatives, largest first
       → opened with Pillow (img.load() reads it all), or converted with `sips -s format jpeg`
       → resized to max_dimension, sent as JPEG
```

## iCloud downloads

- **A download that never arrived was recorded as a broken video.** 130 videos (May to Nov 2026, 127 of them iCloud-only at the time) had "No usable video source" errors, which `PERMANENT_FAILURE_PATTERNS` skips forever. For 118 of them Photos' export had returned a 691-999 byte file with no video stream, and for the rest nothing, because the original was still in iCloud. 75 of them had been labeled or transcribed fine before. Asked again on 26 Nov, PhotoKit returned a normal 720p file for each one tried (8-93 s). Fixed in 0.10.2 (6e30262): only a 720p file or an original that was there and had no video stream counts as permanent; otherwise `VideoNotDownloaded` is raised and the video is tried again next cycle. The 130 rows were deleted from `item_metrics` the same day so those videos are tried again; in the first cycle after that, one whose 720p version didn't arrive in 300 s was marked to try again instead of skipped.
- **A hung Photos.app made every iCloud video look broken.** On 27 Oct 2026 Photos answered even simple queries with `AppleEvent timed out (-1712)`, and every iCloud-only video export returned nothing after 120 s, which was recorded as "No usable video source". 38 videos were marked permanent before anyone noticed; a full reindex would have skipped thousands. After restarting Photos the same videos exported in 2-26 s. The exporter now restarts Photos.app and tries once more when an iCloud-only export returns nothing (777d1ca, 0.1.4).
- **One stuck video held up all the others.** Up to 0.9.1, a video whose 720p version didn't arrive waited 300 s, then 300 s more for a Photos export of the original, then a Photos restart: about 15 minutes, while every other video waited. On 24 Nov five videos in a row took about 15 minutes each, and a batch could retry an item up to 10 times. 0.9.2 (345df40) exports whichever requested item is ready first (`PhotoKitPrefetch.next_ready`), counts each item's timeout from when it reached the front, and fails a timed-out iCloud-only video at once so it is tried next cycle.
- **A failed 720p download still went to the Photos export of the original.** The 0.9.2 fix only covered a 720p request that timed out. When cloudd gave up on the download instead and PhotoKit returned no asset, the video still went to the Photos export of the original, waited 300 s, restarted Photos.app and waited 300 s more. On 26 Nov `IMG_7526.MOV` held up every other video from 12:54 to 13:09 that way; cloudd had stopped its 720p download after 19 MB in 234 s. Since 0.10.3 PhotoKit's empty answer for an iCloud-only video raises `VideoNotDownloaded` at once (`DownloadFailed` in `exporter.py`). An `AVComposition` (slow motion) and videos whose original is on the Mac still go to the export.
- **A timed-out download threw away what had arrived.** Cancelling a PhotoKit request stops cloudd's download, and the next cycle starts from zero. With iCloud at 0.3 MB/s, a 720p file over about 45-90 MB could never arrive in 300 s, so it failed every cycle. Since 0.10.3 an item still downloading when its time is up goes to the end of the batch once and its request keeps going (`PhotoKitPrefetch.put_back`); it is cancelled only if it still hasn't arrived after a second 300 s at the front. A finished 720p download is kept in the library's `resources/derivatives` folder, so it is there for later cycles too.
- **More requests at once don't make iCloud faster.** On 26 Nov at midday, with 4, 16 and 32 extra 720p requests, cloudd's download stayed at 0.24-0.38 MB/s, and none of 32 extra requests got any data in 8 minutes. cloudd downloads files in 30 MB pieces, about two at a time, and a piece can wait 2-24 minutes in its queue before it starts (`Observed ... seconds in queue` in cloudd's `com.apple.mmcs` log). The requests are already `qos=UserInitiated`. Each piece came at about 8 Mbit/s from 01:00 to 07:00 and about 1.2 Mbit/s from 12:00, from the same iCloud edge (`usqas5`), while a plain download on the same line got 25 Mbit/s and latency was normal. `VIDEO_PREFETCH` stays at 4.
- **`daemon status` showed nothing while waiting on iCloud.** It lists items being labeled, so during a long download it showed only "Last done N minutes ago" and looked stuck. Since 0.10.3 the labeler logs "Waiting for iCloud" after 10 s with nothing ready and "Stopped waiting for iCloud" when it moves on, and `daemon status` shows the wait.
- **Originals are too big to download.** A 4K video is 360-700 MB, and iCloud gave about 4.7 MB/s on a good day. Photos are requested at `max_dimension` and videos as Photos' 720p version (`PHVideoRequestOptionsDeliveryModeMediumQualityFormat`, about 45 MB instead of 700 MB) (85a0490, 0.5.0).
- **iCloud's speed swings.** 4.7 MB/s was typical, but it dropped to 0.2 MB/s within an hour on 21 Nov, and cloudd sent about 160 KB/s on 24 Nov. Photos exports of video originals took 17-178 s (55 s on average). Nothing in the labeler controls this; requesting ahead (below) hides most of it.
- **Downloads one at a time were slow.** Cold photos took 1.8 s each one at a time and 0.22 s each with 32 requested ahead. Requests for the next 32 photos and 4 videos are started before the current one is used (02c9f2b, 0.9.0).
- **osxphotos export without Photos returns nothing for iCloud-only items.** `photo.export()` without `use_photos_export=True` returns `[]`, and `photo.path` is `None` for them. The labeler always passes `use_photos_export=True` (aa522cc, 0.1.0).
- **A photo export could block for 120 s.** Its timeout was cut to 30 s, with the original on disk as the fallback (9a3fc94).
- **Files on disk that can't be read.** Some originals on disk are iCloud placeholders that Pillow and sips can't open, and some exports are cut short. The labeler forces a full read with `img.load()` and falls back to Photos' derivatives, largest first (1818c03, 4140c76). 281 items were labeled from a derivative; they are recorded as a normal success and never labeled again from the full image.
- **Uploads fill a small home connection.** With `threads=32` the labeler sent about 600 KB/s of photos to the LLM, most of an upload link of under 1 MB/s, and video calls on the same connection fell behind. `daemon pause --minutes N` exists for that.

## PhotoKit

- **The first run has no PhotoKit access.** The permission request is asynchronous and the status starts as not determined, so the first run falls back to the Photos export while macOS asks whether Python may use Photos (85a0490, 0.5.0).
- **Results only arrive while the run loop runs.** Requests start on the main thread, and their result handlers are only called while `NSRunLoop.runUntilDate` is pumped, in `PHOTOKIT_POLL_S` steps (`wait_for_photokit`).
- **Slow-motion videos come back as an `AVComposition`,** which has no file URL. The labeler then uses the Photos export of the original (85a0490). On 26 Nov a slow-motion video's 720p request returned a normal file, so this may depend on the video.
- **An asset's local identifier is `<uuid>/L0/001`,** built from the osxphotos uuid for `fetchAssetsWithLocalIdentifiers` and for AppleScript's `media item id`.
- **The AVAsset must outlive the request.** Its file is read after the request returns, so it is held until `exported_video` exits (02c9f2b).
- **The caption can't be written through PhotoKit.** `setAssetDescription:` is refused (`isClientEntitled` is false). Keywords and title use the private `setKeywordTitles:` and `setTitle:` (about 16 ms each), and the caption is written with one AppleScript command (02c9f2b, 0.9.0).
- **A grouped save can fail as a whole.** Each photo in it is then saved on its own, and a photo whose change still fails is written through AppleScript (02c9f2b).

## Photos.app and AppleScript

- **Photos.app's scripting can't see some items.** photoscript's `photoExists` is false for some items, which it reports as `Invalid photo id`: 26,288 such lines from 12 May to 22 Nov. 17 Shared Library photos failed this way about 1,510 times each, every cycle from 1 Jun to 1 Jul, until they left the library; a hidden burst photo is still unlabeled. Every one of these attempts first spent an LLM request, because labeling happens before writing. Writes moved to PhotoKit in 0.9.0, so this no longer blocks writes, but nothing checks before labeling.
- **Photos.app hangs with no window.** On 22 Nov 2026 (03:12-06:24 and 15:35-21:31) Photos answered every command only when it timed out after 120 s, about 30 failed writes an hour. photoscript's own retry, which quits Photos and starts it again with a script command, is what started the hung copy. A write that fails after `PHOTOS_HUNG_AFTER_S` (60 s) now force-quits Photos, opens it with `open -a`, waits `PHOTOS_RESTART_WAIT_S` (30 s) and tries once more, and photoscript's retry is off (746330d, 0.8.2).
- **A restarted Photos.app can be half broken.** On 21 Nov photoscript killed Photos during an export; the new copy answered simple calls, but every lookup by id timed out with `Invalid photo id`, 2 minutes per item for 27 minutes, until Photos was quit and opened again by hand.
- **Compiling the script waited forever.** Compiling the writer's AppleScript asks a running Photos for its scripting terms with no timeout. On 23 Nov Photos was still starting and never answered, so the first write held `_write_lock` and every worker waited. The script is now compiled with `osacompile` in a subprocess with a 60 s timeout (a173670, 0.9.1).
- **photoscript wrote every keyword list five times.** Its setters read the value back and set it again up to 5 times when it differs, and Photos returns keywords sorted, so a keyword write always "differed": 7 saves per photo, about 1 s each. The writer uses its own compiled script, and keywords and title go through PhotoKit (02c9f2b, 0.9.0). Never compare keyword lists in order.
- **Photos.app gets force-quit a lot.** Four separate code paths restart it: osxphotos after 10 failed AppleScript exports (2,818 times, about 90 a day in June), photoscript (546), the exporter (130) and the writer (165, of which 155 between 02:00 and 11:00 on 24 Nov). On 24 Nov every write after the writer's restart worked, so under 128 queued writes Photos was slow rather than hung. **Open:** the paths don't know about each other.
- **Writes fail while Photos quits.** `User canceled (-128)`, `Connection is invalid (-609)` and `AppleEvent timed out (-1712)` (37, 14 and 1 times) come from Photos quitting or being killed during a write. They are retried next cycle; 7 of those items were written later but their `metrics.db` rows still say error.
- **Photos.app must be running for AppleScript.** The writer checks with `pgrep -x Photos`, opens it with `open -a Photos` and waits 3 s (aa522cc).
- **AppleScript is single-threaded,** so AppleScript writes take `_write_lock`. PhotoKit writes don't.
- **Photos is hard to use while the labeler writes.** `daemon pause` stops exports and writes, and stops the daemon for good after an hour; `--minutes N` (1-60) pauses for a set time (1567023, 0.6.0; 467c1cf, 0.7.0).
- **A heavy write load hangs Photos.** On 27 Oct the lowercase migration wrote about 3 keywords a second while transcription exported a video every 10-30 s, and Photos stopped answering. With the migration paused, Photos answered in 0.06 s. The migration ended with "58733 items normalized, 8 failed"; it doesn't retry failed items.

## photolibraryd and the Photos database

- **Keyword saves are slow, and slower the more photos share the keyword.** photolibraryd saves one change at a time, and a save that adds or removes a keyword loads every photo that has it (the `m:` tags are on tens of thousands). One save per photo took about 1 s idle and 4-6 s each with 64 at once; 10 photos in one save took 0.45 s. `_PhotoKitSaver` puts everything waiting into one `performChangesAndWait`, up to `PHOTOKIT_BATCH_SIZE` (128) (02c9f2b, 0.9.0).
- **A stuck WAL made every save slow.** On 23 Nov `Photos.sqlite-wal` was 6.5 GB against a 5.8 GB database, and `Photos.sqlite` hadn't changed since the day before. One photolibraryd connection held a WAL read slot at frame 85,383, so SQLite couldn't copy anything newer back, and every page read searched 1.6 million WAL frames. Saves took about 1 s per photo even when idle, and labeling fell from about 1,200 to under 500 an hour. The fix: quit Photos.app, then `kill -TERM` photolibraryd (`launchctl kickstart -k` is refused by SIP). launchd starts it again on the next PhotoKit call, it copied the WAL back at once (6.5 GB to 424 KB), and saves went from 0.93 s to 0.13 s. It builds up slowly, so it looks like the labeler getting slower. Check the WAL's size and read locks before changing code: the `-shm` header has `mxFrame` at offset 16, `nBackfill` at 96 and five read marks at 100, and `fcntl F_GETLK` on bytes 123-127 says which process holds each.

## osxphotos and finding work

- **Loading the library is slow.** `PhotosDB()` took about 20 s for 120,000 photos in March, about 2.5 minutes in October, 2-5 minutes in November, and 10 minutes from a cold cache (57 s right after). With `poll_interval` at 300 s it loaded the whole library every 5 minutes (6.6-7.3 GB at peak) and almost always found nothing. The poll interval became 6 hours (e95520d), per-cycle limits rose to 2,000 photos and 200 videos (02c9f2b), and `daemon status` reads `library.json` instead of loading the library (8480fa3, 0.8.0).
- **osxphotos' SQLite belongs to the thread that opened it,** so exports run on the main thread (ed33c14).
- **Two threads opening PhotosDB at once crash.** On 0.2.1 the transcriber thread failed with `KeyError: 'CFURLCreateByResolvingBookmarkData'` (pyobjc looks CoreFoundation functions up lazily, and that isn't thread-safe) and then slept the full 6 hours. `load_photos_db()` takes a lock, and a failed load is tried again after 5 minutes (6deda3f, 0.2.2).
- **`from_date` filters by the date taken, not the date added.** Discovery sorts by `date_added` itself.
- **There is no "has no keywords" query.** Discovery loads every item and filters in Python.
- **Hidden items are never labeled** (`not p.hidden` everywhere). This was a choice, not a limit.
- **Shared Library items** export through their own path (`scopes/momentshared`): 19,761 of the 19,916 "Photos export failed, falling back to original" warnings were Shared Library originals.

## Video files and ffmpeg

- **Photos' export can be a placeholder.** For many iPhone HEVC `.MOV` files, and for every iCloud-only video whose original Photos hasn't downloaded, the export is a file of under 1 KB with no video stream. ffprobe checks every file for a video stream before it is used (61f1e40, 0.1.4). On 12 May, before that check, the same 60 videos failed every 5 minutes, about 90 times each.
- **A few files really are broken.** Of the 60 videos failing on 12 May, 57 were recovered by 61f1e40; the other 3 were an audio-only mp4 and two with damaged MP4 atoms. These are what "No usable video source" is for.
- **Old `.3gp` clips** have one decodable keyframe at 0 s, and ffmpeg's mjpeg encoder rejects their limited-range YUV. Frame extraction tries an input seek, then an output seek with `-pix_fmt yuvj420p`, then the frame at 0 s (61f1e40).
- **Clips under half a second** have no frame at the seek times. Below `SHORT_VIDEO_THRESHOLD_S` (0.5 s) one frame is taken (61f1e40).
- **Short clips** get at most one frame every `MIN_FRAME_SPACING_S` (0.5 s), so a 3 s clip gets 6 frames, not 30 (710c144).
- **A frame can be missing.** `Failed to extract frame N` (3,332 times) leaves the video labeled from fewer frames.
- **ffmpeg's errors were hidden** by `-v quiet`; with `-v error` its stderr is in the error message (61f1e40).
- **Spatial audio.** Newer iPhone videos have an `apple_apac` spatial audio track that ffmpeg picks by default and older builds can't decode. Audio is taken from the first audio track with `-map 0:a:0` (72fdc18, 0.2.0).

## Whisper and transcripts

- **LLM servers have no speech-to-text.** LM Studio and Ollama have no transcription endpoint, so the labeler runs Whisper itself: mlx-whisper large-v3 on the Mac (about 3 GB, Apple Silicon only), or the faster-whisper server in `devbox/whisper` (72fdc18, 0.2.0; c7cdc43, 0.4.0).
- **Whisper makes text up.** On 28 Oct, 540 of 699 transcripts were junk:
  - Egyptian Arabic was detected as Polish, Russian, Norwegian or Japanese, because Whisper picks one language from the first 30 s and picks at random on music; a 94 s Arabic video came out in Spanish.
  - Stock phrases appeared on music and silence: "اشتركوا في القناة" in 41 transcripts, "ترجمة نانسي قنقر", "altyazı m.k.", "Thank you for watching" (with `no_speech_prob` 0.73-0.86).
  - Some transcripts were the same words repeated.
  - A prompt describing the dialect leaked its own words into the output.

  The fix (e352ecb, 0.3.0): with `whisper_languages` set, the language is detected per 30 s window, windows where the listed languages together score below 0.5 are skipped, and each other window is transcribed in its own language. Segments are dropped for `avg_logprob` below -1.0, `compression_ratio` above 2.4, `no_speech_prob` above 0.85 (or above 0.6 with `avg_logprob` below -0.5), or text that is only phrases from `MADE_UP_PHRASES`. The thresholds were picked on 75 videos: 13 of 30 junk transcripts now give no transcript, 20 of 20 useful ones are kept, and 24 of 25 videos with no speech stay empty. Song lyrics score 0.6-0.8 `no_speech_prob` and are kept. `migrate redo-transcripts` redid 1,473 transcripts. An earlier single cutoff at `no_speech_prob` 0.5 also dropped real speech (72fdc18).
- **Arabic is folded before matching made-up phrases:** marks U+064B-0652 and U+0640 removed, and أإآ→ا, ة→ه, ى→ي.
- **`condition_on_previous_text=False`** is passed on every transcription, local and server.
- **Transcripts weren't used in labels.** Transcription first ran in its own thread. It is now part of labeling a video: the video is exported once and the transcript, cut to `MAX_TRANSCRIPT_CHARS` (3,000), goes into the merge request. If transcription fails, the video is labeled without it (c689f6e, 0.3.0).
- **The separate transcriber thread failed in bulk.** On 27-28 Oct it raised `FileNotFoundError` 1,977 times on 1,903 videos, 1,585 of them in 2 minutes, because it exported while the labeling thread was also exporting and restarting Photos. It was replaced in 0.3.0.
- **`.local` names took about 5 s per new connection** (mDNS). The Whisper client keeps one connection open (`KEEPALIVE_S` 600 s) (c7cdc43, 0.4.0).
- **The Whisper server shares a GPU.** It unloads the model after 300 s idle, and a request while another model holds the GPU can fail with a 500 (CUDA out of memory). When the server doesn't answer, new videos are labeled without a transcript and labeled videos wait for a later cycle. Live requests (`priority=live`) go ahead of waiting ones but not the one running (ef36ec9).

## LLM servers and replies

- **Images filled the context window.** Full-size images ran out of context ("failed to prepare attention ubatches"). Images are resized to `max_dimension` (1024) first (aa522cc).
- **Frames are expensive.** A frame costs about 1,856 tokens against a 20,224-token LM Studio slot, so 10 frames in one request overflowed. Each frame adds about 5 s of LLM time, so 20 or more frames passed the 90 s timeout. Videos are labeled from 30 frames in batches of 5 and one text-only merge request (710c144, 0.1.4). On a 38 s video that is 6 batches of 42-51 s and a merge of about 105 s: about 6 minutes of LLM time and 19,800 input tokens.
- **HEIC fails in LM Studio** with `400 Failed to predict`. Images are always sent as JPEG; formats Pillow can't open are converted with `sips -s format jpeg` (dcc28c7).
- **Replies have more than JSON in them.** Qwen's `<think>` blocks, ```` ```json ```` blocks anywhere in the reply, `<|channel|>` tags, and Gemma's `<start_of_turn>`/`<end_of_turn>` are stripped (e3e7493). LM Studio ignores `chat_template_kwargs.enable_thinking=false`; only editing its Jinja template turns thinking off there.
- **Bad JSON** gets one more request asking for valid JSON only (783 times). Twice-bad JSON fails the item until next cycle.
- **The merge request thought for minutes.** qwen3.5-9b's merge thought about 2,400 tokens and took 110-296 s, past the timeout, and a timeout redid the whole video. The merge is sent with `reasoning_effort="none"` (about 6 s, no thinking tokens; `/no_think`, `chat_template_kwargs` and `"low"` were ignored), and with a 600 s timeout (`LLM_MERGE_TIMEOUT`) (263b91d). A server that rejects `reasoning_effort` gets the request again without it. The `reasoning_effort` setting came later (fd2c9d0, 0.4.0).
- **The OpenAI client retries on its own.** It retries twice on timeouts, connection errors, 408, 429 and 5xx before the labeler sees an error, so one labeler attempt can be 3 requests of 90 s each. It absorbed all 1,221 HTTP 429s and 45 HTTP 408s from the local proxy on 23-26 Nov.
- **Retryable errors are retried forever.** `_label_with_retry` retries timeouts, connection errors, 429, 5xx and LM Studio's "model has crashed" 400 with backoff from 5 s to 300 s and no limit on attempts. One video was tried 1,818 times from 30 Oct to 10 Nov, about every 9 minutes, and since 0.3.0 labeled videos one at a time, nothing else ran (4,382 timeout and 2,504 connection-error retries on a LAN server overall). **Open.**
- **Account and server problems were counted as item failures.**
  - 402 "requires more credits, or fewer max_tokens" 13,921 times on 74 items (5-8 Jun): the labeler never sets `max_tokens`, so the provider reserved 64,000-65,536 tokens a request.
  - 404 "No endpoints found that support image input" 35 times: the configured model had no image input.
  - 400 "No models loaded" 230 times, and "Model reloaded" / "Model is unloaded" 21 times: LM Studio had no model loaded.
  - 400 "Context size has been exceeded" twice.

  Each was recorded against the item and tried again every cycle. **Open:** these should stop the queue and say why.
- **Servers come and go.** 503 "Loading model" (64) and 502 "overloaded" (9) are retried. A retry can go to another server in the pool (db2fe52). Before c94c657 (0.1.0) there was no LLM timeout and the daemon couldn't shut down while a request hung; requests now time out after 90 s and in-flight futures are cancelled on stop.
- **The content filter cut replies off.** gpt-6.1-sol copies the text of song lyrics and book pages into `ocr_text`, and OpenAI's filter stops the reply partway (`finish_reason="content_filter"`), so the JSON never parses: 637 JSON errors on 36 items from 23 to 25 Nov, the same items every cycle. A cut-off reply is now asked for again with `ocr_text` empty and no quoted text, which worked for all 32 tried (40d82d6, 0.10.0). Rows where the filter cut a reply off get `content_filtered=1` (66 so far, all labeled on the second try). If the second reply is cut off too, `ContentFilteredError` is recorded and discovery skips the item; that hasn't happened yet.
- **Empty replies.** `'NoneType' object has no attribute 'strip'` (17 times): the reply's `content` was `None`. `finish_reason` isn't logged for these, so a refusal can't be told from an empty answer. **Open.**

## Keywords

- **The model tag.** Every labeled item gets `m:` + the first 8 hex digits of the sha256 of the model name (ef09fed, April 2026), so labels from a model no server uses any more can be found. The hash can't be turned back into a name, so `~/.image-labeler/model-tags.json` maps each tag to its model (bee68f0, 0.8.1).
- **62,141 photos and 13 videos had labels from before the model tag existed,** and normal runs never relabeled them, because they had no `m:` tag of an old model. Since 0.10.0 (9d65cab) an item with keywords and no `m:` tag counts as labeled by another model. They were relabeled from 25 Nov.
- **Relabeling drops keywords typed by hand.** `write_metadata` writes the new labels, the model and video tags, and the transcript; every other keyword is replaced. That was always true for items relabeled from an old model, and since 0.10.0 it is also true for items with keywords and no `m:` tag, which 0.1.4 (bb1f206) had left alone in case the keywords were typed by hand. Nothing is backed up first. The lowercase migration's backups from 27 Oct 2026 (`~/.image-labeler/backups/keywords-*.jsonl`) are the only record of keywords from before the November relabel. **Open.**
- **The video settings tag.** Videos get `v:` + the first 8 hex digits of the sha256 of `frames=N,batch=M` (710c144), so videos labeled with other frame settings can be found. When this was added, `init` had saved `video_frames: 5` into every config, so every video labeled that way would have been relabeled for nothing; 5 frames in one request counts as current (bc5a4c9).
- **Photos keeps each casing as its own keyword.** 13,557 keywords had more than one casing. Every keyword, `ocr:` and `trans:` included, is written lowercase and duplicates are dropped (9126446, 0.2.0). `migrate normalize-keywords` fixed 58,733 items at about 0.2 s each, with a JSONL backup.
- **Photos' Info window splits keywords at commas.** Clicking into the keyword field on the Mac split one transcript into 8 keywords; 21,128 keywords had commas. Commas between digits are removed (3,000 becomes 3000) and other commas become spaces (884dd2e, 0.2.1).
- **Labeling must keep transcripts.** A relabel keeps `trans:` keywords, a video whose only keywords are `trans:` still counts as unlabeled (72fdc18), and adding a transcript to a labeled video keeps its `m:`, `v:` and `ocr:` keywords (c689f6e).
- **The caption is written before the keywords,** so an item never has its new `m:` tag next to an old caption (02c9f2b).
- **Thirteen videos had keywords and no model tag** in October, possibly typed by hand. They were left out of the October video reindex; since 0.10.0 they are relabeled like the 62,141 photos above.

## metrics.db

- **It is also the skip list.** `get_permanent_failure_uuids` skips items whose row says error with "No usable video source" or `content_filtered=1`. To retry one, delete its row from `item_metrics`; deleting the file retries everything. It has one row per item (`UNIQUE(uuid)`, an upsert; 9a3fc94), so a later success replaces an error.
- **Written items were marked failed.** One grouped PhotoKit save finishes up to 128 items at once, and each then writes its row at the same moment. SQLite's default 5 s wait for the write lock ran out, and on 25 Nov 17 of 71 photos in one save were logged as "database is locked" although their labels were written (34 rows in all, 24-25 Nov). Connections wait up to 60 s (`BUSY_TIMEOUT_S`), and a row that still can't be saved logs a warning instead of failing the item (05cfea0, 0.10.1). **Open:** those 34 rows, and 7 from AppleScript errors, still say error although the items are labeled, so error counts are too high.
- **The per-item failure limit can't trip.** `MAX_ITEM_FAILURES` (10) is counted per batch, and an item runs once per batch, so the log's 46,791 "failed (1/10)" lines never went past 1. If it ever fired, `MaxFailuresExceeded` isn't caught and the daemon would exit (launchd starts it again). **Open.**
- **Columns are added to old databases** with `_ensure_column` (908060c). Hourly stats are stored as UTC ISO times so the dashboard shows local time (72f58ff).

## The daemon, launchd and Homebrew

- **Stopping cut writes off.** launchd's default 20 s exit timeout could stop the daemon in the middle of writing an item. The plist sets `ExitTimeOut` to 150 s (5656cd7, 0.4.0). The signal handler raises `KeyboardInterrupt` so blocking calls stop waiting, and a second signal exits at once (c938a7f).
- **The loop could run without sleeping.** A cycle that reaches its per-cycle limit starts the next one at once, but only when it labeled something, so a cycle where every item fails sleeps (bb1f206).
- **A daemon with no log line for a while may be waiting on a macOS prompt.** After the 0.2.2 upgrade it sat at 0% CPU for 1 h 45 min on "python3.11 would like to access data from other apps" (`kTCCServiceSystemPolicyAppData`). `log show --predicate 'subsystem == "com.apple.TCC" AND eventMessage CONTAINS "AUTHREQ_PROMPTING"'` shows it.
- **Upgrading under a running daemon breaks it.** `brew upgrade` deletes the old Cellar folder, and a running daemon failed about 1,600 videos with `FileNotFoundError` in two minutes. Stop the daemon first. The plist uses `/opt/homebrew/opt/icloud-image-labeler/...`, not the versioned Cellar path (164d0f5, 0.2.1).
- **`brew upgrade` isn't always done the first time.** Right after the tap update, the first `brew upgrade` can end with only Homebrew's support notice and leave the old version; the second one builds it. It then prints `Failed changing dylib ID of .../jiter/...so` (`MachO::HeaderPadError`), which is harmless for a Python extension module. Check with the brew Python from outside the checkout (`cd /` first), since the checkout's `labeler` would be imported instead.
- **`daemon start` drops `--reindex`.** It writes a plist without it, so a reindex run is restarted by writing the plist from `daemon._generate_plist()` with `--reindex` appended.
- **GitHub's API sometimes failed on writes** with empty HTTP 500s: `gh release create` created nothing three times, while `git push` worked. Creating the tag first through the API and then `gh release create --verify-tag` worked; the tap was updated by hand when its workflow failed the same way. The formula's version sed once matched zero digits and wrote `0.1.3--version` into the test (b518c8a).
- **`config set` and `config show` printed API keys.** They show `<hidden>` (f40b6ca, 0.4.1); a key printed before that was rotated.
- **`--threads` was ignored** for the single-server config, which copied the global `threads` (6488cb9).
- **Ten daemon starts have no shutdown line before them** (June to November): the daemon was killed, crashed, or the Mac restarted. 47 of 2,847 `run_metrics` rows have no `finished_at`.

## Memory and speed

- **The autorelease pool was never drained.** Each exported photo kept its `PHAsset`, `CGImage` and `IOSurface` (about 3.6 MB), so the daemon reached 19 GB after 5,000 photos and the Mac swapped until everything was several times slower. Every PhotoKit export and write runs inside `objc.autorelease_pool()`, and the daemon stays around 200 MB (02c9f2b, 0.9.0).
- **The library stayed in memory while the daemon slept.** Every `PhotoInfo` keeps a reference to its `PhotosDB`. Each cycle runs in `_process_one_cycle` with `gc.collect()` after it (51fe517), which took idle memory from 2.6 GB to 920 MB.
- **Items held their LLM slot while waiting to write.** An item gives its slot back before it writes, with `WORKERS_PER_LLM_SLOT` (4) worker threads per slot, so items waiting to write end up in the same PhotoKit save (02c9f2b).
- **Videos were labeled one at a time,** about 67 s each; they are labeled in parallel since 0.4.0 (5656cd7).
- **Measured throughput** with gpt-6.1-sol and `threads=32` (no 429s at 32): 57 photos a minute (about 3,400 an hour) at 209 MB, against 450-700 an hour with 0.8.2 and the stuck WAL. Videos ran at about 10 a minute, with about 86 s of LLM time each. LLM time per photo went from about 7.5 s at 16 threads to 9.4 s at 32. Exporting several videos in one AppleScript request didn't help.

## Still open

What 0.10.2 still does that a rewrite shouldn't:

1. Retryable errors are retried forever inside a batch, and every other error is tried again every cycle with no limit. Nothing counts attempts across runs, and nothing tells anyone when an item or a server is stuck.
2. Server and account errors (out of credits, no image input, no model loaded, context exceeded) count against the item instead of stopping the queue.
3. `max_tokens` is never set.
4. The LLM request runs before it is known that the item can be read and written.
5. A relabel drops keywords typed by hand, with no backup.
6. `MAX_ITEM_FAILURES` can't trip, and `MaxFailuresExceeded` would end the daemon if it did.
7. Rows stay "error" after the item was written (41 rows on 26 Nov).
8. Items labeled from a derivative count as a full success and are never labeled again from the full image.
9. Empty replies don't log `finish_reason`.
10. Four code paths force-quit Photos.app without knowing about each other.
11. A truly broken video that is only in iCloud and that PhotoKit gives nothing for is now tried every cycle (one PhotoKit request each time) rather than skipped.

## Timeline of the worst episodes

| When | What happened | Fixed by |
|---|---|---|
| 11 May | 35 × 404: the configured model had no image input | switching model |
| 12 May 01:42-11:49 | The same 60 videos failed every 5 minutes on Photos' placeholder exports (about 5,400 errors) | 61f1e40 at 12:17 |
| 1 Jun-1 Jul | About 25,600 `Invalid photo id` on 17 Shared Library photos, each after an LLM request; osxphotos restarted Photos.app about 90 times a day | the photos leaving the library |
| 5-8 Jun | 13,921 × 402 out of credits on 74 items | switching server |
| 8 Jun 13:59-14:13 | 225 × "No models loaded" right after switching to LM Studio | loading a model |
| 14-16 Jun, 23-25 Jun, 2-10 Oct, 13-24 Oct | The LAN server timed out or was unreachable; retries reached attempt 490 and no item finished for days | open |
| 27 Oct | Photos hung; every iCloud-only video export returned nothing and 38 videos were marked permanent. The lowercase migration and the transcriber ran beside the daemon and hung Photos again | 777d1ca; pausing the migration |
| 27-28 Oct | The transcriber thread: 1,977 `FileNotFoundError`, 1,585 of them in 2 minutes; a `brew upgrade` under the running daemon failed about 1,600 videos | 0.3.0; stopping the daemon before upgrades |
| 28 Oct | 540 of 699 transcripts were made up | e352ecb (0.3.0) |
| 30 Oct-10 Nov | One video retried 1,818 times; nothing else ran | open |
| 22 Nov | Photos.app hung with no window for most of the day | 746330d (0.8.2) |
| 23 Nov | Stuck WAL (6.5 GB); compiling the AppleScript waited forever; the daemon had grown to 19 GB | killing photolibraryd; a173670; 02c9f2b |
| 23-25 Nov | The content filter cut off 36 items' replies every cycle | 40d82d6 (0.10.0) |
| 24 Nov | Five stuck iCloud videos took about 15 minutes each; 155 Photos.app force-quits by the writer | 345df40 (0.9.2) |
| 24-25 Nov | 34 written photos marked failed with "database is locked" | 05cfea0 (0.10.1) |
| May-26 Nov | 130 videos skipped forever as "No usable video source" because iCloud hadn't sent them | 6e30262 (0.10.2) |
| 26 Nov midday | iCloud sent about 0.3 MB/s; 4 of the first 40 videos timed out and lost their partial downloads, and one failed 720p download held everything up for 14 minutes | 0.10.3 |

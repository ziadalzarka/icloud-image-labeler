# Codebase Concerns

**Analysis Date:** 2026-03-19

## Tech Debt

**LLM Response Parsing Fragility:**
- Issue: Response parsing relies on regex stripping of `<think>` blocks and markdown fences before JSON parsing. Qwen models can produce malformed outputs that the single retry doesn't always recover from.
- Files: `labeler/llm.py` (lines 42-50)
- Impact: Failed JSON parses after retry cause items to fail processing completely, even though the LLM may have generated valid labels in the response.
- Fix approach: Implement more robust parsing with fallback to extracting JSON via regex patterns, or use structured output modes if the LLM supports them. Consider implementing a secondary retry with temperature adjustment before giving up.

**Thread-Local Database Connections Without Cleanup:**
- Issue: `labeler/metrics.py` uses `threading.local()` to manage SQLite connections, but connections are never explicitly closed. Long-running processes (daemon mode) may accumulate unclosed connections.
- Files: `labeler/metrics.py` (lines 11-20)
- Impact: Memory leak in daemon mode; potential resource exhaustion over time. SQLite WAL files may not be cleaned up properly.
- Fix approach: Add explicit connection cleanup on shutdown. Implement a context manager or register atexit handler to close connections. Monitor daemon logs for connection count growth.

**Export Timeout Not Enforced Consistently:**
- Issue: Photo exports use `timeout=30` but video exports use `timeout=300`. No upper bound exists if export hangs indefinitely despite timeout parameter (some osxphotos versions may ignore timeout).
- Files: `labeler/exporter.py` (lines 49, 103)
- Impact: Hung exports can block batch processing indefinitely even with signal handlers installed, because timeout is advisory not guaranteed.
- Fix approach: Wrap export calls with explicit thread timeouts using `concurrent.futures` or implement subprocess-level timeout for photo exports.

**Max Item Failures Hard-Coded to 10:**
- Issue: `MAX_ITEM_FAILURES` is globally defined as 10 with no configuration option.
- Files: `labeler/processor.py` (line 18)
- Impact: Users can't adjust tolerance for flaky items without code changes. Legitimate temporary failures (transient network issues, Photos.app lag) may prematurely stop processing.
- Fix approach: Add `max_item_failures` to config.json with sensible default. Expose via CLI flag.

**Refresh Interval Hard-Coded to 6 Hours:**
- Issue: `refresh_interval=21600` (6 hours) is hard-coded when calling `process_batch()` in `cli.py` but configurable at the batch level.
- Files: `labeler/cli.py` (line 72)
- Impact: Long-running daemon can take 6 hours to pick up newly added photos. Users have no way to customize refresh frequency.
- Fix approach: Add `refresh_interval` to config.json (default 21600). Pass from `_run()` to `process_batch()`.

## Known Bugs

**JSON Parse Retry Mutates Messages List:**
- Symptoms: If JSON parsing fails and retry is triggered, the original `messages` list is mutated by appending assistant/user corrections. Subsequent retries (if any) will have different message history than intended.
- Files: `labeler/llm.py` (lines 71-72)
- Trigger: Model returns malformed JSON on first try but correct JSON on second try.
- Workaround: None; users must re-run the batch.

**Incomplete Frame Extraction Not Reported:**
- Symptoms: `export_video_frames_as_base64()` logs warnings for individual frame failures but doesn't raise an error if some frames fail to extract. If ffmpeg silently produces zero frames, the function returns empty list and later raises a vague "No frames extracted" error.
- Files: `labeler/exporter.py` (lines 154-155)
- Trigger: ffmpeg partial failure (e.g., codec unsupported for later frames but works for early frames).
- Workaround: Check logs for frame extraction warnings; re-run with different video.

**Daemon Restart With Modified Config Not Reflected:**
- Symptoms: If user edits `~/.image-labeler/config.json` while daemon is running, config is only loaded once at startup. Changes won't take effect until daemon is restarted.
- Files: `labeler/daemon.py`, `labeler/cli.py` (config is loaded once at startup)
- Trigger: User modifies config and expects changes to apply immediately.
- Workaround: Run `icloud-image-labeler daemon restart` after editing config.

## Security Considerations

**API Key Stored in Plain Text:**
- Risk: `~/.image-labeler/config.json` contains API key in plain text. Credentials for cloud LLM providers are readable by any user on the machine.
- Files: `labeler/config.py`, `~/.image-labeler/config.json` (not in repo but created at runtime)
- Current mitigation: Config file is created with user-only permissions (0600) via Python's default file creation mode.
- Recommendations: Document credential security best practices in README. Consider using macOS Keychain integration via `keyring` library for sensitive values. Warn users if API key is present in environment variables (currently not validated).

**Base64 Image Data Passed in Messages:**
- Risk: Entire base64-encoded images are sent to LLM in user messages. If LLM API logs requests, image data is permanently stored on external servers.
- Files: `labeler/llm.py` (lines 94-95, 113-115)
- Current mitigation: None. Images are base64-encoded but sent as-is.
- Recommendations: Document this behavior clearly. For privacy-conscious users, suggest self-hosting LLM via LM Studio. Consider adding image hash verification before sending to detect already-processed images.

**No Validation of LLM Responses:**
- Risk: LLM can return arbitrary strings in `ocr_text` field, which is then appended as a keyword prefixed with `ocr:`. Malicious or broken LLM could return very long strings that exhaust Photos.app metadata limits.
- Files: `labeler/writer.py` (lines 38-39)
- Current mitigation: None. OCR text is written as-is.
- Recommendations: Validate response schema; enforce max length on ocr_text (e.g., 500 chars) before appending to keywords. Log warnings if response seems malformed.

## Performance Bottlenecks

**Sequential Video Processing Blocks Entire Batch:**
- Problem: Videos are processed strictly sequentially on main thread (line 361 in `processor.py`). If batch contains 100 videos, processing time is sum of all video durations.
- Files: `labeler/processor.py` (lines 359-378)
- Cause: Photos.app metadata writes must be serialized (`_write_lock`), but main thread video export/LLM/write could be parallelized.
- Improvement path: Extract frames for all videos in parallel, then label/write sequentially. This requires refactoring to separate export phase from labeling phase for videos.

**Image Resizing Happens on Main Thread:**
- Problem: Photo export happens on main thread (SQLite thread binding), but image resizing and base64 encoding could be moved to worker threads.
- Files: `labeler/exporter.py` (lines 79-88), `labeler/processor.py` (lines 318-320)
- Cause: Export is on main thread to satisfy osxphotos SQLite requirements, but postprocessing isn't SQLite-bound.
- Improvement path: Move resize and base64 encode to worker threads. Only export on main thread.

**No Batch Size Optimization:**
- Problem: Photos are always exported fully regardless of max_dimension setting. Large 12MP photos are exported at full resolution, then resized in memory, wasting I/O.
- Files: `labeler/exporter.py` (no downsampling during export)
- Cause: osxphotos export doesn't support size hints. PIL resize is done in Python after full export.
- Improvement path: Use ffmpeg-based image resizing during export or accept larger batch times for high-resolution photos.

**No Early Exit When Photos.app Becomes Unresponsive:**
- Problem: If Photos.app hangs during metadata write, timeout is only enforced by thread-level join (5s in shutdown, line 345), not by PhotoScript calls themselves.
- Files: `labeler/writer.py` (lines 24-47)
- Cause: PhotoScript is AppleScript automation with no timeout support.
- Improvement path: Wrap PhotoScript calls with subprocess timeout or use lower-level AppleScript with explicit timeout. Monitor Photos.app responsiveness and bail out if stuck.

## Fragile Areas

**Photo Export Fallback Chain Vulnerable to Partial Failures:**
- Files: `labeler/exporter.py` (lines 45-77)
- Why fragile: Export attempt → original fallback → derivatives fallback → raise error. Each step masks failures of previous steps. If export succeeds but file is truncated (caught at line 65 with `img.load()`), fallback to original assumes it exists and is valid. If original also fails silently, we fall back to derivatives. If all fail, error message is generic.
- Safe modification: Log each fallback attempt with the reason (e.g., "Export succeeded but file truncated: X bytes"). Test with known truncated files. Add explicit validation that fallback paths exist before attempting to open.
- Test coverage: No unit tests for export fallback logic. Manually verified with iCloud-only files but edge cases (corrupted exports, missing derivatives) are untested.

**Retry Loop Assumptions About Error Transience:**
- Files: `labeler/processor.py` (lines 27-36, 123-141, 197-213)
- Why fragile: `_is_retryable_error()` checks for 5xx status codes and "crashed" string in 400 errors. If LLM returns 400 for other reasons (bad image format), it will be retried indefinitely until MAX_ITEM_FAILURES is hit.
- Safe modification: Log the exact error before retry decision. Add telemetry on retry reasons to identify patterns. Separate transient errors (500) from client errors (400) more strictly.
- Test coverage: No tests for retry logic. Manual verification only with LM Studio crashes.

**In-Flight Futures Draining on Shutdown Doesn't Guarantee Safety:**
- Files: `labeler/processor.py` (lines 336-354)
- Why fragile: When shutdown is requested, code cancels futures and waits 5 seconds for them to finish. If futures are mid-metadata-write via PhotoScript, cancellation doesn't stop AppleScript execution—it just abandons the thread. Metadata may be partially written.
- Safe modification: Use a graceful draining approach: signal shutdown, wait for in-flight futures to complete naturally, then cancel any that still haven't after timeout. Test graceful shutdown by sending SIGTERM during active metadata writes.
- Test coverage: No integration tests for shutdown behavior. Manual testing required.

**Metrics Recording Upsert Silently Overwrites on UUID Collision:**
- Files: `labeler/metrics.py` (lines 96-122)
- Why fragile: If same UUID is processed twice (e.g., manual re-run), metrics are overwritten without warning. Original error reason is lost. No log message when upsert occurs.
- Safe modification: Log a warning when upsert happens. Consider adding a conflict resolution strategy (e.g., keep first error, skip on status=="error").
- Test coverage: No tests. Manually tested with duplicate UUIDs but behavior not verified.

## Scaling Limits

**SQLite Metrics Database Unoptimized for Large Datasets:**
- Current capacity: Single SQLite database. WAL mode enabled but no partitioning or archival strategy.
- Limit: After processing millions of items over years, queries will slow down. Datasette frontend may become sluggish.
- Scaling path: Implement log rotation/archival (e.g., move old records to separate database or parquet files annually). Add VACUUM command to optimize database size.

**No Rate Limiting on Refresh Discovery Queries:**
- Current capacity: `_maybe_refresh()` re-queries all photos every 6 hours. If batch is very large, this query can lock the Photos library.
- Limit: In a setup with 100k+ photos, refresh query can hang for minutes, blocking batch progress.
- Scaling path: Implement incremental refresh (track last refresh UUID, only query for newer items since then). Use pagination to avoid large result sets.

**Thread Pool Backpressure at Fixed Thread Count:**
- Current capacity: Default 4 threads for photos. No adaptive threading based on system load.
- Limit: On high-end Macs with 16+ cores, 4 threads are underutilized. On low-end, 4 threads may cause CPU thrashing.
- Scaling path: Add auto-tuning based on system CPU count (e.g., threads = max(2, cpu_count // 2)). Add config option `threads="auto"`.

## Dependencies at Risk

**osxphotos Fragile to Photos.app API Changes:**
- Risk: macOS updates can break osxphotos Photos library queries. Library structure changes between major macOS versions.
- Impact: Batch discovery could fail silently (returns empty list) or with cryptic errors.
- Migration plan: Monitor osxphotos issues/releases. Pin to tested versions in pyproject.toml. Add fallback to direct SQLite querying of Photos library if osxphotos fails.

**PhotoScript Blocked by Photos.app Unresponsiveness:**
- Risk: PhotoScript is AppleScript automation. If Photos.app hangs or is updating library, PhotoScript calls hang indefinitely.
- Impact: Metadata writes can block indefinitely, causing daemon to appear frozen.
- Migration plan: Consider fork/alternative to PhotoScript if it doesn't support timeouts. Implement watchdog to detect hung metadata writes and forcibly kill Photos.app process (nuclear option). Document best practices to keep Photos.app responsive (disable sync during run).

**ffmpeg Optional But No Fallback:**
- Risk: ffmpeg or ffprobe not installed, dependency check runs at startup and exits hard.
- Impact: User can't run tool if ffmpeg missing, even if only processing photos.
- Migration plan: Make ffmpeg optional (check only when videos are queued). Provide clear install instructions with fallback suggestions.

## Missing Critical Features

**No Resume Capability for Interrupted Batches:**
- Problem: If daemon is killed mid-batch, all progress is lost. No way to resume from last item.
- Blocks: Users can't safely deploy daemon in production without risk of re-processing large backlog.
- Workaround: Use `--limit` to process in smaller chunks, then re-run full batch. But this doesn't track which items were processed.
- Priority: High

**No Duplicate Detection for Same-Day Re-runs:**
- Problem: If user runs `icloud-image-labeler run --days 1` twice in same day, photos labeled on first run will be skipped (good), but there's no log/report showing which items were already done.
- Blocks: Users can't easily verify that re-runs are idempotent or understand why metrics show fewer items processed on second run.
- Workaround: Check metrics database via Datasette; not user-friendly.
- Priority: Medium

**No Image Hash Validation to Prevent Re-processing:**
- Problem: If photo is moved between libraries or re-imported, same image could be labeled twice (different UUID).
- Blocks: Can't consolidate duplicate work. Metrics will count duplicates as separate items.
- Workaround: None.
- Priority: Low (edge case)

## Test Coverage Gaps

**No Unit Tests for Core Logic:**
- Untested area: Retry logic, error classification, response parsing, metrics recording
- Files: `labeler/processor.py`, `labeler/llm.py`, `labeler/metrics.py`
- Risk: Regressions in retry behavior, parsing edge cases, or metrics accuracy go undetected. Manual testing is error-prone.
- Priority: High

**No Integration Tests for Export/LLM/Write Pipeline:**
- Untested area: Photo export with fallback chain, LLM request/response cycle, metadata write to Photos.app
- Files: `labeler/exporter.py`, `labeler/llm.py`, `labeler/writer.py`
- Risk: Changes to export logic can silently break fallback behavior. LLM response parsing changes could miss edge cases. PhotoScript calls may fail silently.
- Priority: High

**No Daemon Lifecycle Tests:**
- Untested area: Daemon start/stop/restart, graceful shutdown, config reload
- Files: `labeler/daemon.py`, `labeler/cli.py` (daemon subcommand)
- Risk: Daemon may not shut down cleanly, may not start properly after manual plist edits, may not handle signal handlers correctly.
- Priority: Medium

**No UI/UX Tests for Init Wizard:**
- Untested area: Interactive setup, model selection, error handling in wizard
- Files: `labeler/init.py`
- Risk: Wizard could become unusable if prompts are reordered or logic changes. Connection testing could timeout without user feedback.
- Priority: Low (wizard is simple)

---

*Concerns audit: 2026-03-19*

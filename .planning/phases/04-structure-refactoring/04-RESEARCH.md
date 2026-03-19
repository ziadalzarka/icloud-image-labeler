# Phase 4: Structure Refactoring - Research

**Researched:** 2026-03-19
**Domain:** Python function decomposition, control flow flattening, constant extraction
**Confidence:** HIGH

## Summary

Phase 4 is a pure code restructuring phase -- no new libraries, no behavior changes, no architectural shifts. The work is entirely about breaking large functions into smaller ones, flattening deeply nested control flow with guard clauses, and replacing magic literals with named constants.

The codebase is 1715 LOC across 14 modules. Three modules require significant work: `processor.py` (479 lines, containing `process_batch` at 220+ lines with complexity 26), `cli.py` (246 lines, with `main()` at 92 lines and `_run()` at complexity 11), and `exporter.py` (209 lines, with two 60-90 line functions containing 3+ nesting levels). The remaining modules (`llm.py`, `writer.py`, `discovery.py`, `config.py`, `daemon.py`, etc.) are already well-structured with short, focused functions.

**Primary recommendation:** Decompose the three target modules one at a time (processor.py first -- it is the most complex), extracting helpers with descriptive names, flattening nesting with guard clauses, and pulling magic literals to module-level constants. Verify `ruff check` passes after each module.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STRC-01 | Long functions in `processor.py` decomposed into focused helpers | `process_batch` (220+ lines, C901=26, PLR0912=20 branches, PLR0915=112 statements) and `_maybe_refresh` (32-line closure) are the primary targets. See Decomposition Map below. |
| STRC-02 | Long functions in `cli.py` decomposed into focused helpers | `main()` (92 lines, PLR0915=56 statements) and `_run()` (C901=11) need decomposition. See Decomposition Map below. |
| STRC-03 | Long functions in `exporter.py` decomposed into focused helpers | `export_photo_as_base64` (~60 lines, nested try/if/if) and `export_video_frames_as_base64` (~90 lines, nested loop). See Decomposition Map below. |
| STRC-04 | Long functions in remaining modules decomposed where needed | All other modules already have short, focused functions. `metrics.py` has `record_item` with many params but the body is a single SQL call -- not a decomposition candidate. No action needed. |
| STRC-05 | Deep nesting replaced with guard clauses / early returns | Identified in `exporter.py` (export fallback chain at 3+ levels), `processor.py` (photo loop body at 4+ levels), and `cli.py` (`_run` override chain). |
| STRC-06 | Magic numbers and strings extracted into named constants | Full inventory below: 15+ magic literals across the three target modules. |
</phase_requirements>

## Standard Stack

No new libraries needed. This phase uses only existing tooling.

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| Ruff | (already configured) | Lint + format validation after each change | Already in pyproject.toml; PLR rules will validate complexity reduction |

### Ruff Complexity Rules (Currently Ignored)

The following rules are currently in the `ignore` list in `pyproject.toml`:

| Rule | Description | Current Violations |
|------|-------------|--------------------|
| PLR0912 | Too many branches (>12) | `process_batch` has 20 |
| PLR0915 | Too many statements (>50) | `process_batch` has 112, `main()` has 56 |
| PLR0913 | Too many arguments (>5) | Multiple functions -- NOT a Phase 4 concern |

**Important:** PLR0912 and PLR0915 should be un-ignored from `pyproject.toml` at the END of this phase (after all decomposition is complete) to prevent regression. PLR0913 (too many arguments) should remain ignored -- it is about function signatures, not structure, and changing it would alter public APIs.

C901 (McCabe complexity) is already active and shows:
- `process_batch`: complexity 26 (limit 10)
- `_run`: complexity 11 (limit 10)

## Architecture Patterns

### Pattern 1: Extract-and-Delegate Decomposition

**What:** Break a large function into a coordinator that calls focused helpers.
**When to use:** Function exceeds ~30 lines of logic or has multiple responsibilities.

```python
# BEFORE: monolithic function
def process_batch(items, ...):
    # 220 lines doing: setup, photo loop, video loop, metrics

# AFTER: coordinator delegates to focused helpers
def process_batch(items, ...):
    photos, videos, tracker, run_id = _init_batch(items, ...)
    photos_ok, photos_fail = _process_photos(photos, tracker, ...)
    videos_ok, videos_fail = _process_videos(videos, tracker, ...)
    _finalize_batch(run_id, photos_ok, photos_fail, videos_ok, videos_fail)
```

### Pattern 2: Guard Clause Flattening

**What:** Replace nested if/else with early returns to reduce indentation.
**When to use:** 3+ levels of nesting, especially try/if/if chains.

```python
# BEFORE: deeply nested
def export_photo_as_base64(photo, max_dimension=1024):
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = photo.export(tmpdir, ...)
        if exported:
            export_path = exported[0]
        elif photo.path and Path(photo.path).exists():
            export_path = photo.path
        else:
            export_path = None
        img = None
        if export_path:
            try:
                img = _open_image(export_path, tmpdir)
            except Exception:
                img = None
        if img is None:
            derivatives = photo.path_derivatives
            if derivatives:
                img = _open_image(derivatives[0], tmpdir)
            else:
                raise RuntimeError(...)

# AFTER: guard clauses + helper
def _resolve_export_path(photo, tmpdir):
    """Try export, then original, then None."""
    exported = photo.export(tmpdir, use_photos_export=True, timeout=PHOTO_EXPORT_TIMEOUT)
    if exported:
        return exported[0]
    if photo.path and Path(photo.path).exists():
        logger.warning(...)
        return photo.path
    return None

def _open_or_fallback(photo, export_path, tmpdir):
    """Open from export path, falling back to derivatives."""
    if export_path:
        try:
            img = _open_image(export_path, tmpdir)
            img.load()
            return img
        except Exception as e:
            logger.warning(...)
    derivatives = photo.path_derivatives
    if not derivatives:
        raise RuntimeError(...)
    return _open_image(derivatives[0], tmpdir)
```

### Pattern 3: Config Override Extraction

**What:** Replace repetitive `args.X if args.X is not None else cfg[X]` with a helper.
**When to use:** `_run()` in cli.py has 10+ override lines.

```python
def _resolve_config(args, cfg):
    """Merge CLI args over config defaults. Returns resolved dict."""
    def _pick(attr, key):
        val = getattr(args, attr)
        return val if val is not None else cfg[key]

    resolved = {
        "base_url": args.base_url or cfg["base_url"],
        "api_key": args.api_key or cfg["api_key"],
        "model": args.model or cfg["model"],
        "limit": _pick("limit", "limit_per_cycle"),
        "days": _pick("days", "days"),
        # ... etc
    }
    # Handle write/dry-run special case
    resolved["write"] = cfg["write"]
    if args.write is True:
        resolved["write"] = True
    elif args.dry_run is True:
        resolved["write"] = False
    return resolved
```

### Pattern 4: Argparse Builder Extraction

**What:** Move argparse subcommand setup into dedicated functions.
**When to use:** `main()` in cli.py spends 60+ lines on parser construction.

```python
def _build_run_parser(subparsers):
    """Add the 'run' subcommand and its arguments."""
    p = subparsers.add_parser("run", help="Process unprocessed media")
    p.add_argument("--limit", type=int, default=None)
    # ...
    return p

def _build_parser():
    """Build the complete argument parser."""
    parser = argparse.ArgumentParser(...)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init", help="Interactive first-run setup wizard")
    run_parser = _build_run_parser(subparsers)
    _build_daemon_parser(subparsers)
    _build_config_parser(subparsers)
    _build_metrics_parser(subparsers)
    return parser, run_parser
```

### Anti-Patterns to Avoid

- **Decomposing for the sake of it:** Don't extract 3-line helpers. The goal is ~30 lines of *logic*, not 30 lines total. A function that is 40 lines but all sequential and single-purpose is fine.
- **Breaking data flow:** When extracting from `process_batch`, be careful with shared mutable state (`processed`, `photos_ok`, etc.). Use return values, not shared mutable closures.
- **Renaming during restructuring:** Phase 5 handles naming. Don't rename existing functions/variables in Phase 4 -- only name NEW helpers descriptively.
- **Over-extracting constants:** `0` and `1` used as indices, loop counters, or boolean-like values are NOT magic numbers. Only extract literals that carry domain meaning.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Complexity checking | Manual line counting | `ruff check --select C901,PLR0912,PLR0915` | Objective measurement, catches regressions |
| Format preservation | Manual whitespace fixes | `ruff format` | Already configured, run after each change |

## Common Pitfalls

### Pitfall 1: Breaking Closure State in process_batch
**What goes wrong:** `_maybe_refresh` is a closure that mutates `last_refresh`, `total`, `photos`, `videos`, `seen_uuids` from the enclosing scope. Extracting it as a standalone function requires passing all these as arguments or using a state object.
**Why it happens:** Python closures with `nonlocal` bindings are tricky to extract.
**How to avoid:** Keep `_maybe_refresh` as a method on a batch-state dataclass, or pass a mutable state dict. The simplest approach: create a `_BatchState` dataclass that holds all the mutable counters, and pass it through.
**Warning signs:** `nonlocal` keyword, mutation of outer-scope variables.

### Pitfall 2: Changing Behavior During Restructuring
**What goes wrong:** Subtly altering error handling, retry logic, or timing while decomposing.
**Why it happens:** When moving code into a new function, it is easy to miss a `continue`, `break`, or `raise` that had special meaning in the original loop context.
**How to avoid:** Each extracted helper should handle exactly one responsibility. Control flow changes (continue/break/raise) must be preserved as return values that the caller acts on.
**Warning signs:** Any `try/except` block that changes shape during extraction.

### Pitfall 3: Thread Safety Regression
**What goes wrong:** `process_batch` carefully manages thread pool lifecycle, in-flight futures, and shutdown signals. Decomposition could separate the submit and collect phases incorrectly.
**Why it happens:** The photo processing loop interleaves export (main thread), submit (to pool), and collect (from futures). This is a single logical operation spread across iterations.
**How to avoid:** Extract the photo loop as ONE function (`_process_photos_parallel`), not as separate submit/collect helpers. Keep the interleaved pattern intact within the extracted function.

### Pitfall 4: Ruff Ignore List Not Updated
**What goes wrong:** Phase completes but PLR0912/PLR0915 still in ignore list, so violations can regress.
**Why it happens:** Forgetting to update `pyproject.toml` at the end.
**How to avoid:** Final task in the plan should explicitly remove PLR0912 and PLR0915 from the ignore list and verify `ruff check` passes cleanly.

## Decomposition Map

### processor.py -- Target Functions

**`process_batch` (lines 259-479, 220 lines)**
Extract into:
1. `_init_batch(items, model, threads, write)` -- split photos/videos, create tracker, start metrics run (~15 lines)
2. `_process_photos_parallel(photos, pool_args, tracker, state)` -- the entire photo loop including export-on-main, submit-to-pool, collect-results (~80 lines)
3. `_collect_completed_futures(in_flight, state)` -- drain done futures, update counters (~20 lines)
4. `_export_and_submit_photo(photo, pool, in_flight, ...)` -- export + submit one photo (~20 lines)
5. `_drain_remaining_futures(in_flight, state)` -- final drain after loop (~20 lines)
6. `_process_videos_sequential(videos, args, tracker, state)` -- the video loop (~25 lines)
7. `_maybe_refresh` -- convert from closure to standalone function accepting state

**`_maybe_refresh` (lines 296-327, 32 lines, closure)**
Convert to standalone function. Needs: `discover_fn`, `last_refresh`, `refresh_interval`, `photos`, `videos`, `seen_uuids`, `total`. Use a mutable state object or return updated values.

### cli.py -- Target Functions

**`main` (lines 155-247, 92 lines, PLR0915=56 statements)**
Extract into:
1. `_build_parser()` -- construct ArgumentParser + subparsers (~60 lines of parser setup)
2. `_dispatch(args, cfg)` -- the if/elif command dispatch (~15 lines)

**`_run` (lines 30-98, 68 lines, C901=11)**
Extract into:
1. `_resolve_config(args, cfg)` -- merge CLI overrides with config (~25 lines)
2. Remaining loop logic stays in `_run` but becomes ~25 lines

### exporter.py -- Target Functions

**`export_photo_as_base64` (lines 53-112, 60 lines)**
Extract into:
1. `_resolve_export_path(photo, tmpdir)` -- try export, fallback to original path (~15 lines)
2. `_open_or_fallback(photo, export_path, tmpdir)` -- open image with derivative fallback (~15 lines)
3. `_encode_as_jpeg(img, max_dimension, tmpdir)` -- resize + save + base64 encode (~15 lines)

**`export_video_frames_as_base64` (lines 115-209, 95 lines)**
Extract into:
1. `_get_video_duration(video_path, filename)` -- ffprobe call + parse (~20 lines)
2. `_extract_frame(video_path, timestamp, frame_path, max_dimension)` -- single ffmpeg frame extraction (~15 lines)
3. `_extract_all_frames(video_path, num_frames, duration, max_dimension, tmpdir)` -- loop calling `_extract_frame` (~20 lines)

## Magic Literals Inventory

### processor.py
| Literal | Location | Proposed Constant | Already Named? |
|---------|----------|-------------------|----------------|
| `10` | line 19 | `MAX_ITEM_FAILURES` | YES |
| `5` | line 20 | `RETRY_BASE_DELAY` | YES |
| `300` | line 21 | `RETRY_MAX_DELAY` | YES |
| `500` | line 22 | `_HTTP_SERVER_ERROR` | YES |
| `400` | line 23 | `_HTTP_BAD_REQUEST` | YES |
| `0.1` | lines 360, 365 | `_POLL_INTERVAL` | NO -- extract |
| `5` | line 415 | `_FUTURE_DRAIN_TIMEOUT` | NO -- extract |
| `21600` | line 268 | Already a parameter default | Borderline -- move to constant `DEFAULT_REFRESH_INTERVAL` |

### cli.py
| Literal | Location | Proposed Constant | Already Named? |
|---------|----------|-------------------|----------------|
| `21600` | line 88 | `DEFAULT_REFRESH_INTERVAL` (or import from processor) | NO -- extract |
| `8001` | line 149 | `DEFAULT_DATASETTE_PORT` | NO -- extract |

### exporter.py
| Literal | Location | Proposed Constant | Already Named? |
|---------|----------|-------------------|----------------|
| `1024` | lines 54, 116 | Already a parameter default | Borderline -- could add `DEFAULT_MAX_DIMENSION` |
| `30` | line 59 | `PHOTO_EXPORT_TIMEOUT` | NO -- extract |
| `300` | line 124 | `VIDEO_EXPORT_TIMEOUT` | NO -- extract |
| `85` | line 99 | `JPEG_QUALITY` | NO -- extract |
| `2` | line 181 (ffmpeg `-q:v`) | `FFMPEG_QUALITY` | NO -- extract |

### llm.py
| Literal | Location | Proposed Constant | Already Named? |
|---------|----------|-------------------|----------------|
| `90.0` | line 45 | `LLM_TIMEOUT` | NO -- extract |
| `0.3` | lines 69, 84 | `LLM_TEMPERATURE` | NO -- extract |

### writer.py
| Literal | Location | Proposed Constant | Already Named? |
|---------|----------|-------------------|----------------|
| `3` | line 20 | `PHOTOS_APP_STARTUP_WAIT` | NO -- extract |

## Verification Strategy

### After Each Module Refactoring
```bash
# Must pass -- ensures no syntax errors or import issues
python -c "from labeler.processor import process_batch"
python -c "from labeler.cli import main"
python -c "from labeler.exporter import export_photo_as_base64"

# Must pass -- ensures no lint regressions
ruff check labeler/
ruff format --check labeler/
```

### After All Decomposition (Final Step)
```bash
# Remove PLR0912 and PLR0915 from ignore list in pyproject.toml
# Then verify no violations remain:
ruff check --select PLR0912,PLR0915,C901 labeler/
```

### Behavior Preservation Check
Since there are no tests, behavior preservation is verified by:
1. Import check (no runtime errors)
2. `python -m labeler --help` (CLI still works)
3. `python -m labeler config show` (config subsystem works)
4. Visual inspection that control flow is preserved

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None (no test infrastructure exists) |
| Config file | none |
| Quick run command | `ruff check labeler/ && ruff format --check labeler/` |
| Full suite command | `ruff check labeler/ && python -c "from labeler import cli, processor, exporter"` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRC-01 | processor.py functions under 30 lines | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/processor.py` | N/A (ruff rule) |
| STRC-02 | cli.py functions under 30 lines | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/cli.py` | N/A (ruff rule) |
| STRC-03 | exporter.py functions under 30 lines | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/exporter.py` | N/A (ruff rule) |
| STRC-04 | remaining modules decomposed where needed | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/` | N/A (ruff rule) |
| STRC-05 | Deep nesting replaced with guard clauses | manual | Visual inspection of indentation levels | N/A |
| STRC-06 | Magic numbers/strings extracted to constants | manual | Visual inspection + grep for bare literals | N/A |

### Sampling Rate
- **Per task commit:** `ruff check labeler/ && ruff format --check labeler/`
- **Per wave merge:** `ruff check labeler/ && python -c "from labeler import cli, processor, exporter"`
- **Phase gate:** Full lint pass with PLR0912/PLR0915 un-ignored

### Wave 0 Gaps
None -- ruff is already configured and operational. No test framework to set up.

## Open Questions

1. **Should `_maybe_refresh` become a method on a class or a standalone function?**
   - What we know: It mutates 5+ outer-scope variables via `nonlocal`
   - What's unclear: Whether a dataclass approach adds unnecessary complexity for a CLI tool
   - Recommendation: Use a simple mutable state dict passed by reference. Avoids class overhead while eliminating the closure. The planner should decide.

2. **Should `PLR0913` (too many arguments) be addressed?**
   - What we know: Many functions have 6-9 parameters. Fixing this would mean grouping into config objects.
   - What's unclear: Whether this is in scope for Phase 4 (requirements say "decompose" not "redesign signatures")
   - Recommendation: Leave PLR0913 ignored. It is a design concern, not a structure concern. Out of scope per REQUIREMENTS.md ("OOP refactoring" is explicitly out of scope).

## Sources

### Primary (HIGH confidence)
- Direct source code analysis of all 14 modules in `labeler/`
- `ruff check --select PLR0912,PLR0915,PLR0911,C901` output (5 violations found)
- `pyproject.toml` ruff configuration (current ignore list: PLR0912, PLR0913, PLR0915)

### Secondary (MEDIUM confidence)
- Python refactoring best practices (guard clauses, extract method, replace magic number with constant)
- These are well-established patterns that don't require external verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, just ruff (already in place)
- Architecture: HIGH - patterns are straightforward Python refactoring, verified against actual code
- Pitfalls: HIGH - identified from direct code analysis (closure state, thread safety, control flow)
- Decomposition map: HIGH - based on actual line counts and complexity metrics from ruff

**Research date:** 2026-03-19
**Valid until:** No expiry -- this is static code analysis, not version-dependent

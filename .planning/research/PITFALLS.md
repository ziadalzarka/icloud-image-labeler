# Pitfalls Research

**Domain:** Python code quality refactoring (existing CLI tool, ~12 modules, no test suite)
**Researched:** 2026-03-19
**Confidence:** HIGH (based on direct codebase analysis + established Python practices)

## Critical Pitfalls

### Pitfall 1: Behavioral Regressions from "Cosmetic" Refactoring

**What goes wrong:**
Refactoring that is intended to be purely structural silently changes behavior. In this codebase, the most dangerous areas are:
- `processor.py`'s `process_batch` which mutates lists in-place (`photos[photo_insert_idx:photo_insert_idx] = new_photos`) and tracks state via closures (`nonlocal last_refresh, total`). Extracting the refresh logic into a separate function could break the list mutation or state tracking.
- `writer.py`'s `_write_lock` is a module-level singleton. Moving `write_metadata` to a class or restructuring imports could create a second lock instance, breaking the thread-safety guarantee.
- `shutdown.py`'s module-level `_shutdown_event` is shared across all importers. Restructuring could break signal propagation.

**Why it happens:**
When there are no tests, developers assume "I'm just moving code around" is safe. But Python's module-level state, closures, and mutable default arguments make structural changes semantically meaningful.

**How to avoid:**
- Before any refactoring, create a manual test checklist: run a dry-run batch of 3 photos, verify graceful shutdown (Ctrl+C), verify daemon start/stop, verify config set/show. Run this before and after each refactoring change.
- Never refactor and format in the same commit. Format first (pure whitespace/style), then refactor in separate, small commits.
- For `processor.py` specifically: do not extract `_maybe_refresh` out of `process_batch` without understanding the `nonlocal` bindings and list mutation side effects.

**Warning signs:**
- A diff that moves code between scopes (function to module level, or vice versa)
- Any change touching `_write_lock`, `_shutdown_event`, or `_maybe_refresh`
- Functions that take mutable arguments being restructured

**Phase to address:**
Phase 1 (Ruff formatting) is safe. Phase 2 (structural refactoring) is where this bites. Mandate atomic, reviewable commits.

---

### Pitfall 2: Ruff Autofix Changing Semantics

**What goes wrong:**
Ruff's `--fix` flag auto-removes "unused" imports and "unnecessary" code that is actually load-bearing. Specific risks in this codebase:
- `exporter.py` line 26: `pillow_heif.register_heif_opener()` is called inside `_open_image`. Ruff might flag `pillow_heif` as unused if it only sees the registration call and not a direct attribute use.
- `cli.py` line 65: `import osxphotos` inside a conditional branch. Ruff may want to move it to the top, but it is intentionally deferred (heavy import, only used for `--uuid` mode).
- Any f-string with side effects in log statements. Ruff's `UP032` rule rewrites `.format()` to f-strings, which can change evaluation order.

**Why it happens:**
Teams run `ruff check --fix` globally and trust it blindly. Ruff is excellent but its autofixes are heuristic, not semantic.

**How to avoid:**
- Run `ruff check` (without `--fix`) first. Review every suggested fix.
- Use `ruff check --fix --diff` to preview changes before applying.
- For the first pass, enable only formatting rules (E, W) and safe style rules. Add linting rules (F, UP, I) one category at a time.
- Add `# noqa` comments with explanations where Ruff is wrong (e.g., the `pillow_heif` registration pattern).

**Warning signs:**
- Running `ruff check --fix` on the entire codebase in one shot
- Ruff removing an import from `exporter.py` or `cli.py` without checking if it is conditionally used
- Any autofix touching a line with `register_`, `signal.signal`, or module-level side effects

**Phase to address:**
Phase 1 (Ruff setup). Use a phased rule enablement strategy, not "enable everything at once."

---

### Pitfall 3: Refactoring processor.py Without Understanding Its Concurrency Model

**What goes wrong:**
`processor.py` is the most complex module (~180 lines for `process_batch`) and the most tempting target for "break up this long function." But it has a specific concurrency design:
- Photo exports run on the main thread (osxphotos SQLite is thread-bound)
- LLM calls run in a ThreadPoolExecutor
- The `in_flight` dict tracks futures, with backpressure via `len(in_flight) >= threads`
- `_maybe_refresh` mutates the `photos` and `videos` lists that the outer loop iterates over
- Shutdown can happen at any point, and futures need to be drained/cancelled

Breaking this into smaller functions without preserving these invariants causes race conditions, deadlocks, or data loss.

**Why it happens:**
Long functions are a code smell, so developers instinctively want to break them up. But `process_batch`'s length comes from genuine complexity, not poor structure.

**How to avoid:**
- Document the concurrency model in a docstring before refactoring. The current docstring is good but doesn't cover the backpressure or refresh mutation patterns.
- If extracting, keep the main loop in one place. Extract the "drain completed futures" and "submit next photo" blocks as methods on a small orchestrator class, not as free functions that need closure variables passed as arguments.
- Do not introduce `async` as a "cleanup" -- that would be a rewrite, not a refactoring.

**Warning signs:**
- Someone proposing to split `process_batch` into `process_photos` and `process_videos` as separate top-level functions (the shared state -- `tracker`, `processed`, `total`, `seen_uuids` -- makes this tricky)
- Any change that moves the ThreadPoolExecutor lifecycle outside the function
- Adding `asyncio` to this module

**Phase to address:**
Phase 2 (structural refactoring). This module should be the last one refactored, after simpler modules build confidence. Consider leaving its structure mostly intact with better naming/comments rather than aggressive extraction.

---

### Pitfall 4: Formatting the Entire Codebase in One Commit

**What goes wrong:**
A single "format everything" commit creates a massive diff that:
- Makes `git blame` useless for every line in the codebase
- Cannot be reviewed meaningfully (hundreds of lines of whitespace changes)
- If it contains even one semantic change (accidentally or via autofix), it is buried and unfindable

**Why it happens:**
It feels efficient to "just format everything at once." And technically Ruff formatting (unlike linting fixes) should be purely cosmetic. But in practice, mixed formatting + linting fixes, or formatting that triggers unintended changes (line length wrapping changing code structure), create hidden problems.

**How to avoid:**
- Format one module at a time, in separate commits. This codebase has ~12 modules; 12 small commits are better than 1 large one.
- Use `git blame --ignore-rev` (add a `.git-blame-ignore-revs` file) for the formatting commits so blame stays useful.
- Format first, then lint fix, then refactor -- never combine these in one commit.

**Warning signs:**
- A single commit touching every `.py` file
- A diff with 500+ changed lines that is "just formatting"
- No `.git-blame-ignore-revs` file after formatting

**Phase to address:**
Phase 1 (Ruff formatting). Use per-module commits and create `.git-blame-ignore-revs`.

---

### Pitfall 5: Removing "Dead Code" That Handles Edge Cases

**What goes wrong:**
Code that looks dead or redundant is actually handling a rare edge case. In this codebase:
- `exporter.py` lines 51-77: The multi-fallback chain (export -> original path -> derivative) looks overly defensive, but each fallback handles a real failure mode (iCloud-only files, corrupted exports, missing originals).
- `llm.py` lines 67-81: The JSON retry with "correction prompt" looks like dead code if the model always returns JSON, but Qwen models intermittently return non-JSON.
- `processor.py` lines 27-36: The `_is_retryable_error` check for "crashed" in the message body looks hacky, but LM Studio genuinely returns 400 with "crashed" when models crash.

**Why it happens:**
Developers see defensive code and think "this can't happen" or "this is too complex, simplify." Without production logs showing these edge cases triggering, the code looks unnecessary.

**How to avoid:**
- Before removing any error handling or fallback path, check git log for the commit that added it. If the commit message explains a specific bug fix, keep the code.
- Add comments explaining WHY defensive code exists, rather than removing it. This is the highest-value cleanup for this codebase.
- Mark intentional fallback chains with comments like `# Fallback: iCloud-only files may not export`.

**Warning signs:**
- Removing try/except blocks to "simplify" error handling
- Removing fallback logic from `exporter.py`
- Removing the `_is_retryable_error` special cases
- Any change described as "removing dead code" in modules that handle external services (osxphotos, LM Studio, PhotoScript, ffmpeg)

**Phase to address:**
Phase 2 (dead code removal). Be extremely conservative. Only remove code that is provably unreachable (e.g., unused private functions with zero callers), not code that handles error conditions.

---

## Moderate Pitfalls

### Pitfall 6: Inconsistent Ruff Configuration Leading to Config Drift

**What goes wrong:**
Ruff config is added to `pyproject.toml` but with too many or too few rules enabled, or without pinning Ruff's version. Future Ruff updates change rule behavior, and the codebase gradually drifts from the configured style.

**How to avoid:**
- Pin Ruff version in dev dependencies (e.g., `ruff>=0.9.0,<0.10`).
- Start with Ruff's defaults (which include `E` and `F` rules), then add `I` (import sorting), `UP` (pyupgrade for Python 3.10+), and `W` (warnings). Do not enable `ALL`.
- Set `line-length = 120` (not 88) to avoid excessive line wrapping in this codebase which has long function signatures (see `processor.py` and `metrics.py`).
- Add the `[tool.ruff]` section to `pyproject.toml` (already exists, natural home for it).

**Warning signs:**
- `ruff.toml` as a separate file instead of in `pyproject.toml`
- `select = ["ALL"]` in the config
- No version pin for Ruff

**Phase to address:**
Phase 1 (Ruff setup).

---

### Pitfall 7: Renaming Without Grep-Verifying All Callers

**What goes wrong:**
Renaming a function or variable in one module without updating all callers. Python has no compile step to catch this. In this codebase:
- `create_client` from `llm.py` is called in both `_label_and_write_photo` and `_process_single_video`
- `write_metadata` from `writer.py` is called from `processor.py`
- `export_photo_as_base64` and `export_video_frames_as_base64` are imported in `processor.py`
- `metrics.record_item` has 18 keyword arguments; renaming any would silently break

**How to avoid:**
- Use your editor's "rename symbol" feature, not find-and-replace.
- After any rename, run `python -m labeler run --dry-run --limit 1` to verify imports resolve.
- For function parameter renames (especially `metrics.record_item`), grep for every keyword argument by name.

**Warning signs:**
- Renaming a function that is imported in more than one module
- Renaming keyword arguments on functions with many parameters
- `ImportError` or `TypeError: unexpected keyword argument` at runtime

**Phase to address:**
Phase 2 (naming improvements). Always verify with a quick dry-run after renames.

---

### Pitfall 8: Over-Abstracting Small, Clear Code

**What goes wrong:**
Creating unnecessary abstractions (base classes, protocols, factory patterns) for code that is already clear. This codebase is ~800 lines across 12 modules. It does not need:
- An abstract `MediaProcessor` base class with `PhotoProcessor` and `VideoProcessor` subclasses
- A `LabelingStrategy` pattern
- A configuration management framework beyond what `config.py` already does
- Dependency injection for the LLM client

**Why it happens:**
"Clean code" literature encourages patterns that make sense at scale but add indirection to small codebases. This tool has one job and does it well.

**How to avoid:**
- The refactoring goal is readability, not architecture. If extracting a function requires more lines of parameter passing than the original inline code, don't extract it.
- Measure improvement by "can a new reader understand this module in 5 minutes?" not by "does this follow SOLID principles?"

**Warning signs:**
- Introducing new files (e.g., `base.py`, `interfaces.py`, `factories.py`)
- Adding abstract base classes or Protocol types
- A refactoring that increases total line count by more than 10%

**Phase to address:**
Phase 2 (structural refactoring). Keep the flat module structure. The goal is clarity, not architecture.

---

### Pitfall 9: Breaking the pyproject.toml Entry Point

**What goes wrong:**
Moving `main()` out of `cli.py` or renaming it breaks the `[project.scripts]` entry point (`icloud-image-labeler = "labeler.cli:main"`). Users who installed via `pip install` or `brew` get a broken command.

**How to avoid:**
- Do not move `main()` out of `cli.py`.
- After any change to `cli.py`, verify the entry point resolves: `python -c "from labeler.cli import main; print('ok')"`.

**Warning signs:**
- Renaming `main()` to anything else
- Moving the CLI entry point to `__main__.py`
- Changes to `[project.scripts]` in `pyproject.toml`

**Phase to address:**
Phase 2 (structural refactoring). Leave the entry point untouched.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skipping `.git-blame-ignore-revs` | Saves 2 minutes | Every `git blame` is useless after formatting | Never -- always create this file |
| `# noqa` without explanation | Silences the linter fast | Nobody knows why the rule was suppressed | Never -- always add a comment explaining why |
| Formatting + refactoring in one commit | Fewer commits | Impossible to review, impossible to bisect | Never |
| Leaving long `process_batch` as-is | No regression risk | Harder for new contributors to read | Acceptable for now -- add comments instead of restructuring |
| Not running the tool after each change | Faster iteration | Silent breakage accumulates | Never -- dry-run after every structural change |

## "Looks Done But Isn't" Checklist

- [ ] **Ruff formatting:** Often missing `[tool.ruff.format]` section -- verify `ruff format --check .` passes with zero changes
- [ ] **Import sorting:** Often conflicts with manual grouping -- verify `ruff check --select I .` passes
- [ ] **Dead code removal:** Often removes error handling -- verify every removed code path was truly unreachable (check git history for the commit that added it)
- [ ] **Function extraction:** Often breaks closure variable capture -- verify `nonlocal` bindings and module-level state still work
- [ ] **Naming changes:** Often misses one caller -- verify `python -m labeler run --dry-run --limit 1` works
- [ ] **Line length changes:** Often wraps long strings into unreadable multi-line -- verify log messages and SQL strings are still readable
- [ ] **`.git-blame-ignore-revs`:** Often forgotten -- verify file exists and is referenced in `.gitconfig` or repo instructions

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Behavioral regression from refactoring | MEDIUM | `git bisect` to find the breaking commit, revert it, reapply formatting-only changes |
| Ruff autofix breaking imports | LOW | `git diff` the autofix commit, restore removed imports, add `# noqa` with explanation |
| Broken entry point | LOW | Restore `labeler/cli.py:main`, reinstall with `pip install -e .` |
| Over-abstraction | MEDIUM | Revert the abstraction commits, re-do with simpler approach (comment-based clarity) |
| Lost git blame history | LOW (but permanent annoyance) | Create `.git-blame-ignore-revs` retroactively, configure `git blame` to use it |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Ruff autofix changing semantics | Phase 1 (Ruff setup) | `ruff check --diff` reviewed before applying fixes |
| Formatting in one giant commit | Phase 1 (Ruff formatting) | Each formatting commit touches 1-2 modules max |
| No `.git-blame-ignore-revs` | Phase 1 (Ruff formatting) | File exists after first formatting commit |
| Ruff config drift | Phase 1 (Ruff setup) | Version pinned, rules explicit in `pyproject.toml` |
| Behavioral regression from refactoring | Phase 2 (structural cleanup) | Dry-run test passes after every commit |
| Removing edge-case handling | Phase 2 (dead code removal) | Git history checked for each removal |
| Breaking processor concurrency | Phase 2 (structural cleanup) | `process_batch` changes reviewed for thread safety |
| Renaming without full verification | Phase 2 (naming) | Grep + dry-run after every rename |
| Over-abstraction | Phase 2 (structural cleanup) | No new files or abstract classes introduced |
| Breaking entry point | Phase 2 (structural cleanup) | Entry point import verified after cli.py changes |

## Sources

- Direct analysis of the codebase (`labeler/` -- 12 modules, ~800 lines)
- Ruff documentation on autofix safety (HIGH confidence, well-documented tool)
- Python concurrency patterns for ThreadPoolExecutor (HIGH confidence, stdlib)
- Git blame ignore revs feature (HIGH confidence, Git documentation)

---
*Pitfalls research for: Python code quality refactoring of icloud-image-labeler*
*Researched: 2026-03-19*

# Phase 3: Dead Code Removal - Research

**Researched:** 2026-03-19
**Domain:** Python dead code removal, manual lint resolution
**Confidence:** HIGH

## Summary

Phase 3 covers three requirements: TOOL-04 (resolve remaining non-auto-fixable lint violations), DEAD-02 (remove unused functions/variables), and DEAD-03 (remove commented-out code blocks). After thorough codebase analysis, this phase is smaller than expected.

**Key finding:** `ruff check .` already passes clean with the current configuration. The current ruff config ignores four rules (E501, PLR0912, PLR0913, PLR0915) that produce violations. The PLR rules (complexity) are explicitly deferred to Phase 4 per STATE.md decisions. E501 (line-too-long) produces 18 violations across 4 files. Vulture found zero unused code at 80% confidence. No commented-out code blocks exist (ERA rules pass clean). The phase's actual work is limited to fixing E501 line-length violations and potentially removing the E501 ignore.

**Primary recommendation:** Fix the 18 E501 line-too-long violations, remove E501 from the ignore list, and verify DEAD-02/DEAD-03 are already satisfied. Keep PLR ignores for Phase 4.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOOL-04 | All remaining lint violations that require human judgment resolved manually | 18 E501 violations found; PLR rules deferred to Phase 4 per decision log |
| DEAD-02 | All unused functions and variables removed | Vulture scan: zero unused code found at 80% confidence; manual cross-reference confirms all functions are called |
| DEAD-03 | All commented-out code blocks removed | Ruff ERA rules pass clean; grep found only 3 section-separator comments (not code) |
</phase_requirements>

## Current Codebase State

### Ruff Configuration (pyproject.toml)
```toml
[tool.ruff.lint]
select = ["F", "E", "W", "I", "UP", "B", "SIM", "C4", "RET", "PIE", "ERA", "ARG", "RUF", "PTH", "PLR"]
ignore = ["E501", "PLR0912", "PLR0913", "PLR0915"]
```

### Violations by Ignored Rule

| Rule | Count | Description | Action for Phase 3 |
|------|-------|-------------|---------------------|
| E501 | 18 | Line too long (>88 chars) | FIX -- these are manual-judgment fixes |
| PLR0912 | 1 | Too many branches (processor.py:process_batch) | DEFER -- Phase 4 restructuring |
| PLR0913 | 7 | Too many arguments | DEFER -- Phase 4 restructuring |
| PLR0915 | 2 | Too many statements | DEFER -- Phase 4 restructuring |

### E501 Violations (18 total)

**exporter.py (4 violations):**
- Line 13: docstring 95 chars -- rewrap to multi-line
- Line 61: f-string in logger.warning 98 chars -- break string
- Line 89: f-string in RuntimeError 104 chars -- break string
- Line 113: docstring 95 chars -- rewrap to multi-line

**llm.py (4 violations):**
- Lines 10, 23, 24: System prompt string literals (113-204 chars) -- these are LLM prompt constants; break into concatenated lines or use parenthesized strings
- Line 117: f-string in dict literal 119 chars -- break string

**metrics.py (5 violations):**
- Lines 107-109: SQL ON CONFLICT clause (95-99 chars each) -- reformat SQL to one column per line
- Line 145: SQL INSERT statement 100 chars -- reformat SQL

**processor.py (5 violations):**
- Line 324: logger.info f-string 119 chars -- break string
- Line 343: logger.info f-string 114 chars -- break string
- Line 350: logger.error f-string 91 chars -- break string
- Line 380: logger.error f-string 90 chars -- break string
- Lines 412, 453: logger.info f-strings 106-110 chars -- break strings

### Dead Code Analysis (Vulture)

| Confidence | Findings |
|------------|----------|
| 80%+ | Zero unused code |
| 60%+ | 2 false positives (writer.py attributes set on PhotoScript object) |

**Manual cross-reference confirms:** Every function defined in every module is imported and called from at least one other module. The codebase is tight with no dead functions or classes.

### Commented-Out Code Analysis

| Check | Result |
|-------|--------|
| Ruff ERA (commented-out code) | All checks passed |
| Grep for commented code patterns | Zero matches |
| Manual review | 3 section separators in processor.py (e.g., `# --- Photo processing ---`) -- these are organizational comments, NOT dead code |

## Architecture Patterns

### E501 Fix Strategies

**Strategy 1: Long f-strings in logger calls**
```python
# BEFORE (too long)
logger.info(
    f"[{processed}/{total}] Done: {photo.original_filename} (added {_format_date(photo)})"
)

# AFTER (split the f-string)
logger.info(
    f"[{processed}/{total}] Done: {photo.original_filename} "
    f"(added {_format_date(photo)})"
)
```

**Strategy 2: Long docstrings**
```python
# BEFORE (single line too long)
def _resize_if_needed(img, max_dim: int):
    """Resize image so the longest side is at most max_dim pixels, maintaining aspect ratio."""

# AFTER (multi-line docstring)
def _resize_if_needed(img, max_dim: int):
    """Resize image so the longest side is at most max_dim pixels.

    Maintains aspect ratio.
    """
```

**Strategy 3: Long SQL strings**
```python
# BEFORE
"""INSERT INTO run_metrics (started_at, model, threads, dry_run, photos_found, videos_found)

# AFTER -- one column per line
"""INSERT INTO run_metrics (
    started_at, model, threads,
    dry_run, photos_found, videos_found
)
```

**Strategy 4: LLM prompt constants**
```python
# BEFORE (long line inside triple-quoted string)
PHOTO_SYSTEM_PROMPT = """You are a photo labeling assistant...
1. **keywords**: A list of descriptive keywords/tags (objects, scenes, activities, colors, mood). 10-20 keywords.

# NOTE: E501 inside triple-quoted strings used as LLM prompts should be handled
# carefully -- the string content is sent to an LLM, so line breaks matter.
# Option A: Keep long lines and add noqa comment (pragmatic)
# Option B: Restructure prompt text to fit 88 chars (may change LLM behavior)
```

### Ignore List Update Strategy

After fixing E501 violations:
1. Remove `"E501"` from the ignore list
2. Keep `"PLR0912"`, `"PLR0913"`, `"PLR0915"` -- these are Phase 4 concerns
3. Run `ruff check .` to verify zero violations

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dead code detection | Manual grep for unused functions | `vulture` + `ruff --select F,ERA` | Vulture has whole-program analysis; Ruff ERA catches commented code |
| Line-length fixes | Automated reformatter | Manual judgment per line | `ruff format` does NOT enforce E501; these need human decisions about where to break |

## Common Pitfalls

### Pitfall 1: Breaking LLM prompts with line wrapping
**What goes wrong:** Changing line breaks in triple-quoted strings sent to the LLM can subtly alter model output quality.
**Why it happens:** E501 applies to lines inside `"""` strings too, but these are semantic content.
**How to avoid:** For `PHOTO_SYSTEM_PROMPT` and `VIDEO_SYSTEM_PROMPT` in llm.py, either use `# noqa: E501` inline comments or restructure the text carefully. Do NOT blindly insert `\n` at column 88.
**Warning signs:** LLM output quality regression after prompt text changes.

### Pitfall 2: Removing PLR ignores prematurely
**What goes wrong:** Removing PLR0912/0913/0915 from ignore list causes 10 violations that require Phase 4 restructuring work.
**Why it happens:** These rules flag structural complexity, not dead code.
**How to avoid:** Only remove E501 from the ignore list. PLR rules stay ignored until Phase 4.

### Pitfall 3: False positives in dead code analysis
**What goes wrong:** Removing code that looks unused but is called dynamically.
**Why it happens:** Entry points like `main()`, `__main__.py`, and attribute setters on external objects look unused to static analysis.
**How to avoid:** Already verified -- no action needed. All functions are genuinely used.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None (no test suite exists) |
| Config file | None |
| Quick run command | `ruff check .` |
| Full suite command | `ruff check . && python -m labeler run --dry-run --limit 1` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOOL-04 | Zero ruff violations (excluding deferred PLR rules) | lint | `ruff check .` | N/A (lint tool) |
| DEAD-02 | No unused functions/variables | static analysis | `python -m vulture labeler/ --min-confidence 80` | N/A (analysis tool) |
| DEAD-03 | No commented-out code blocks | lint | `ruff check . --select ERA` | N/A (lint tool) |

### Sampling Rate
- **Per task commit:** `ruff check .`
- **Per wave merge:** `ruff check . && python -m vulture labeler/ --min-confidence 80`
- **Phase gate:** Full suite green + manual review of all changes

### Wave 0 Gaps
None -- validation uses existing lint tools, no test infrastructure needed.

## Open Questions

1. **LLM prompt line length: noqa vs restructure?**
   - What we know: 4 of 18 E501 violations are inside LLM system prompt strings (llm.py lines 10, 23, 24, 117)
   - What's unclear: Whether restructuring prompt text affects LLM output quality
   - Recommendation: Use `# noqa: E501` for lines inside triple-quoted prompt constants (lines 10, 23, 24). The f-string on line 117 can be split normally.

## Sources

### Primary (HIGH confidence)
- Direct `ruff check .` output against the actual codebase -- all violation counts verified
- Direct `vulture` analysis of the actual codebase -- zero dead code confirmed
- Manual reading of all 14 Python files in `labeler/` package

### Secondary (MEDIUM confidence)
- STATE.md decision log confirming PLR rules are deferred to Phase 4

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Ruff already configured, just need to fix violations
- Architecture: HIGH - All violations enumerated from actual codebase scan
- Pitfalls: HIGH - Based on direct analysis of the specific violations

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable -- no external dependencies changing)

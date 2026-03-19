# Phase 2: Automated Lint Fixes - Research

**Researched:** 2026-03-19
**Domain:** Ruff linting -- expanded rule sets (PTH, PLR) and auto-fix
**Confidence:** HIGH

## Summary

Phase 2 adds PTH (pathlib preference) and PLR (Pylint refactoring) rule sets to the existing Ruff configuration and resolves all violations. The current config already includes SIM, C4, and RET from the roadmap's "expanded" list, so only PTH and PLR are new. E501 (line length) is already ignored in config.

The codebase currently passes `ruff check .` clean with the existing rule set. Adding PTH and PLR introduces exactly 33 new violations: 20 PTH violations (converting `os.path` calls to `pathlib` equivalents) and 13 PLR violations (too-many-arguments, too-many-statements, too-many-branches, magic-value-comparison). None of these are auto-fixable by `ruff --fix`; all require manual code changes.

Additionally, there is 1 auto-fixable F401 (unused import) that appears when checking with expanded rules -- but on re-check with current config it passes clean, so this may already be fixed. The primary work is manual PTH conversions (straightforward) and deciding how to handle PLR violations (some overlap with Phase 4 structure refactoring).

**Primary recommendation:** Add PTH and PLR to rule sets. Fix all PTH violations (simple os.path-to-pathlib conversions). For PLR complexity violations (PLR0912, PLR0913, PLR0915), add per-line `noqa` comments or adjust thresholds in config since these are explicitly addressed in Phase 4 (structure refactoring). Fix PLR2004 (magic values) inline since they're simple constant extractions.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOOL-03 | All auto-fixable lint violations resolved via `ruff check --fix` | Currently 0 auto-fixable violations exist. Adding new rules introduces 0 new auto-fixable ones. Run `ruff check --fix .` to confirm clean. |
| TOOL-06 | Expanded rule sets (SIM, C4, PTH, RET, PLR) enabled and violations resolved | SIM, C4, RET already enabled. Add PTH and PLR to `select` in pyproject.toml. 33 new violations to resolve (20 PTH, 13 PLR). |
| DEAD-01 | All unused imports removed across all modules | Currently no unused imports (F401 passes clean). Verify remains clean after PTH changes add new `pathlib` imports. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ruff | 0.15.6 | Linting and auto-fix | Already configured; sole linter per Phase 1 decision |

No additional libraries needed. This phase is purely configuration and code changes.

### What's Changing in pyproject.toml

Current `select`:
```
["F", "E", "W", "I", "UP", "B", "SIM", "C4", "RET", "PIE", "ERA", "ARG", "RUF"]
```

Target `select` (add PTH, PLR):
```
["F", "E", "W", "I", "UP", "B", "SIM", "C4", "RET", "PIE", "ERA", "ARG", "RUF", "PTH", "PLR"]
```

## Architecture Patterns

### PTH Conversions (20 violations)

All PTH violations are `os.path.*` calls that should use `pathlib.Path` equivalents. These are mechanical conversions:

| Ruff Rule | Count | os.path Call | pathlib Equivalent |
|-----------|-------|--------------|--------------------|
| PTH123 | 4 | `open(path)` | `Path(path).open()` or keep `open()` with Path arg |
| PTH202 | 4 | `os.path.getsize(p)` | `Path(p).stat().st_size` |
| PTH110 | 3 | `os.path.exists(p)` | `Path(p).exists()` |
| PTH118 | 3 | `os.path.join(a, b)` | `Path(a) / b` |
| PTH120 | 3 | `os.path.dirname(p)` | `Path(p).parent` |
| PTH100 | 1 | `os.path.abspath(p)` | `Path(p).resolve()` |
| PTH103 | 1 | `os.makedirs(p)` | `Path(p).mkdir(parents=True, exist_ok=True)` |
| PTH111 | 1 | `os.path.expanduser(p)` | `Path(p).expanduser()` |
| PTH119 | 1 | `os.path.basename(p)` | `Path(p).name` |

**Files affected:**
- `labeler/config.py` -- 1 violation (PTH123)
- `labeler/daemon.py` -- 4 violations (PTH120 x2, PTH100, PTH123)
- `labeler/exporter.py` -- 11 violations (PTH118 x3, PTH110 x3, PTH202 x3, PTH119, PTH123)
- `labeler/metrics.py` -- 3 violations (PTH103, PTH120, PTH111)
- `labeler/processor.py` -- 1 violation (PTH202, in _record_error if present)

### PLR Violations (13 violations)

| Ruff Rule | Count | Description | Recommended Action |
|-----------|-------|-------------|--------------------|
| PLR0913 | 7 | Too many arguments (>5) | Defer to Phase 4 via config threshold or per-line noqa |
| PLR0915 | 2 | Too many statements (>50) | Defer to Phase 4 via config threshold or per-line noqa |
| PLR2004 | 2 | Magic value in comparison (500, 400) | Fix inline -- extract HTTP status constants |
| PLR0912 | 1 | Too many branches (>12) | Defer to Phase 4 via config threshold or per-line noqa |

**Key decision: PLR complexity rules vs Phase 4 overlap**

PLR0913 (too-many-arguments), PLR0912 (too-many-branches), and PLR0915 (too-many-statements) flag the SAME functions that Phase 4 (STRC-01 through STRC-04) will decompose. Options:

1. **Ignore specific PLR complexity rules** -- Add `PLR0912`, `PLR0913`, `PLR0915` to `ignore` list. Phase 4 fixes the root cause; re-enable after Phase 4.
2. **Set higher thresholds** -- e.g., `max-args = 10`, `max-statements = 120`. Effectively silences current violations.
3. **Per-line noqa** -- Adds noise, must be removed in Phase 4.

**Recommendation:** Option 1 (ignore complexity PLR rules for now). These rules exist to flag structural problems that Phase 4 explicitly addresses. Enabling them now just creates noise or forces premature refactoring. Re-enable in Phase 4 or Phase 5 as a verification step.

### Pattern: Safe os.path to pathlib Conversion

When converting, preserve the type expected by callers:

```python
# BEFORE
sips_jpg = os.path.join(tmpdir, "sips_converted.jpg")
result = subprocess.run(["sips", ..., "--out", sips_jpg], ...)

# AFTER -- str() wrap needed because subprocess expects str, not Path
sips_jpg = str(Path(tmpdir) / "sips_converted.jpg")
result = subprocess.run(["sips", ..., "--out", sips_jpg], ...)
```

**Critical:** Many callsites pass paths to `subprocess.run`, `Image.open`, `base64` encoding, and `os.path.getsize`. Some accept Path objects natively (Pillow, pathlib methods), others need `str()` wrapping (subprocess args in lists). Test each conversion.

### Anti-Patterns to Avoid
- **Converting tmpdir to Path repeatedly:** When a function uses `tmpdir` (from `tempfile.TemporaryDirectory`) many times, convert once at the top: `tmp = Path(tmpdir)`
- **Mixing os.path and pathlib in same function:** Convert all os.path calls in a function at once, not piecemeal
- **Forgetting str() for subprocess:** `subprocess.run` list args need strings, not Path objects

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path manipulation | String concatenation with `/` | `pathlib.Path` / operator | Cross-platform, type-safe, readable |
| HTTP status constants | Inline magic numbers | Named constants at module top | PLR2004 compliance, self-documenting |

## Common Pitfalls

### Pitfall 1: Breaking subprocess calls with Path objects
**What goes wrong:** Replacing `os.path.join()` result with `Path()` object in subprocess command lists causes TypeError or unexpected behavior.
**Why it happens:** subprocess expects strings in command lists, not Path objects.
**How to avoid:** Always `str()` wrap Path objects passed to `subprocess.run` command lists. Or use `fspath()`.
**Warning signs:** TypeError at runtime when processing photos/videos.

### Pitfall 2: Changing return types of functions
**What goes wrong:** `_get_labeler_module_path()` in daemon.py returns `str`. Converting internals to pathlib changes the return to `Path`, breaking callers.
**Why it happens:** Mechanical conversion without checking function signatures and callers.
**How to avoid:** Keep return types the same. Use `str(Path(...))` if the function's contract is to return a string.
**Warning signs:** Type mismatches in plist generation, daemon commands.

### Pitfall 3: open() with Path -- PTH123 nuance
**What goes wrong:** `open(CONFIG_PATH)` where CONFIG_PATH is already a Path object. Ruff flags this but `open()` accepts Path objects fine since Python 3.6.
**How to avoid:** Convert to `CONFIG_PATH.open()` method style to satisfy PTH123. Both work identically.
**Warning signs:** None functionally, just lint violations.

### Pitfall 4: PLR0913 premature refactoring
**What goes wrong:** Trying to reduce argument counts by bundling into dataclasses or dicts to satisfy PLR0913, creating unnecessary abstractions before Phase 4.
**Why it happens:** Wanting zero violations without considering the roadmap phasing.
**How to avoid:** Defer PLR complexity rules. Phase 4 will properly decompose these functions.

## Code Examples

### Converting os.path.dirname chain (daemon.py)
```python
# BEFORE
def _get_labeler_module_path() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AFTER
def _get_labeler_module_path() -> str:
    return str(Path(__file__).resolve().parent.parent)
```

### Converting os.makedirs + os.path.dirname (metrics.py)
```python
# BEFORE
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# AFTER
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
```

### Converting os.path.join in tempdir context (exporter.py)
```python
# BEFORE
sips_jpg = os.path.join(tmpdir, "sips_converted.jpg")

# AFTER
sips_jpg = Path(tmpdir) / "sips_converted.jpg"
# Note: if passed to subprocess, wrap: str(sips_jpg)
```

### Extracting HTTP status magic values (processor.py)
```python
# BEFORE
if exc.status_code >= 500:
    return True
if exc.status_code == 400 and "crashed" in str(exc).lower():

# AFTER
_HTTP_SERVER_ERROR = 500
_HTTP_BAD_REQUEST = 400

if exc.status_code >= _HTTP_SERVER_ERROR:
    return True
if exc.status_code == _HTTP_BAD_REQUEST and "crashed" in str(exc).lower():
```

### Converting open() to Path.open() (config.py)
```python
# BEFORE
with open(CONFIG_PATH) as f:
    config = json.load(f)

# AFTER
with CONFIG_PATH.open() as f:
    config = json.load(f)
```

## Violation Summary by File

| File | PTH | PLR | Total | Complexity |
|------|-----|-----|-------|------------|
| labeler/processor.py | 0 | 10 | 10 | HIGH (all PLR complexity -- defer) |
| labeler/exporter.py | 11 | 0 | 11 | MEDIUM (mechanical PTH conversions) |
| labeler/daemon.py | 4 | 0 | 4 | LOW (straightforward) |
| labeler/metrics.py | 3 | 2 | 5 | LOW-MEDIUM (PTH + PLR0913 defer) |
| labeler/config.py | 1 | 0 | 1 | LOW |
| labeler/cli.py | 0 | 1 | 1 | LOW (PLR0915 -- defer) |
| **Total** | **20** | **13** | **33** | |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None -- no test infrastructure exists |
| Config file | None |
| Quick run command | `ruff check .` |
| Full suite command | `ruff check . && python -m labeler --help` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOOL-03 | Zero auto-fixable violations | lint | `ruff check . 2>&1 \| grep -c fixable` | N/A (ruff) |
| TOOL-06 | PTH+PLR enabled, violations resolved | lint | `ruff check .` | N/A (ruff) |
| DEAD-01 | No unused imports | lint | `ruff check --select F401 .` | N/A (ruff) |

### Sampling Rate
- **Per task commit:** `ruff check .`
- **Per wave merge:** `ruff check . && python -m labeler --help`
- **Phase gate:** `ruff check .` passes clean + CLI help works

### Wave 0 Gaps
None -- validation is via ruff itself, no test framework needed for this phase.

## Open Questions

1. **Should PLR complexity rules be ignored or threshold-adjusted?**
   - What we know: PLR0912/0913/0915 flag functions Phase 4 will decompose
   - What's unclear: Whether to ignore the rules entirely or set generous thresholds
   - Recommendation: Ignore (`PLR0912`, `PLR0913`, `PLR0915` in ignore list) with a comment noting Phase 4 will re-enable. Cleaner than arbitrary thresholds.

2. **Should B904 be verified as already fixed?**
   - What we know: B904 (raise from) passes clean currently
   - What's unclear: Whether it was fixed in Phase 1 or was already correct
   - Recommendation: No action needed; it passes clean.

## Sources

### Primary (HIGH confidence)
- Direct `ruff check` output against the actual codebase -- all violation counts verified
- `pyproject.toml` -- current configuration inspected directly
- Ruff 0.15.6 installed locally -- rule behavior verified empirically

### Secondary (MEDIUM confidence)
- Ruff documentation for PTH and PLR rule semantics (well-known, stable rules from Pylint/flake8-pathlib origins)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Ruff already configured, just adding rule codes
- Architecture: HIGH -- violations enumerated directly from codebase
- Pitfalls: HIGH -- subprocess/Path interaction is well-documented Python behavior

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable domain, ruff config unlikely to change)

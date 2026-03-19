# Phase 5: Naming & Documentation - Research

**Researched:** 2026-03-19
**Domain:** Python naming conventions, docstring standards, ruff pydocstyle enforcement
**Confidence:** HIGH

## Summary

Phase 5 addresses two related concerns: improving function/variable names across all modules, and adding docstrings to every public function and module. The codebase is a ~1500 LOC Python CLI tool with 14 modules. After Phase 4's structural refactoring, the code is well-organized but has naming and documentation gaps.

**Current state from audit:**
- 11 of 14 modules lack module-level docstrings (only `checks.py`, `init.py`, `shutdown.py` have them)
- 14 public functions lack docstrings across 6 modules (`cli.py`, `config.py`, `daemon.py`, `llm.py`, `processor.py`, `shutdown.py`)
- 3 single-letter variable names exist outside loops in `processor.py` (`i`, `p`)
- Most function names are already good verb-phrases; a few short names in `daemon.py` (`start`, `stop`, `restart`, `status`) are acceptable in context as they are standard daemon lifecycle terms
- `discover` in `cli.py` is a nested function (local closure), not a public function

**Primary recommendation:** Add module docstrings to all 11 missing modules, add docstrings to all 14 undocumented public functions, rename 2-3 ambiguous variables in `processor.py`, and optionally enable ruff `D` rules for ongoing enforcement.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NAME-01 | Functions use clear verb-phrase names that describe their purpose | Audit shows most names are already good. `daemon.py` names (start/stop/restart/status) follow standard CLI daemon conventions and are clear in context. No public function renames needed. |
| NAME-02 | Variables use descriptive names (no single-letter names outside loops/comprehensions) | Found `i` and `p` in `processor.py` L454-470, L506-509. `i` is used as a loop index (while-loop, not for-loop), `p` is a photo reference. Both should be renamed. |
| NAME-03 | Parameters renamed for clarity where current names are ambiguous | Parameter names are already descriptive across all modules. No ambiguous parameters found. |
| DOCS-01 | All public functions have docstrings describing purpose and behavior | 14 public functions missing docstrings: `main`, `load_config`, `save_config`, `set_value`, `reset_config`, `start`, `stop`, `restart`, `status`, `is_running`, `create_client`, `record_failure`, `is_shutting_down` (and `discover` is a nested function, not public) |
| DOCS-02 | All modules have module-level docstrings | 11 modules missing: `__init__.py`, `__main__.py`, `cli.py`, `config.py`, `daemon.py`, `discovery.py`, `exporter.py`, `llm.py`, `metrics.py`, `processor.py`, `writer.py` |
</phase_requirements>

## Standard Stack

No new libraries needed. This phase is purely about editing existing code.

### Tooling for Enforcement

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| ruff | 0.15.6 | Docstring linting via `D` (pydocstyle) rules | Already the project's linter; `D100` (module docstring) and `D103` (function docstring) can enforce the requirements going forward |

**Optional ruff config addition** (to prevent regression after this phase):
```toml
# Add to select list in pyproject.toml [tool.ruff.lint]
select = [..., "D100", "D103"]

# Add pydocstyle convention
[tool.ruff.lint.pydocstyle]
convention = "google"
```

## Architecture Patterns

### Docstring Style

The existing codebase uses **Google-style docstrings** where docstrings exist. Example from `discovery.py`:

```python
def get_unprocessed_media(
    limit: int = 0,
    days_back: int = 0,
    to_days: int = 0,
    photo: bool = True,
    video: bool = True,
) -> list[osxphotos.PhotoInfo]:
    """Query Photos library for unprocessed media (no keywords, not hidden).

    Args:
        limit: Max items to return. 0 = no limit (all unprocessed).
        days_back: Look back N days from now. 0 = no date filter (all photos).
        to_days: Skip the most recent N days (e.g. 7 = exclude last 7 days).
    """
```

**Rule: Follow Google-style consistently.** Single-line docstrings for simple functions, multi-line with `Args:`/`Returns:` sections only when parameters or return values need explanation.

### Module Docstring Pattern

Existing examples to follow:

```python
# checks.py
"""Verify external tool dependencies at startup."""

# init.py
"""Interactive first-run setup wizard."""

# shutdown.py
"""Graceful shutdown handling via SIGINT/SIGTERM."""
```

**Rule: One-line module docstring describing the module's role.** Match the descriptions already in CLAUDE.md's Architecture section.

### Naming Conventions

The codebase follows standard Python conventions:
- `snake_case` for functions and variables
- `_prefix` for private/internal functions
- `UPPER_CASE` for module-level constants
- Verb-phrase names for functions (`process_batch`, `write_metadata`, `export_photo_as_base64`)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docstring enforcement | Manual code review | ruff `D100`/`D103` rules | Automated, catches regressions |
| Docstring formatting | Custom conventions | Google-style (already used) | Consistent with existing code |

## Common Pitfalls

### Pitfall 1: Over-documenting simple functions
**What goes wrong:** Adding verbose multi-line docstrings to trivial functions makes code harder to read.
**Why it happens:** Applying rules uniformly without judgment.
**How to avoid:** Simple functions like `load_config`, `reset_config`, `is_running` need only a one-line docstring. Reserve `Args:`/`Returns:` sections for functions with non-obvious parameters.
**Warning signs:** Docstring is longer than the function body.

### Pitfall 2: Renaming for renaming's sake
**What goes wrong:** Changing well-understood names breaks muscle memory and creates unnecessary churn.
**Why it happens:** Literal interpretation of "verb-phrase names" applied to standard terms.
**How to avoid:** `daemon.start()`, `daemon.stop()`, `daemon.restart()`, `daemon.status()` are idiomatic daemon CLI commands. They don't need renaming. Focus only on genuinely ambiguous names.
**Warning signs:** The new name is longer but not clearer.

### Pitfall 3: Breaking existing imports/callers
**What goes wrong:** Renaming a public function that is imported elsewhere causes import errors.
**Why it happens:** Not checking all call sites before renaming.
**How to avoid:** Before renaming any public function, grep for all usages. In this codebase, the risk is low since no public function renames are needed -- only variable renames within function bodies.

## Detailed Audit Results

### Module Docstrings Needed (DOCS-02)

| Module | Suggested Docstring |
|--------|-------------------|
| `__init__.py` | (empty or package-level description) |
| `__main__.py` | `"""Entry point for python -m labeler."""` |
| `cli.py` | `"""Argparse CLI with run, daemon, config, and metrics subcommands."""` |
| `config.py` | `"""Configuration file management for ~/.image-labeler/config.json."""` |
| `daemon.py` | `"""launchd Launch Agent lifecycle management."""` |
| `discovery.py` | `"""Query macOS Photos library for unprocessed media via osxphotos."""` |
| `exporter.py` | `"""HEIC-to-JPEG photo conversion and video frame extraction."""` |
| `llm.py` | `"""OpenAI-compatible LLM client for photo and video labeling."""` |
| `metrics.py` | `"""SQLite metrics database for tracking processing runs and items."""` |
| `processor.py` | `"""Batch orchestration: parallel photo processing, sequential video processing."""` |
| `writer.py` | `"""PhotoScript metadata writes to macOS Photos.app."""` |

### Public Functions Missing Docstrings (DOCS-01)

| Module | Function | Suggested Docstring |
|--------|----------|-------------------|
| `cli.py` | `main` | `"""Parse CLI arguments and dispatch to the appropriate subcommand."""` |
| `config.py` | `load_config` | `"""Load configuration from disk, creating defaults if the file is missing."""` |
| `config.py` | `save_config` | `"""Write configuration dictionary to disk, filtering to known keys."""` |
| `config.py` | `set_value` | `"""Update a single config key, coercing the string value to the correct type."""` |
| `config.py` | `reset_config` | `"""Reset configuration to default values."""` |
| `daemon.py` | `start` | `"""Install and load the launchd Launch Agent."""` |
| `daemon.py` | `stop` | `"""Unload and remove the launchd Launch Agent."""` |
| `daemon.py` | `restart` | `"""Stop and restart the launchd Launch Agent."""` |
| `daemon.py` | `status` | `"""Print whether the Launch Agent is currently running."""` |
| `daemon.py` | `is_running` | `"""Check if the Launch Agent is loaded in launchctl."""` |
| `llm.py` | `create_client` | `"""Create an OpenAI client configured for the given endpoint."""` |
| `processor.py` | `record_failure` | `"""Record a failure for the given item, raising MaxFailuresExceeded if limit reached."""` |
| `shutdown.py` | `is_shutting_down` | `"""Return True if a graceful shutdown has been requested."""` |

### Variable Renames Needed (NAME-02)

| Module | Line | Current | Suggested | Reason |
|--------|------|---------|-----------|--------|
| `processor.py` | L454 | `i` | `photo_idx` | While-loop index for photo processing; `i` is ambiguous in a 30-line function |
| `processor.py` | L469 | `p` | `photo` | Single-letter alias for a PhotoInfo object |
| `processor.py` | L506 | `i` | `video_idx` | While-loop index for video processing |

### Function Name Assessment (NAME-01, NAME-03)

All public function names are already clear verb-phrases or standard terms:
- `process_batch`, `write_metadata`, `export_photo_as_base64` -- verb-phrase, clear
- `start`, `stop`, `restart`, `status` -- standard daemon lifecycle terms
- `load_config`, `save_config`, `set_value`, `reset_config` -- clear CRUD terms
- `create_client`, `label_photo`, `label_video` -- verb-phrase, clear
- `record_item`, `start_run`, `finish_run` -- verb-phrase, clear

**No public function renames are needed.** All parameter names are also descriptive.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None -- no test infrastructure exists |
| Config file | none |
| Quick run command | N/A |
| Full suite command | N/A |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NAME-01 | Functions use verb-phrase names | manual-only | Visual review of function names | N/A -- naming is subjective |
| NAME-02 | No single-letter variables outside loops | lint | `ruff check labeler/ --select E741` (partial) | N/A |
| DOCS-01 | All public functions have docstrings | lint | `ruff check labeler/ --select D103` | N/A -- rule not yet enabled |
| DOCS-02 | All modules have module-level docstrings | lint | `ruff check labeler/ --select D100` | N/A -- rule not yet enabled |

### Sampling Rate
- **Per task commit:** `ruff check labeler/ --select D100,D103` (after enabling D rules)
- **Per wave merge:** `ruff check .` (full suite)
- **Phase gate:** `ruff check .` green + manual review of variable names

### Wave 0 Gaps
- [ ] Enable ruff `D100` and `D103` rules in pyproject.toml for enforcement
- [ ] Optionally set `[tool.ruff.lint.pydocstyle] convention = "google"` for style consistency

## Sources

### Primary (HIGH confidence)
- Direct codebase audit via AST parsing -- complete inventory of all modules, functions, variables
- Existing ruff configuration in `pyproject.toml` -- confirmed available rules
- `ruff rule D100` and `ruff rule D103` -- confirmed pydocstyle rules available in ruff 0.15.6

### Secondary (MEDIUM confidence)
- Google Python Style Guide docstring conventions -- matched against existing codebase patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, pure code editing
- Architecture: HIGH - following existing patterns already established in codebase
- Pitfalls: HIGH - based on direct codebase audit, all findings verified

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable -- naming/documentation conventions don't change)

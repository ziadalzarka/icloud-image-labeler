# iCloud Image Labeler — Code Quality

## What This Is

A code quality initiative for the icloud-image-labeler CLI tool. Professionalized the codebase by enforcing consistent formatting with Ruff, decomposing long functions, cleaning up dead code, improving naming, and adding comprehensive documentation.

## Core Value

The codebase should be clean, consistent, and easy to read — every module should look like it was written by one person following clear conventions.

## Current State

**v1.0 shipped 2026-03-20** — All code quality goals achieved.

- 1,958 LOC across 14 Python modules in `labeler/`
- Zero ruff violations (rules: E, F, W, I, SIM, C4, PTH, RET, PLR, C901, D100, D103)
- All functions under 30 lines of logic, flat control flow with guard clauses
- All public functions and modules have Google-style docstrings
- All magic literals extracted to named constants

## Requirements

### Validated

- ✓ CLI with `run`, `daemon`, `config`, `init` subcommands — existing
- ✓ osxphotos-based discovery of unprocessed media — existing
- ✓ HEIC-to-JPEG export with derivative fallback — existing
- ✓ OpenAI-compatible LLM client with retry logic — existing
- ✓ Parallel photo / sequential video batch processing — existing
- ✓ PhotoScript metadata writing with thread-safe locking — existing
- ✓ Graceful shutdown with signal handlers — existing
- ✓ SQLite metrics collection — existing
- ✓ launchd daemon lifecycle management — existing
- ✓ Interactive init wizard for first-run setup — existing
- ✓ Homebrew tap distribution — existing
- ✓ Ruff linting and formatting across all modules — v1.0
- ✓ Break up long/complex functions into smaller, well-named pieces — v1.0
- ✓ Improve variable, function, and module naming for clarity — v1.0
- ✓ Remove dead code (unused imports, functions, commented-out blocks) — v1.0
- ✓ All modules and public functions documented with docstrings — v1.0

### Active

(None — next milestone TBD)

### Out of Scope

- Type annotations — not part of this initiative
- CI/pre-commit hooks — may add later but not now
- New features or behavior changes — purely structural/cosmetic
- Test additions — cleanup only, no new tests

## Context

The codebase is a Python 3.10+ macOS CLI tool (14 modules in `labeler/`). After v1.0 code quality initiative, all modules are consistently formatted, well-documented, and structurally clean.

Key modules: `cli.py`, `config.py`, `discovery.py`, `exporter.py`, `llm.py`, `processor.py`, `writer.py`, `metrics.py`, `daemon.py`, `init.py`, `checks.py`, `shutdown.py`

## Constraints

- **No behavior changes**: All refactoring preserved existing functionality exactly
- **Tool**: Ruff for both linting and formatting (replaces black/isort/flake8)
- **Python**: 3.10+ compatibility maintained

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Ruff over Black+isort | All-in-one, extremely fast, modern standard | ✓ Validated Phase 1 |
| No type annotations | Keep scope focused on formatting and structure | ✓ Good — kept scope tight |
| No CI/pre-commit | Can add separately later; this is about the code itself | ✓ Good — focused on code |
| _BatchState dataclass for processor | Replace nonlocal closures with mutable state object | ✓ Validated Phase 4 |
| Google-style docstrings | Match existing patterns already in codebase | ✓ Validated Phase 5 |
| D100/D103 ruff enforcement | Prevent regression on documentation | ✓ Validated Phase 5 |

---
*Last updated: 2026-03-20 after v1.0 milestone*

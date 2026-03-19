# iCloud Image Labeler — Code Quality

## What This Is

A code quality initiative for the icloud-image-labeler CLI tool. The goal is to professionalize the codebase by enforcing consistent formatting with Ruff, cleaning up code structure (long functions, poor naming, dead code), and making every module readable and well-organized.

## Core Value

The codebase should be clean, consistent, and easy to read — every module should look like it was written by one person following clear conventions.

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

### Active

- [ ] Ruff linting and formatting across all modules
- [ ] Break up long/complex functions into smaller, well-named pieces
- [ ] Improve variable, function, and module naming for clarity
- [ ] Remove dead code (unused imports, functions, commented-out blocks)
- [ ] General cleanup — consistent patterns, logical organization within modules

### Out of Scope

- Type annotations — not part of this initiative
- CI/pre-commit hooks — may add later but not now
- New features or behavior changes — purely structural/cosmetic
- Test additions — cleanup only, no new tests

## Context

The codebase is a Python 3.10+ macOS CLI tool (~8 modules in `labeler/`). It works well functionally but grew organically — some functions are long, naming is inconsistent, and there's likely dead code from iterative development. The codebase map identified several concerns in code structure that align with this cleanup effort.

Key modules: `cli.py`, `config.py`, `discovery.py`, `exporter.py`, `llm.py`, `processor.py`, `writer.py`, `metrics.py`, `daemon.py`, `init.py`

## Constraints

- **No behavior changes**: All refactoring must preserve existing functionality exactly
- **Tool**: Ruff for both linting and formatting (replaces black/isort/flake8)
- **Python**: 3.10+ compatibility must be maintained

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Ruff over Black+isort | All-in-one, extremely fast, modern standard | — Pending |
| No type annotations | Keep scope focused on formatting and structure | — Pending |
| No CI/pre-commit | Can add separately later; this is about the code itself | — Pending |

---
*Last updated: 2026-03-19 after initialization*

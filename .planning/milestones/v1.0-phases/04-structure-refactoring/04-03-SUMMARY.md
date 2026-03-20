---
phase: 04-structure-refactoring
plan: 03
subsystem: code-quality
tags: [ruff, constants, magic-numbers, linting, pylint]

# Dependency graph
requires:
  - phase: 04-structure-refactoring
    provides: "Decomposed processor.py and cli.py (Plans 01-02)"
provides:
  - Named constants replacing all magic literals across 5 modules
  - Stricter ruff enforcement with PLR0912/PLR0915 enabled
affects: [05-naming-docs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level named constants for all domain-specific magic numbers/strings"
    - "Private prefix (_POLL_INTERVAL) for internal constants, public for API-facing (DEFAULT_REFRESH_INTERVAL)"

key-files:
  created: []
  modified:
    - labeler/processor.py
    - labeler/cli.py
    - labeler/exporter.py
    - labeler/llm.py
    - labeler/writer.py
    - pyproject.toml

key-decisions:
  - "Kept 1024, 0.5, 0/1 as-is per research anti-patterns (self-documenting or mathematical)"
  - "Used private prefix for internal constants, public for user-facing defaults"

patterns-established:
  - "Named constants at module level for all timeouts, intervals, quality settings, and ports"
  - "PLR0912/PLR0915 enforced via ruff to prevent complexity regression"

requirements-completed: [STRC-04, STRC-06]

# Metrics
duration: 2min
completed: 2026-03-19
---

# Phase 04 Plan 03: Magic Literals and Lint Enforcement Summary

**12 magic literals replaced with named constants across 5 modules, PLR0912/PLR0915 removed from ruff ignore list**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-19T16:13:07Z
- **Completed:** 2026-03-19T16:15:13Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Extracted 12 magic literals to named module-level constants across processor.py, cli.py, exporter.py, llm.py, and writer.py
- Removed PLR0912 (too many branches) and PLR0915 (too many statements) from ruff ignore list
- All modules pass stricter ruff complexity enforcement, preventing regression of Plans 01-02 decomposition work

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract magic literals to named constants across all modules** - `ab9dcac` (refactor)
2. **Task 2: Verify remaining modules + remove PLR0912/PLR0915 from ruff ignore list** - `d04d50e` (chore)

## Files Created/Modified
- `labeler/processor.py` - Added _POLL_INTERVAL, _FUTURE_DRAIN_TIMEOUT, DEFAULT_REFRESH_INTERVAL constants
- `labeler/cli.py` - Added DEFAULT_REFRESH_INTERVAL, DEFAULT_DATASETTE_PORT constants
- `labeler/exporter.py` - Added PHOTO_EXPORT_TIMEOUT, VIDEO_EXPORT_TIMEOUT, JPEG_QUALITY, FFMPEG_QUALITY constants
- `labeler/llm.py` - Added LLM_TIMEOUT, LLM_TEMPERATURE constants
- `labeler/writer.py` - Added PHOTOS_APP_STARTUP_WAIT constant
- `pyproject.toml` - Removed PLR0912 and PLR0915 from ruff ignore list

## Decisions Made
- Kept 1024 (max_dimension default), 0.5 (timestamp formula), and 0/1 (indices) as-is per research anti-patterns -- they are self-documenting or mathematical, not domain constants
- Used private underscore prefix for internal-only constants (_POLL_INTERVAL, _FUTURE_DRAIN_TIMEOUT), public names for user-facing defaults (DEFAULT_REFRESH_INTERVAL)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 04 (structure-refactoring) is now complete
- All structural improvements applied: function decomposition, magic literal extraction, lint enforcement
- Ready for Phase 05 (naming-docs) if planned

## Self-Check: PASSED

All files exist. Both commits verified (ab9dcac, d04d50e). All 12 named constants present. No bare magic literals remain. Ruff passes with stricter config.

---
*Phase: 04-structure-refactoring*
*Completed: 2026-03-19*

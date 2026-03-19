---
phase: 02-automated-lint-fixes
plan: 01
subsystem: tooling
tags: [ruff, pathlib, lint, PTH, PLR]

# Dependency graph
requires:
  - phase: 01-formatting-lint-setup
    provides: "Ruff config in pyproject.toml with base rule sets"
provides:
  - "Expanded ruff rule config with PTH, PLR, and complexity ignores"
  - "pathlib-based path operations across 4 modules"
  - "Named HTTP status constants in processor.py"
affects: [04-restructure-simplify]

# Tech tracking
tech-stack:
  added: []
  patterns: [pathlib for all path operations, named constants for magic values]

key-files:
  created: []
  modified:
    - pyproject.toml
    - labeler/config.py
    - labeler/daemon.py
    - labeler/exporter.py
    - labeler/metrics.py
    - labeler/processor.py
    - labeler/init.py
    - labeler/writer.py

key-decisions:
  - "PLR complexity rules (PLR0912, PLR0913, PLR0915) deferred to Phase 4 via ignore list"
  - "Path objects wrapped in str() when passed to subprocess or sqlite3"

patterns-established:
  - "pathlib.Path for all file path operations instead of os.path"
  - "Named constants for HTTP status codes instead of magic numbers"

requirements-completed: [TOOL-03, TOOL-06, DEAD-01]

# Metrics
duration: 2min
completed: 2026-03-19
---

# Phase 02 Plan 01: Expanded Ruff Rules Summary

**Enabled PTH and PLR ruff rule sets, converted os.path to pathlib in 4 modules, replaced magic HTTP status values with named constants**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-19T14:55:10Z
- **Completed:** 2026-03-19T14:57:00Z
- **Tasks:** 1
- **Files modified:** 8

## Accomplishments
- Expanded ruff select list with PTH (pathlib) and PLR (pylint refactor) rule sets
- Converted all os.path calls to pathlib equivalents in config.py, daemon.py, exporter.py, metrics.py
- Replaced PLR2004 magic HTTP status values (500, 400) with named constants in processor.py
- Deferred PLR complexity rules to Phase 4 via ignore list
- Cleaned unused imports (F401) and f-strings with no placeholders in init.py and writer.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Update Ruff config and fix all PTH + PLR violations** - `e046196` (feat)

## Files Created/Modified
- `pyproject.toml` - Added PTH, PLR to select; PLR0912, PLR0913, PLR0915 to ignore
- `labeler/config.py` - CONFIG_PATH.open() instead of open(CONFIG_PATH)
- `labeler/daemon.py` - Path(__file__).resolve().parent.parent, removed import os
- `labeler/exporter.py` - Full pathlib conversion for all os.path calls, removed import os
- `labeler/metrics.py` - Path.home() for DB_PATH, Path.parent.mkdir, removed import os
- `labeler/processor.py` - _HTTP_SERVER_ERROR and _HTTP_BAD_REQUEST named constants
- `labeler/init.py` - Removed unused json/sys imports, fixed bare f-strings
- `labeler/writer.py` - Fixed bare f-strings

## Decisions Made
- PLR complexity rules deferred to Phase 4 (restructuring) rather than fixing now
- Path objects wrapped in str() when passed to subprocess or sqlite3.connect()

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unused imports and bare f-strings via ruff --fix**
- **Found during:** Task 1 (ruff --fix auto-pass)
- **Issue:** init.py had unused json/sys imports (F401); init.py and writer.py had f-strings with no placeholders
- **Fix:** ruff check --fix automatically removed unused imports and converted bare f-strings
- **Files modified:** labeler/init.py, labeler/writer.py
- **Verification:** ruff check --select F401 . passes
- **Committed in:** e046196 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Auto-fix caught additional violations from existing rules in newly-checked files. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All auto-fixable lint violations resolved
- Codebase uses modern pathlib patterns consistently
- PLR complexity rules ready to be addressed in Phase 4 restructuring

---
*Phase: 02-automated-lint-fixes*
*Completed: 2026-03-19*

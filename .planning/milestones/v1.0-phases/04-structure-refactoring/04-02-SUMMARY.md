---
phase: 04-structure-refactoring
plan: 02
subsystem: cli, exporter
tags: [refactoring, decomposition, guard-clauses, argparse]

requires:
  - phase: 04-structure-refactoring-01
    provides: processor.py decomposition patterns established
provides:
  - Decomposed cli.py with _build_parser, _build_run_parser, _resolve_config helpers
  - Decomposed exporter.py with 6 focused helpers replacing monolithic functions
affects: [04-structure-refactoring-03]

tech-stack:
  added: []
  patterns: [extract-and-delegate decomposition, guard clause flattening, config resolution dict]

key-files:
  created: []
  modified:
    - labeler/cli.py
    - labeler/exporter.py

key-decisions:
  - "Config resolution returns a dict rather than a dataclass -- lightweight for internal use within _run()"
  - "_extract_frame returns bool instead of raising -- caller decides how to handle missing frames"

patterns-established:
  - "Config resolution pattern: _resolve_config merges CLI args with config file defaults into a dict"
  - "Guard clause pattern: early return None/_raise instead of nested if/elif/else chains"

requirements-completed: [STRC-02, STRC-03, STRC-05]

duration: 3min
completed: 2026-03-19
---

# Phase 04 Plan 02: CLI and Exporter Decomposition Summary

**Decomposed cli.py (main 92->15 lines, _run 68->30 lines) and exporter.py (export_photo 60->5 lines, export_video 95->12 lines) into focused helpers with guard clauses**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-19T16:08:07Z
- **Completed:** 2026-03-19T16:10:50Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- cli.py main() reduced from 92 to 15 lines via _build_parser() and _build_run_parser() extraction
- cli.py _run() simplified by extracting config merge logic into _resolve_config() returning a dict
- exporter.py export_photo_as_base64 reduced to 5-line coordinator with 3 helpers
- exporter.py export_video_frames_as_base64 reduced to 12-line coordinator with 3 helpers
- Deep nesting in exporter.py flattened with guard clauses (early returns)

## Task Commits

Each task was committed atomically:

1. **Task 1: Decompose cli.py** - `d4967c4` (refactor)
2. **Task 2: Decompose exporter.py** - `f75fa9a` (refactor)

## Files Created/Modified
- `labeler/cli.py` - Extracted _build_parser, _build_run_parser, _resolve_config; main() and _run() reduced to coordinators
- `labeler/exporter.py` - Extracted _resolve_export_path, _open_or_fallback, _encode_as_jpeg, _get_video_duration, _extract_frame, _extract_all_frames

## Decisions Made
- Config resolution uses a plain dict rather than dataclass -- it is only consumed within _run() so the overhead of a class is unnecessary
- _extract_frame returns a boolean success flag rather than raising on failure, allowing the caller loop to skip missing frames gracefully

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- cli.py and exporter.py fully decomposed, ready for Plan 03 (constants extraction and lint rule enablement)
- All public function signatures preserved -- no downstream changes needed

---
*Phase: 04-structure-refactoring*
*Completed: 2026-03-19*

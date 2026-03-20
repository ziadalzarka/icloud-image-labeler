# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Code Quality

**Shipped:** 2026-03-20
**Phases:** 5 | **Plans:** 7

### What Was Built
- Ruff linter/formatter with comprehensive rule sets (E, F, W, I, SIM, C4, PTH, RET, PLR, C901, D100, D103)
- All 14 modules formatted consistently with zero lint violations
- Dead code removed (unused imports, functions, commented-out blocks)
- Long functions decomposed — processor.py's 220-line C901=26 function into 7 focused helpers
- Guard clause flattening across cli.py, exporter.py, processor.py
- Magic literals extracted to named constants across 5 modules
- Google-style docstrings on all modules and public functions

### What Worked
- Layered phase approach: format → auto-fix → dead code → structure → naming. Each phase built cleanly on the previous
- Ruff as single tool for linting + formatting eliminated tool conflicts
- Research-before-planning pattern: AST-based audits gave exact function sizes and violation counts, making plans precise
- _BatchState dataclass pattern elegantly solved the nonlocal closure problem in processor.py decomposition

### What Was Inefficient
- Phase 3 (Dead Code Removal) had minimal scope — vulture found nothing, only E501 fixes remained. Could have been merged into Phase 2
- Some ROADMAP progress tracking got out of sync (Phase 3 and 5 showed "Not started" even after completion)

### Patterns Established
- Google-style docstrings as project convention
- Ruff D100/D103 enforcement prevents documentation regression
- PLR0912/PLR0915 enforcement prevents function complexity regression
- Guard clause pattern for flattening deep nesting

### Key Lessons
1. For code quality initiatives, research with concrete metrics (line counts, complexity scores) makes planning nearly mechanical
2. Single-plan phases work well for mechanical tasks (formatting, docstrings) — no need to over-split
3. Removing lint rule ignores from pyproject.toml is as important as the refactoring itself — it prevents regression

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 7 | Initial milestone — established layered refactoring approach |

### Top Lessons (Verified Across Milestones)

1. Research with concrete metrics makes planning precise and reduces execution surprises
2. Layered approach (format → fix → restructure → document) prevents cascading diffs

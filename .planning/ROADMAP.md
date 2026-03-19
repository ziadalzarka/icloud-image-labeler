# Roadmap: iCloud Image Labeler -- Code Quality

## Overview

This roadmap takes the codebase from its current organic state to a clean, consistent, professional codebase. The approach is layered: establish automated formatting first (creating clean diffs for everything after), then let tools fix what they can, then manually remove dead code, then restructure functions, and finally polish naming and documentation. Each phase builds on the previous -- formatting before fixes, fixes before refactoring, refactoring before renaming.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Ruff Setup & Formatting** - Configure Ruff in pyproject.toml and format all modules consistently
- [ ] **Phase 2: Automated Lint Fixes** - Run auto-fixable lint rules and expanded rule sets across all modules
- [ ] **Phase 3: Dead Code Removal** - Manually remove unused functions, variables, and commented-out code blocks
- [ ] **Phase 4: Structure Refactoring** - Decompose long functions, flatten nesting, and extract constants
- [ ] **Phase 5: Naming & Documentation** - Improve names across all modules and add docstrings

## Phase Details

### Phase 1: Ruff Setup & Formatting
**Goal**: Every module has consistent formatting and import ordering enforced by Ruff
**Depends on**: Nothing (first phase)
**Requirements**: TOOL-01, TOOL-02, TOOL-05
**Success Criteria** (what must be TRUE):
  1. `ruff format --check .` passes with zero violations on all modules
  2. `ruff check --select I .` (isort rules) passes with zero violations
  3. Ruff configuration exists in pyproject.toml with target-version = "py310" and selected rule sets
  4. All existing functionality still works identically (no behavior changes from formatting)
**Plans**: TBD

Plans:
- [ ] 01-01: TBD

### Phase 2: Automated Lint Fixes
**Goal**: All auto-fixable lint violations are resolved, including expanded rule sets
**Depends on**: Phase 1
**Requirements**: TOOL-03, TOOL-06, DEAD-01
**Success Criteria** (what must be TRUE):
  1. `ruff check .` passes with zero auto-fixable violations remaining
  2. Expanded rule sets (SIM, C4, PTH, RET, PLR) are enabled and all their auto-fixable violations resolved
  3. No unused imports remain in any module
  4. All existing functionality still works identically after auto-fixes
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: Dead Code Removal
**Goal**: All dead code and remaining manual lint violations are cleaned up
**Depends on**: Phase 2
**Requirements**: TOOL-04, DEAD-02, DEAD-03
**Success Criteria** (what must be TRUE):
  1. `ruff check .` passes with zero violations (including non-auto-fixable rules)
  2. No unused functions or variables exist in any module
  3. No commented-out code blocks remain in any module
  4. All existing functionality still works identically after removals
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: Structure Refactoring
**Goal**: All modules have short, focused functions with flat control flow and named constants
**Depends on**: Phase 3
**Requirements**: STRC-01, STRC-02, STRC-03, STRC-04, STRC-05, STRC-06
**Success Criteria** (what must be TRUE):
  1. No function in processor.py, cli.py, or exporter.py exceeds ~30 lines of logic
  2. Deeply nested blocks (3+ levels) are replaced with guard clauses or early returns
  3. Magic numbers and strings are replaced with named constants at module level
  4. Helper functions extracted during decomposition have clear, descriptive names
  5. All existing functionality still works identically after restructuring
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: Naming & Documentation
**Goal**: Every public function and module has clear naming and documentation
**Depends on**: Phase 4
**Requirements**: NAME-01, NAME-02, NAME-03, DOCS-01, DOCS-02
**Success Criteria** (what must be TRUE):
  1. All public functions use clear verb-phrase names that describe their purpose
  2. No ambiguous single-letter variable names exist outside loops and comprehensions
  3. All public functions have docstrings describing purpose and behavior
  4. All modules have module-level docstrings describing their role
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Ruff Setup & Formatting | 0/? | Not started | - |
| 2. Automated Lint Fixes | 0/? | Not started | - |
| 3. Dead Code Removal | 0/? | Not started | - |
| 4. Structure Refactoring | 0/? | Not started | - |
| 5. Naming & Documentation | 0/? | Not started | - |

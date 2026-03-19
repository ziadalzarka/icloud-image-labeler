# Requirements: iCloud Image Labeler -- Code Quality

**Defined:** 2026-03-19
**Core Value:** Clean, consistent, professional codebase that's easy to read and maintain

## v1 Requirements

Requirements for code quality initiative. Each maps to roadmap phases.

### Tooling

- [x] **TOOL-01**: Ruff configuration added to pyproject.toml with target version py310, line length, and selected rule sets
- [x] **TOOL-02**: All modules formatted consistently via `ruff format`
- [x] **TOOL-03**: All auto-fixable lint violations resolved via `ruff check --fix`
- [x] **TOOL-04**: All remaining lint violations that require human judgment resolved manually
- [x] **TOOL-05**: Imports sorted consistently across all modules via Ruff isort rules
- [x] **TOOL-06**: Expanded rule sets enabled (SIM, C4, PTH, RET, PLR) and violations resolved

### Dead Code

- [x] **DEAD-01**: All unused imports removed across all modules
- [x] **DEAD-02**: All unused functions and variables removed
- [x] **DEAD-03**: All commented-out code blocks removed

### Structure

- [x] **STRC-01**: Long functions in `processor.py` decomposed into focused helpers
- [x] **STRC-02**: Long functions in `cli.py` decomposed into focused helpers
- [x] **STRC-03**: Long functions in `exporter.py` decomposed into focused helpers
- [ ] **STRC-04**: Long functions in remaining modules decomposed where needed
- [x] **STRC-05**: Deep nesting replaced with guard clauses / early returns where applicable
- [ ] **STRC-06**: Magic numbers and strings extracted into named constants

### Naming

- [ ] **NAME-01**: Functions use clear verb-phrase names that describe their purpose
- [ ] **NAME-02**: Variables use descriptive names (no single-letter names outside loops/comprehensions)
- [ ] **NAME-03**: Parameters renamed for clarity where current names are ambiguous

### Documentation

- [ ] **DOCS-01**: All public functions have docstrings describing purpose and behavior
- [ ] **DOCS-02**: All modules have module-level docstrings

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Automation

- **AUTO-01**: Pre-commit hooks enforce Ruff formatting and linting on every commit
- **AUTO-02**: CI pipeline runs Ruff checks on pull requests

### Additional Cleanup

- **CLNP-01**: Module-level organization pattern (imports -> constants -> classes -> public -> private)
- **CLNP-02**: Error message consistency across all modules
- **CLNP-03**: Type annotations on public function signatures

## Out of Scope

| Feature | Reason |
|---------|--------|
| Type annotations (mypy/pyright) | Massive scope expansion; marginal value for 1500 LOC project |
| Test additions | Separate initiative; mixing with cleanup doubles scope |
| Behavior changes | Must preserve existing functionality exactly |
| OOP refactoring | Procedural/functional style works well for this CLI tool |
| Pylint/Flake8 alongside Ruff | Ruff covers their important rules; multiple linters create conflicts |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TOOL-01 | Phase 1 | Complete |
| TOOL-02 | Phase 1 | Complete |
| TOOL-03 | Phase 2 | Complete |
| TOOL-04 | Phase 3 | Complete |
| TOOL-05 | Phase 1 | Complete |
| TOOL-06 | Phase 2 | Complete |
| DEAD-01 | Phase 2 | Complete |
| DEAD-02 | Phase 3 | Complete |
| DEAD-03 | Phase 3 | Complete |
| STRC-01 | Phase 4 | Complete |
| STRC-02 | Phase 4 | Complete |
| STRC-03 | Phase 4 | Complete |
| STRC-04 | Phase 4 | Pending |
| STRC-05 | Phase 4 | Complete |
| STRC-06 | Phase 4 | Pending |
| NAME-01 | Phase 5 | Pending |
| NAME-02 | Phase 5 | Pending |
| NAME-03 | Phase 5 | Pending |
| DOCS-01 | Phase 5 | Pending |
| DOCS-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-19 after roadmap creation*

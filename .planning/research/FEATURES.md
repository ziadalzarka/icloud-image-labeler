# Feature Research

**Domain:** Python code quality enforcement for a small CLI codebase (~1500 LOC, 14 modules)
**Researched:** 2026-03-19
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Must Have for a Professional Codebase)

Features that any well-maintained Python project should have. Missing these signals neglect.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Automated formatting (Ruff formatter) | Eliminates style debates, ensures visual consistency across all modules | LOW | Single `ruff format .` pass. Non-destructive to logic. Do this first since it touches every line and creates clean diffs for subsequent changes. |
| Lint rule enforcement (Ruff linter) | Catches real bugs (unused imports, undefined names, unreachable code) and enforces style | LOW | Start with default rules (F, E4, E7, E9), then expand to B (bugbear), UP (pyupgrade), I (isort). Configure in pyproject.toml. |
| Import sorting and organization | Unsorted imports signal a messy codebase; sorted imports make dependency scanning trivial | LOW | Ruff's `I` (isort) rules handle this. Include in the lint rule set. |
| Dead code removal | Unused imports, unreachable branches, and commented-out code add noise and confuse readers | LOW | Ruff's F rules catch unused imports/variables. Manual pass needed for commented-out blocks and unused functions Ruff cannot detect. |
| Ruff configuration in pyproject.toml | The project already has pyproject.toml; co-locating tool config is standard practice | LOW | Add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]` sections. Pin target Python version to `py310`. |
| Function decomposition (long functions) | Functions over ~50 lines are hard to read, test, and debug. `processor.py` at 386 lines likely has several. | MEDIUM | Requires understanding logic to extract helpers. Focus on the biggest modules first: processor.py (386L), cli.py (240L), exporter.py (164L). |
| Consistent naming conventions | Mixed naming styles (abbreviations vs full words, inconsistent verb choices) make code harder to navigate | MEDIUM | Rename for clarity: functions should be verb-phrases, variables should be descriptive nouns. Requires careful grep to update all call sites. |
| Docstrings on public functions | Professional code documents intent. Even brief one-liners on public functions make the codebase navigable. | LOW | Add module-level and function-level docstrings where missing. Keep them short and useful, not boilerplate. |

### Differentiators (Nice to Have, Not Required)

Features that go beyond baseline quality. Valuable but not essential for this cleanup scope.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Expanded Ruff rule sets (SIM, C4, PTH, RET, PLR) | SIM catches simplifiable code, C4 catches list-comp anti-patterns, PTH modernizes os.path to pathlib, RET flags inconsistent returns, PLR catches complexity issues | LOW | Enable incrementally after core rules are stable. Each rule set adds a category of cleanup. |
| Constants extraction | Replace magic numbers/strings with named constants (e.g., default timeouts, retry counts, dimension limits) | LOW | Improves readability and makes tuning easier. Grep for hardcoded numeric literals. |
| Module-level organization pattern | Consistent ordering within each file: imports, constants, classes, public functions, private helpers | LOW | Creates predictability when navigating any module. |
| Guard clauses over nested conditionals | Replace deep nesting with early returns. Reduces indentation levels and improves readability. | MEDIUM | Requires understanding control flow to safely restructure. Particularly relevant in processor.py. |
| Error message consistency | Standardize how errors are logged/reported across modules (consistent format, context included) | LOW | Improves debuggability. Review logging patterns across modules. |

### Anti-Features (Deliberately NOT Doing)

Features that seem beneficial but are out of scope, premature, or counterproductive for this initiative.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Type annotations (mypy/pyright) | Catches type bugs at analysis time | Massive scope expansion on a 1500 LOC project with no existing annotations. Adding types to osxphotos/photoscript integration code requires stub knowledge. PROJECT.md explicitly excludes this. | Defer to a separate milestone if ever needed. The codebase is small enough that types add marginal value. |
| Pre-commit hooks / CI pipeline | Enforces rules automatically on every commit | Adds infrastructure overhead to a single-developer project. PROJECT.md explicitly defers this. | Run `ruff check` and `ruff format` manually or via a simple Makefile target. Add hooks later if contributors join. |
| Test additions | Tests catch regressions during refactoring | Writing tests is a separate initiative. Mixing test-writing with cleanup doubles the scope. PROJECT.md explicitly excludes this. | Refactor carefully by preserving all public interfaces. Run the tool manually to verify behavior after changes. |
| Aggressive OOP refactoring | Classes can encapsulate related state and behavior | The codebase is procedural/functional and works well that way. Forcing classes onto a small CLI tool adds abstraction without benefit. | Keep the current module-based organization. Extract functions, not classes. |
| Pylint / Flake8 alongside Ruff | More rules, different perspectives | Ruff already reimplements the important rules from both. Running multiple linters creates conflicting opinions and config sprawl. | Use Ruff exclusively. It covers F (pyflakes), E/W (pycodestyle), B (bugbear), UP (pyupgrade), I (isort), and many more. |
| Docstring enforcement via lint rules (D) | Ensures every function has docs | Forces boilerplate docstrings like "This function does X" on obvious helpers. Noise-to-signal ratio is bad for small codebases. | Add docstrings manually where they genuinely help. Skip obvious private helpers. |
| Behavior changes disguised as refactoring | "While we're in there, let's also fix this bug..." | Mixing behavior changes with structural cleanup makes it impossible to verify the refactoring preserved correctness. | Strictly cosmetic/structural changes only. File behavior-change issues separately. |

## Feature Dependencies

```
[Ruff configuration in pyproject.toml]
    |
    +--enables--> [Automated formatting]
    |                 |
    |                 +--should precede--> [All other changes]
    |                                      (formatting first creates clean baseline)
    |
    +--enables--> [Lint rule enforcement]
    |                 |
    |                 +--includes--> [Import sorting]
    |                 +--includes--> [Dead code removal (unused imports)]
    |
    +--enables--> [Expanded rule sets]

[Automated formatting] --must precede--> [Function decomposition]
    (format first so extracted functions match project style)

[Automated formatting] --must precede--> [Naming improvements]
    (format first to avoid double-touching files)

[Function decomposition] --independent of--> [Naming improvements]
    (can be done in parallel per-module, but better to decompose first
     so new extracted functions get good names from the start)

[Dead code removal] --should precede--> [Function decomposition]
    (remove noise first so you're not refactoring dead code)
```

### Dependency Notes

- **Ruff config must come first:** Everything depends on having the tool configured.
- **Formatting before all other changes:** Running the formatter first means subsequent diffs show only meaningful structural changes, not mixed formatting+logic changes.
- **Dead code removal before decomposition:** No point extracting or renaming code that should be deleted.
- **Decomposition before naming:** When you extract a helper function, you name it at creation time. Better to decompose first so naming covers the new functions too.

## MVP Definition

### Phase 1: Tooling and Formatting (v1)

Minimum viable cleanup -- establishes the foundation everything else builds on.

- [ ] Ruff configuration in pyproject.toml (target version, rule selection, line length)
- [ ] `ruff format` across all modules (single pass, commit the result)
- [ ] `ruff check --fix` for auto-fixable lint violations (unused imports, import sorting)
- [ ] Manual fix of remaining lint violations that require human judgment

### Phase 2: Structural Cleanup (v1.x)

Apply once formatting is stable and committed.

- [ ] Dead code removal (commented-out blocks, unused functions beyond what Ruff catches)
- [ ] Function decomposition in large modules (processor.py, cli.py, exporter.py)
- [ ] Naming improvements (variables, functions, parameters)
- [ ] Docstrings on public functions and modules

### Future Consideration (v2+)

Defer until the core cleanup is validated.

- [ ] Expanded Ruff rule sets (SIM, C4, PTH, RET, PLR) -- add incrementally
- [ ] Constants extraction for magic values
- [ ] Guard clause refactoring for deeply nested conditionals
- [ ] Pre-commit hooks (if contributors join the project)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Ruff config in pyproject.toml | HIGH | LOW | P1 |
| Automated formatting | HIGH | LOW | P1 |
| Lint rule enforcement | HIGH | LOW | P1 |
| Import sorting | HIGH | LOW | P1 |
| Dead code removal | HIGH | LOW | P1 |
| Function decomposition | HIGH | MEDIUM | P1 |
| Naming improvements | MEDIUM | MEDIUM | P2 |
| Docstrings on public functions | MEDIUM | LOW | P2 |
| Expanded Ruff rule sets | MEDIUM | LOW | P2 |
| Constants extraction | LOW | LOW | P3 |
| Module-level organization | LOW | LOW | P3 |
| Guard clause refactoring | LOW | MEDIUM | P3 |
| Error message consistency | LOW | LOW | P3 |

**Priority key:**
- P1: Core cleanup -- the reason this initiative exists
- P2: Should have, adds meaningful quality once P1 is done
- P3: Nice to have, diminishing returns for a 1500 LOC project

## Sources

- [Ruff Linter documentation](https://docs.astral.sh/ruff/linter/)
- [Ruff Rules reference](https://docs.astral.sh/ruff/rules/)
- [Ruff Formatter documentation](https://docs.astral.sh/ruff/formatter/)
- [Real Python: Python Code Quality](https://realpython.com/python-code-quality/)
- [Top Python Code Quality Tools 2026](https://www.qodo.ai/blog/python-code-quality-tools/)

---
*Feature research for: Python code quality enforcement*
*Researched: 2026-03-19*

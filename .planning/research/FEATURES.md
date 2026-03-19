# Feature Landscape

**Domain:** Python code quality enforcement
**Researched:** 2026-03-19

## Table Stakes

Features that must be present for the code quality milestone to be considered complete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Consistent formatting across all modules | Baseline readability; the whole point of adding a formatter | Low | `ruff format` handles this in one command |
| Import sorting and grouping | Inconsistent imports are the most visible code smell | Low | `I` rule set with `known-first-party = ["labeler"]` |
| Unused import removal | Dead imports are noise and confuse readers | Low | `F401` auto-fix |
| Commented-out code removal | PROJECT.md explicitly requires this | Low | `ERA` rule set detects it; manual removal |
| Syntax modernization for Python 3.10+ | Project targets 3.10+; old syntax patterns look unmaintained | Low | `UP` rule set auto-fixes most cases |
| Long function decomposition | PROJECT.md explicitly requires breaking up complex functions | High | Manual work; Ruff flags complexity but cannot fix it |
| Dead code removal (unused functions) | PROJECT.md explicitly requires this | Medium | `ARG` + `F` detect some; manual review needed for the rest |
| Consistent naming patterns | PROJECT.md explicitly requires this | Medium | Manual work; `N` rules are too rigid, do this by hand |

## Differentiators

Features that go beyond minimum requirements but add value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Bug prevention rules (`B`) | Catch mutable default args, bare excepts before they cause issues | Low | `B` rule set; auto-fixable |
| Code simplification (`SIM`) | Reduce cognitive load; simpler logic is easier to maintain | Low | `SIM` rule set; partially auto-fixable |
| Comprehension cleanup (`C4`) | Pythonic patterns; removes unnecessary `list()` / `dict()` wrapping | Low | `C4` rule set; auto-fixable |
| `ruff format --check` as verification | Confirm formatting stays consistent after manual edits | Low | Single command; could become pre-commit later |

## Anti-Features

Features to explicitly NOT build in this milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Type annotations | Massive scope expansion; changes function signatures; needs mypy too | Separate milestone if desired |
| Pre-commit hooks | Adds friction during a cleanup phase; better after code is clean | Add after cleanup is complete |
| CI enforcement | No CI exists; adding it is infrastructure work, not code quality | Separate milestone |
| Docstring enforcement (`D` rules) | Extremely noisy on existing undocumented code; low value for cleanup | Add if documentation milestone happens |
| Security scanning (`S` rules) | Out of scope; mixes concerns | Separate security review if needed |
| Test additions | No tests exist; writing tests is a separate effort | Separate milestone |
| Aggressive Pylint rules (`PL`) | High noise, overlaps with simpler rules, slows down cleanup | Use `B`/`SIM`/`RET` for the same effect with less noise |

## Feature Dependencies

```
Formatting (ruff format) --> Auto-fixes (ruff check --fix) --> Manual cleanup
                                                                    |
                                                    Long function decomposition
                                                    Naming improvements
                                                    Dead code removal
```

Formatting must happen first because it normalizes the codebase. Auto-fixes depend on stable formatting. Manual cleanup depends on both being done so diffs are clean and focused.

## MVP Recommendation

Prioritize:
1. Ruff configuration in pyproject.toml (enables everything else)
2. `ruff format` across all modules (instant consistency)
3. `ruff check --fix` for safe auto-fixes (removes obvious issues)
4. Manual cleanup of the highest-complexity modules first

Defer: Naming improvements should come last because they require understanding intent, not just structure.

## Sources

- [Ruff rule reference](https://docs.astral.sh/ruff/rules/) -- rule set capabilities and auto-fix availability
- PROJECT.md -- explicit scope and requirements

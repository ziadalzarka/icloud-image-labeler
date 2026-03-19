# Architecture Research

**Domain:** Python code quality enforcement for existing CLI codebase
**Researched:** 2026-03-19
**Confidence:** HIGH

## System Overview: Code Quality Pipeline

The code quality initiative operates as a pipeline with strict ordering. Each step builds on the previous one -- running them out of order creates unnecessary churn (e.g., reformatting code you are about to delete, or linting code that will be restructured).

```
┌─────────────────────────────────────────────────────────────────┐
│                   Code Quality Pipeline                          │
│                                                                  │
│  Step 1          Step 2          Step 3          Step 4          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐   │
│  │ FORMAT   │───>│ LINT     │───>│ DEAD     │───>│ REFACTOR │   │
│  │ (Ruff    │    │ (Ruff    │    │ CODE     │    │ (Break   │   │
│  │  format) │    │  check)  │    │ REMOVAL  │    │  up fns) │   │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘   │
│       │               │               │               │          │
│  Cosmetic only   Fix real bugs   Reduce surface   Improve        │
│  No behavior     No behavior     No behavior      readability    │
│  change          change          change           No behavior    │
│                                                   change         │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Order

1. **Format first** -- Establishes consistent style baseline. Every subsequent diff is about substance, not whitespace. Ruff format is fully deterministic and safe.
2. **Lint second** -- Catches real bugs, unused imports, bad patterns. Runs on already-formatted code so fixes don't fight formatting.
3. **Dead code removal third** -- Remove unused imports, functions, commented-out blocks. Do this before refactoring so you don't waste effort restructuring code that should be deleted.
4. **Refactor last** -- Break up long functions, improve naming. This is the highest-risk step (most likely to accidentally change behavior) and benefits from a clean, linted baseline.

## Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| Ruff Formatter | Deterministic code formatting (replaces Black + isort) | `ruff format .` |
| Ruff Linter | Static analysis, bug detection, style enforcement | `ruff check . --fix` |
| Dead Code Pass | Manual removal of unused code identified by linter | Human review of F401, F841 violations |
| Refactoring Pass | Structural improvements (function decomposition, naming) | Human-driven, module by module |

## Ruff Configuration in pyproject.toml

Ruff configuration belongs in `pyproject.toml` under `[tool.ruff]` sections. This is the standard location for Python tool config and avoids adding more dotfiles.

### Recommended Configuration

```toml
[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "F",     # pyflakes (unused imports, variables, etc.)
    "W",     # pycodestyle warnings
    "I",     # isort (import ordering)
    "B",     # flake8-bugbear (common bug patterns)
    "UP",    # pyupgrade (use modern Python syntax)
    "SIM",   # flake8-simplify (simplifiable constructs)
    "RUF",   # Ruff-specific rules
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # unused imports OK in __init__

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### Rule Categories Explained

| Rule Prefix | What It Catches | Why Include |
|-------------|-----------------|-------------|
| `E` / `W` | PEP 8 style violations | Baseline style conformance |
| `F` | Unused imports, undefined names, dead variables | The core of dead code detection |
| `I` | Import sorting | Consistent import blocks, replaces isort |
| `B` | Common bug patterns (mutable default args, etc.) | Catches real bugs, not just style |
| `UP` | Python 2/3.8/3.9 syntax that can use 3.10+ equivalents | Modernizes code for target version |
| `SIM` | Unnecessarily complex constructs | Simplifies code during cleanup |
| `RUF` | Ruff-specific rules (unnecessary parentheses, etc.) | Catches things other linters miss |

### What NOT to Enable Yet

- **`C90`** (McCabe complexity) -- Useful for flagging functions to refactor, but run it as a report, not a blocker. Long functions are known and will be addressed in the refactoring step.
- **`ANN`** (type annotations) -- Explicitly out of scope per PROJECT.md.
- **`D`** (docstrings) -- Adding docstrings is a separate concern from cleanup.
- **`ALL`** -- Avoid. Too noisy, enables rules that conflict with each other.

## Data Flow: Applying Quality Steps to Each Module

### Per-Module Processing Order

```
For each module in labeler/:
    ┌────────────────────────────┐
    │  ruff format <module>.py   │  Autofix: whitespace, quotes, imports
    └────────────┬───────────────┘
                 ↓
    ┌────────────────────────────┐
    │  ruff check <module>.py    │  Report: violations
    │  ruff check --fix          │  Autofix: safe fixes (unused imports, etc.)
    └────────────┬───────────────┘
                 ↓
    ┌────────────────────────────┐
    │  Manual: remove dead code  │  Delete unused functions, commented blocks
    └────────────┬───────────────┘
                 ↓
    ┌────────────────────────────┐
    │  Manual: refactor          │  Extract functions, rename, reorganize
    └────────────┬───────────────┘
                 ↓
    ┌────────────────────────────┐
    │  ruff format + check       │  Final pass to re-format refactored code
    └────────────────────────────┘
```

### Module Processing Priority

Process modules from least-coupled to most-coupled. This minimizes cascading diffs.

```
Independent (no intra-package dependents):
  shutdown.py (37 lines)  -- tiny, standalone
  checks.py   (33 lines)  -- tiny, standalone
  config.py   (66 lines)  -- small, standalone
  writer.py   (47 lines)  -- small, only imports are external
  daemon.py   (90 lines)  -- only depends on config

Mid-tier (imported by 1-2 modules):
  init.py      (89 lines)  -- depends on config
  discovery.py (65 lines)  -- depends on config
  metrics.py   (161 lines) -- imported by processor
  exporter.py  (164 lines) -- imported by processor
  llm.py       (123 lines) -- imported by processor

High-coupling (depends on many, depended on by CLI):
  processor.py (386 lines) -- imports exporter, llm, writer, metrics, shutdown
  cli.py       (240 lines) -- imports everything, defines arg parsing
```

## Architectural Patterns

### Pattern 1: Format-Then-Lint (Never Reverse)

**What:** Always run `ruff format` before `ruff check`. The formatter is designed to produce output that the linter accepts. Running them in reverse means lint fixes may not be formatted consistently.

**When to use:** Every time. This is the canonical order from Ruff's own documentation.

**Trade-offs:** None. This is strictly correct.

**Execution:**
```bash
ruff format labeler/
ruff check labeler/ --fix
```

### Pattern 2: Configuration-First Commit

**What:** Add the `[tool.ruff]` configuration to `pyproject.toml` as its own commit before any code changes. This establishes the rules and lets you run `ruff check .` to see the full scope of violations before fixing anything.

**When to use:** At the very start of the initiative.

**Trade-offs:** One extra commit, but gives a clean baseline and separates "defining rules" from "applying rules."

### Pattern 3: Bulk Format as Single Commit

**What:** Run `ruff format .` across the entire codebase and commit the result as one atomic commit. Do not mix formatting changes with any other changes.

**When to use:** Immediately after configuration. One big commit labeled clearly (e.g., "Apply Ruff formatting across all modules").

**Trade-offs:** Creates a large diff that touches every file, but `git blame` can be configured to ignore it (`git blame --ignore-rev`). The alternative (formatting per-module) creates many small commits that are harder to ignore in blame.

**Blame ignore setup:**
```bash
# After the formatting commit:
echo "<formatting-commit-hash>" >> .git-blame-ignore-revs
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

### Pattern 4: Module-by-Module Refactoring

**What:** After bulk formatting and linting, refactor one module at a time. Each module gets its own commit.

**When to use:** For the refactoring step (Step 4). Unlike formatting which is safe to do in bulk, refactoring carries risk and should be isolated.

**Trade-offs:** More commits, but each is reviewable and revertable independently.

## Existing Project Structure (No Changes Needed)

```
labeler/
├── __init__.py      # Package marker (empty)
├── __main__.py      # Entry point (3 lines)
├── checks.py        # Dependency checking (33 lines)
├── cli.py           # Argparse CLI, subcommand dispatch (240 lines)
├── config.py        # Config file management (66 lines)
├── daemon.py        # launchd lifecycle (90 lines)
├── discovery.py     # osxphotos query (65 lines)
├── exporter.py      # HEIC-to-JPEG, video frames (164 lines)
├── init.py          # Setup wizard (89 lines)
├── llm.py           # LLM client, response parsing (123 lines)
├── metrics.py       # SQLite metrics collection (161 lines)
├── processor.py     # Batch orchestration (386 lines) ← primary refactor target
├── shutdown.py      # Signal handling (37 lines)
└── writer.py        # PhotoScript metadata writes (47 lines)
```

The flat module structure is appropriate for a ~1500-line codebase. No sub-packages needed. The refactoring step is about function-level decomposition within modules, not restructuring the package.

### Key Refactoring Targets

| Module | Lines | Concern | Action |
|--------|-------|---------|--------|
| `processor.py` | 386 | `process_batch` is ~160 lines with nested loops and state | Extract photo processing loop, video processing loop, and refresh logic into separate functions |
| `cli.py` | 240 | `_run` has ~35 lines of config-override boilerplate | Extract config resolution into a helper |
| `exporter.py` | 164 | Moderate complexity, some long functions | Review for extraction opportunities |
| `metrics.py` | 161 | SQL string building | Minor cleanup |

## Anti-Patterns

### Anti-Pattern 1: Mixing Formatting with Refactoring in One Commit

**What people do:** Format code, fix lint errors, and refactor functions all in the same commit.
**Why it's wrong:** Impossible to review. If a behavior bug is introduced, you cannot isolate whether it came from formatting, linting, or refactoring. Git blame becomes useless.
**Do this instead:** Separate commits -- one for formatting, one for lint fixes, one per module refactored.

### Anti-Pattern 2: Enabling Too Many Lint Rules at Once

**What people do:** Set `select = ["ALL"]` or enable 15+ rule categories immediately.
**Why it's wrong:** Creates hundreds of violations, many conflicting. Overwhelms the cleanup effort and leads to ignoring real issues in a sea of style nitpicks.
**Do this instead:** Start with `E`, `F`, `W`, `I` (core rules). Add `B`, `UP`, `SIM` after the first pass is clean. Expand further only if needed.

### Anti-Pattern 3: Refactoring Before Removing Dead Code

**What people do:** Start breaking up a long function, then realize half the code paths are unused.
**Why it's wrong:** Wasted effort restructuring code that should be deleted.
**Do this instead:** Remove dead code first (F401 unused imports, F841 unused variables, commented-out blocks), then refactor what remains.

### Anti-Pattern 4: Formatting Per-File Instead of Bulk

**What people do:** Format one file at a time across multiple commits.
**Why it's wrong:** Creates many commits that clutter blame. Each commit is trivial on its own but collectively pollutes history.
**Do this instead:** One bulk `ruff format .` commit with a `.git-blame-ignore-revs` entry.

## Integration Points

### pyproject.toml as Single Source of Truth

| Tool | Configuration Section | Notes |
|------|----------------------|-------|
| Ruff Linter | `[tool.ruff.lint]` | Rule selection, per-file ignores |
| Ruff Formatter | `[tool.ruff.format]` | Quote style, indent style |
| Ruff General | `[tool.ruff]` | target-version, line-length |
| Setuptools | `[build-system]`, `[project]` | Already present, unchanged |

All Ruff config goes in `pyproject.toml`. No separate `ruff.toml` needed for a project this size.

### Ruff Format vs Ruff Check Interaction

| Scenario | Behavior |
|----------|----------|
| Run format then check | Correct. Formatter output satisfies all formatting-related lint rules. |
| Run check then format | Incorrect. Lint autofix may produce unformatted code. |
| Run check --fix | Safe autofixes only. Won't break code. But run format afterward. |
| Conflicting rules | Ruff disables conflicting lint rules automatically when formatter is active. |

### Internal Module Boundaries (Unchanged by Cleanup)

| Boundary | Communication | Cleanup Impact |
|----------|---------------|----------------|
| cli.py -> processor.py | Direct function call | Config resolution may be extracted |
| processor.py -> exporter.py | Direct function call | No interface change |
| processor.py -> llm.py | Direct function call | No interface change |
| processor.py -> writer.py | Direct function call | No interface change |
| processor.py -> metrics.py | Direct function call | No interface change |
| cli.py -> config.py | Direct function call | No interface change |

The cleanup initiative does not change any module interfaces. All refactoring is internal to each module.

## Build Order Summary

This is the dependency chain for the code quality initiative:

```
1. Add Ruff config to pyproject.toml          (no code changes)
         ↓
2. ruff format . (bulk format)                (cosmetic only, one commit)
         ↓
3. ruff check --fix (auto-fixable lint)       (safe fixes, one commit)
         ↓
4. Manual lint fixes for remaining violations  (one commit)
         ↓
5. Dead code removal across all modules        (one commit)
         ↓
6. Refactor processor.py                       (own commit -- highest risk)
         ↓
7. Refactor cli.py                             (own commit)
         ↓
8. Refactor remaining modules as needed        (own commit per module)
         ↓
9. Final ruff format + check pass              (verify clean state)
```

Steps 1-5 are mechanical and low-risk. Steps 6-8 are judgment-based and higher-risk. Each step depends on the previous one being complete.

## Sources

- [Ruff Configuration Documentation](https://docs.astral.sh/ruff/configuration/)
- [Ruff Formatter Documentation](https://docs.astral.sh/ruff/formatter/)
- [Ruff Linter Documentation](https://docs.astral.sh/ruff/linter/)
- [Ruff Settings Reference](https://docs.astral.sh/ruff/settings/)
- [Python Code Quality - TestDriven.io](https://testdriven.io/blog/python-code-quality/)
- [Real Python - Python Code Quality](https://realpython.com/python-code-quality/)

---
*Architecture research for: Python code quality enforcement*
*Researched: 2026-03-19*

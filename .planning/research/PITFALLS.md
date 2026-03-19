# Domain Pitfalls

**Domain:** Python code quality enforcement on existing codebase
**Researched:** 2026-03-19

## Critical Pitfalls

Mistakes that cause wasted work or broken functionality.

### Pitfall 1: Mixing formatting and logic changes in the same commit
**What goes wrong:** A single commit contains both `ruff format` changes and manual refactoring. The diff becomes unreadable. If the refactoring introduces a bug, it is nearly impossible to isolate which change caused it.
**Why it happens:** Developers run the formatter and start cleaning up code in the same session.
**Consequences:** Unreviewable diffs. If something breaks, `git bisect` points to a massive commit. Rollback reverts both formatting and logic changes.
**Prevention:** Commit formatting changes separately from logic changes. First commit: `ruff format` only. Second commit: auto-fixes. Third+ commits: manual refactoring per module.
**Detection:** Any commit that touches both whitespace/formatting AND function signatures/logic flow.

### Pitfall 2: Auto-fix introduces subtle behavior change
**What goes wrong:** `ruff check --fix` applies a transformation that is syntactically safe but semantically different in an edge case. Example: `SIM` rules can change short-circuit evaluation order. `UP` rules can change exception handling syntax.
**Why it happens:** Auto-fix rules are tested against common patterns, not every possible edge case in every codebase.
**Consequences:** Silent behavior change that passes linting but breaks runtime behavior.
**Prevention:** Run auto-fixes module-by-module, not on the entire codebase at once. Review the diff before committing. Test core functionality after each module is fixed.
**Detection:** Run the tool after each auto-fix pass to verify the application still works (process a photo, run the CLI).

### Pitfall 3: Refactoring breaks the "no behavior changes" constraint
**What goes wrong:** While breaking up a long function, a variable scope changes, an early return path is lost, or an exception handler no longer catches the right scope.
**Why it happens:** Extract-function refactoring is inherently risky without tests. The project has no test suite.
**Consequences:** Runtime errors or silent behavior changes in production.
**Prevention:** For each function extraction: (1) identify all variables used, (2) verify return paths are preserved, (3) manually test the affected code path. Keep refactoring commits small and focused on one function at a time.
**Detection:** Manual testing after each refactoring step.

## Moderate Pitfalls

### Pitfall 4: Enabling too many rule sets at once
**What goes wrong:** Enabling all available Ruff rules produces hundreds or thousands of violations. The developer becomes overwhelmed, starts ignoring warnings, or adds broad `noqa` comments everywhere.
**Prevention:** Start with the recommended 12 rule sets. Add more only when the current set is clean. Never add a rule set unless you plan to fix all its violations.

### Pitfall 5: Fighting the formatter
**What goes wrong:** Manually formatting code that Ruff will reformat anyway. Or adding `# fmt: off` comments to preserve manual formatting that looks "better."
**Prevention:** Accept the formatter's decisions. Consistency matters more than aesthetic preferences. Only use `# fmt: off` for genuinely unformattable constructs (like alignment tables in data).

### Pitfall 6: Removing "dead code" that is actually used dynamically
**What goes wrong:** A function or import appears unused but is actually called via `getattr()`, string-based dispatch, or AppleScript bridge patterns.
**Why it happens:** Static analysis cannot trace dynamic invocation.
**Prevention:** Before removing any function flagged as unused, grep for its name as a string literal. Be especially careful with `writer.py` (PhotoScript/AppleScript bridge) and `cli.py` (argparse dispatch).

### Pitfall 7: isort breaks star imports or conditional imports
**What goes wrong:** Ruff's isort rules reorganize imports, moving a conditional import or `from x import *` into a position where it no longer works.
**Prevention:** The `known-first-party = ["labeler"]` setting prevents most issues. If conditional imports exist (e.g., `try: import osxphotos`), add per-line `# noqa: I` comments.

## Minor Pitfalls

### Pitfall 8: pyupgrade changes that are correct but unfamiliar
**What goes wrong:** `UP` rules modernize syntax (e.g., `dict()` to `{}`, `Optional[X]` to `X | None`). The code is correct but looks unfamiliar to the developer.
**Prevention:** Accept the modernization. The project targets 3.10+; modern syntax is correct.

### Pitfall 9: Formatter conflicts with string formatting in LLM prompts
**What goes wrong:** Ruff reformats long string literals (like LLM prompts in `llm.py`) in ways that change whitespace within the string.
**Prevention:** Ruff's formatter preserves string content. But verify that multiline f-strings or template strings in `llm.py` are not affected by line-break changes.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Initial formatting | Giant diff obscures actual state of code | Commit formatting as a single standalone commit with message "Apply ruff format" |
| Auto-fixes | SIM/UP rules may change behavior subtly | Review diffs per-module; test CLI after each |
| Function decomposition | Scope/variable bugs from extraction | One function at a time; verify all variable references |
| Dead code removal | Dynamic dispatch patterns hide usage | Grep for function names as strings before removing |
| Import cleanup | Conditional imports may break | Check for try/except import patterns before running isort fixes |

## Sources

- Community patterns from Python refactoring discussions
- Ruff documentation on [auto-fix safety](https://docs.astral.sh/ruff/linter/#fix-safety)
- PROJECT.md constraint: "No behavior changes"

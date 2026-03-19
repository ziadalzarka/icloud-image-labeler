# Architecture Patterns

**Domain:** Python code quality tooling integration
**Researched:** 2026-03-19

## Recommended Architecture

No architectural changes to the application. The code quality tooling is purely additive configuration.

### Configuration Location

All Ruff configuration lives in the existing `pyproject.toml` file under `[tool.ruff]` sections. No new files needed.

```
pyproject.toml          <-- Add [tool.ruff], [tool.ruff.lint], [tool.ruff.format] sections
labeler/                <-- All modules get formatted/linted in place
  __init__.py
  cli.py
  config.py
  daemon.py
  discovery.py
  exporter.py
  llm.py
  processor.py
  writer.py
  metrics.py
  init.py
```

### Per-File Overrides

Ruff supports per-file rule overrides for modules that need different treatment:

```toml
[tool.ruff.lint.per-file-ignores]
"labeler/cli.py" = ["ARG"]      # CLI dispatch functions may have unused args
"labeler/daemon.py" = ["B"]     # System-level code may need bare excepts
```

Use sparingly. Prefer fixing the code over suppressing rules.

## Patterns to Follow

### Pattern 1: Format-First Workflow
**What:** Always run `ruff format` before `ruff check`. The formatter normalizes whitespace and line breaks, giving the linter stable input.
**When:** Every time you touch code.
**Example:**
```bash
ruff format labeler/
ruff check --fix labeler/
ruff check labeler/  # Verify nothing remains
```

### Pattern 2: Module-by-Module Refactoring
**What:** Clean up one module at a time, not the whole codebase. Each module gets its own commit(s).
**When:** During the manual cleanup phase.
**Why:** Keeps diffs reviewable. If something breaks, the blast radius is one module.

### Pattern 3: Extract-and-Name
**What:** When breaking up long functions, extract a block into a new function with a descriptive name. The name should describe WHAT, not HOW.
**When:** Functions longer than ~40 lines or with multiple levels of nesting.
**Example:**
```python
# Before
def process_batch(items):
    # 20 lines of filtering logic
    # 30 lines of processing logic
    # 15 lines of error handling

# After
def process_batch(items):
    valid_items = _filter_processable(items)
    results = _process_items(valid_items)
    _handle_failures(results)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Suppressing Rules Globally Instead of Fixing
**What:** Adding rules to the `ignore` list because they produce too many violations.
**Why bad:** Hides real issues. The rule was enabled for a reason.
**Instead:** Fix the violations. If a rule is genuinely wrong for this project, document WHY in a comment next to the ignore entry.

### Anti-Pattern 2: Inline noqa Comments Everywhere
**What:** Adding `# noqa: XXX` to individual lines instead of fixing the issue.
**Why bad:** Creates maintenance burden. Each noqa is technical debt.
**Instead:** Fix the code. Use noqa only for genuine false positives (less than 5 total in a clean codebase).

### Anti-Pattern 3: Reformatting and Refactoring in One Commit
**What:** A single commit that both reformats and changes logic.
**Why bad:** Impossible to review. Impossible to bisect. Impossible to revert partially.
**Instead:** Separate commits: one for formatting, one for logic changes.

## Scalability Considerations

Not applicable. This is a ~10-module CLI tool. Ruff processes the entire codebase in under 100ms. No scalability concerns exist.

## Sources

- [Ruff configuration docs](https://docs.astral.sh/ruff/configuration/) -- per-file overrides, pyproject.toml structure
- [Ruff formatter docs](https://docs.astral.sh/ruff/formatter/) -- format-first workflow

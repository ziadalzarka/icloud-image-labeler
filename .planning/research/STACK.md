# Stack Research

**Domain:** Python code quality (linting, formatting, refactoring) for existing CLI tool
**Researched:** 2026-03-19
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Ruff | 0.15.6 | Linting + formatting | Replaces Black, isort, Flake8, pyupgrade, autoflake in one tool. 100-200x faster than Flake8. Adopted by FastAPI, pandas, pydantic, Apache Airflow. The uncontested standard for Python code quality in 2025-2026. |

No other core technologies needed. Ruff is the entire stack for this scope.

### Supporting Libraries

None required. The PROJECT.md explicitly excludes type checking (mypy), CI/pre-commit hooks, and test tooling from scope. Ruff is self-contained with zero Python dependencies.

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Ruff VS Code extension (`charliermarsh.ruff`) | Real-time lint + format-on-save | Replaces the old Python/Pylint/Black extensions for linting and formatting |
| `ruff check --fix` | Auto-fix safe lint violations | Many rules have automatic fixes; run before manual cleanup |
| `ruff format` | Format all files | Drop-in Black replacement; near-identical output |

## Recommended Ruff Configuration

Add this to the existing `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = [
    "F",     # Pyflakes — undefined names, unused imports, redefined variables
    "E",     # pycodestyle errors — whitespace, indentation, syntax issues
    "W",     # pycodestyle warnings — trailing whitespace, blank lines
    "I",     # isort — import sorting and grouping
    "UP",    # pyupgrade — modernize syntax for Python 3.10+ (dict unions, type hints, etc.)
    "B",     # flake8-bugbear — common bugs and design problems (mutable defaults, etc.)
    "SIM",   # flake8-simplify — simplifiable if/else, context managers, boolean logic
    "C4",    # flake8-comprehensions — unnecessary list/dict/set calls that should be comprehensions
    "RET",   # flake8-return — unnecessary return statements, implicit returns
    "PIE",   # flake8-pie — misc lint (unnecessary pass, dict.setdefault, etc.)
    "ERA",   # eradicate — detect commented-out code (PROJECT.md specifically calls this out)
    "ARG",   # flake8-unused-arguments — unused function/method arguments
    "RUF",   # Ruff-specific — parenthesized context managers, ambiguous characters, etc.
]
ignore = [
    "E501",   # line length — let the formatter handle this, not the linter
    "RET504", # unnecessary assignment before return — sometimes improves readability
    "ARG001", # unused function argument — too noisy for callback-heavy code
]

[tool.ruff.lint.isort]
known-first-party = ["labeler"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true
```

### Rule Set Rationale

**Included and why:**

| Rule Set | Code | Why This Project Needs It |
|----------|------|--------------------------|
| Pyflakes | `F` | Catches undefined names, unused imports. Bread and butter. |
| pycodestyle | `E`, `W` | Basic style consistency. Non-negotiable baseline. |
| isort | `I` | Import ordering. The project has no import convention currently. |
| pyupgrade | `UP` | Project targets 3.10+. Auto-modernize old syntax patterns. |
| Bugbear | `B` | Catches real bugs (mutable default args, bare except). High signal. |
| Simplify | `SIM` | Directly supports the "break up complex code" goal from PROJECT.md. |
| Comprehensions | `C4` | Clean up unnecessary list()/dict() wrapping. Quick wins. |
| Return | `RET` | Simplify return patterns during function restructuring. |
| PIE | `PIE` | Catch unnecessary `pass`, redundant `dict.setdefault`. Low noise. |
| Eradicate | `ERA` | PROJECT.md explicitly wants "commented-out blocks" removed. |
| Unused args | `ARG` | Find dead parameters during function cleanup. |
| Ruff-specific | `RUF` | Catches things other tools miss. Low noise, high value. |

**Explicitly NOT included and why:**

| Rule Set | Code | Why Excluded |
|----------|------|-------------|
| flake8-annotations | `ANN` | Type annotations are out of scope per PROJECT.md |
| pydocstyle | `D` | Docstring enforcement not in scope; would be noisy on existing code |
| flake8-bandit | `S` | Security scanning is out of scope for a formatting/cleanup milestone |
| flake8-print | `T20` | CLI tool legitimately uses print statements |
| Pylint | `PL` | Overlaps heavily with F/E/B/SIM. Adds noise without value for this scope. |
| pep8-naming | `N` | Naming cleanup is a manual task per PROJECT.md; automated rules are too rigid |
| flake8-type-checking | `TC` | No type annotations in scope |
| mccabe | `C90` | Complexity measurement is informational only; not actionable for formatter |
| flake8-pytest-style | `PT` | No tests in scope |
| tryceratops | `TRY` | Exception handling patterns are opinionated; low value for cleanup |
| flake8-boolean-trap | `FBT` | Too noisy for existing code; would require API changes |
| flake8-errmsg | `EM` | Stylistic preference, not a quality issue |

### Configuration Decisions Explained

**`line-length = 88`**: Black's default, which Ruff's formatter matches. No reason to deviate. This is the community standard.

**`target-version = "py310"`**: Matches `requires-python = ">=3.10"` in pyproject.toml. Enables pyupgrade rules to modernize to 3.10 syntax (structural pattern matching type unions with `X | Y`, etc.).

**`E501` ignored**: The formatter handles line length. Having the linter also flag it creates duplicate noise and fights with the formatter on multi-line expressions.

**`quote-style = "double"`**: Black default. Most Python projects use double quotes.

**`docstring-code-format = true`**: Formats code blocks inside docstrings. Free consistency.

## Installation

```bash
# Install as dev dependency
pip install ruff

# Or add to pyproject.toml dev dependencies
# [project.optional-dependencies]
# dev = ["ruff>=0.15"]
```

No other packages needed. Ruff is a single binary with no Python dependencies.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Ruff (lint) | Flake8 + plugins | Never for new projects. Flake8 ecosystem is fragmented and 100x slower. Only reason: need a niche Flake8 plugin with no Ruff equivalent. |
| Ruff (format) | Black | Never. Ruff's formatter produces near-identical output and is 30x faster. Black is in maintenance mode. |
| Ruff (imports) | isort | Never. Ruff's isort implementation is a superset. |
| Ruff (upgrade) | pyupgrade | Never. Ruff's UP rules are a superset of pyupgrade. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Black | Redundant. Ruff's formatter is a drop-in replacement, faster, and maintained by the same ecosystem (Astral). | `ruff format` |
| Flake8 | Ruff implements every Flake8 rule plus hundreds more. Flake8 plugin ecosystem is fragmenting as maintainers migrate to Ruff. | `ruff check` |
| isort | Ruff's `I` rules are a complete isort replacement with identical behavior. | `ruff check --select I --fix` |
| Pylint | Slow (AST-based, pure Python). Ruff covers 209+ of Pylint's ~409 rules. The unique Pylint rules are mostly deep analysis that's out of scope for this cleanup. | `ruff check` with `B`, `SIM`, `RET` rules |
| autopep8 | Unmaintained. Ruff's formatter + linter cover everything autopep8 did. | `ruff format` + `ruff check --fix` |
| pyupgrade | Ruff's `UP` rules are a superset. No reason to run a separate tool. | `ruff check --select UP --fix` |
| autoflake | Ruff handles unused import removal (`F401`) and unused variable detection (`F841`) natively. | `ruff check --select F --fix` |
| pre-commit (for now) | Out of scope per PROJECT.md. Can add later as a separate milestone. | Run `ruff check` and `ruff format` manually or via editor |

## Workflow Pattern

```bash
# Step 1: Format all files
ruff format labeler/

# Step 2: Fix auto-fixable lint issues
ruff check --fix labeler/

# Step 3: Review remaining manual fixes
ruff check labeler/

# Step 4: Check everything is clean
ruff check labeler/ && ruff format --check labeler/
```

**Important**: Run `ruff format` BEFORE `ruff check --fix`. The formatter may change line breaks that affect how the linter sees the code. Formatting first gives the linter stable input.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| Ruff 0.15.x | Python 3.10+ | Matches project's `requires-python` |
| Ruff 0.15.x | pyproject.toml config | All config lives in `[tool.ruff]` sections |
| Ruff formatter | Black output | Near-identical output; safe migration from Black |

## Sources

- [Ruff official documentation](https://docs.astral.sh/ruff/) -- configuration, rule reference
- [Ruff v0.15.0 blog post](https://astral.sh/blog/ruff-v0.15.0) -- 2026 style guide changes
- [Ruff GitHub releases](https://github.com/astral-sh/ruff/releases) -- version 0.15.6 confirmed via local install
- [Ruff configuration docs](https://docs.astral.sh/ruff/configuration/) -- pyproject.toml structure
- [Ruff settings reference](https://docs.astral.sh/ruff/settings/) -- all available settings
- Local `ruff version` and `ruff linter` output -- confirmed 0.15.6 and available rule sets

---
*Stack research for: Python code quality tooling*
*Researched: 2026-03-19*

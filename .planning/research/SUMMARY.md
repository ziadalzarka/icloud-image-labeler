# Research Summary: iCloud Image Labeler Code Quality

**Domain:** Python code quality enforcement for existing CLI tool
**Researched:** 2026-03-19
**Overall confidence:** HIGH

## Executive Summary

The Python code quality landscape has consolidated around a single tool: Ruff. Written in Rust by Astral (the same company behind `uv`), Ruff replaces Black, isort, Flake8, pyupgrade, autoflake, and dozens of Flake8 plugins in a single binary that runs 100-200x faster than the tools it replaces. Major projects (FastAPI, pandas, pydantic, Apache Airflow) have already migrated. There is no credible alternative for new projects in 2026.

For this project specifically, the scope is well-defined: add Ruff linting and formatting, then use those rules as guardrails while manually cleaning up code structure (long functions, poor naming, dead code). The tooling is mature and the configuration is straightforward -- the real work is in the manual refactoring, not the tool setup.

The project has 10 modules in `labeler/` targeting Python 3.10+. The recommended Ruff configuration enables 12 rule sets chosen specifically for cleanup tasks: catching unused code, simplifying logic, modernizing syntax, and enforcing consistent formatting. Rule sets for type checking, security, and testing are excluded per the project's explicit scope.

## Key Findings

**Stack:** Ruff 0.15.6 is the only tool needed -- linting, formatting, import sorting, and code modernization in one binary.

**Architecture:** No architectural changes needed. Configuration lives entirely in `pyproject.toml` alongside existing project config.

**Critical pitfall:** Running `ruff check --fix` on the entire codebase at once risks introducing subtle behavior changes. The `--fix` flag auto-applies safe fixes, but "safe" means syntactically equivalent, not necessarily semantically identical in edge cases. Apply fixes module-by-module and verify.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **Tool Setup** - Add Ruff configuration to pyproject.toml, run formatter on all files
   - Addresses: Consistent formatting across all modules
   - Avoids: Mixing formatting changes with logic changes in the same commits

2. **Automated Fixes** - Run `ruff check --fix` to auto-fix safe lint violations
   - Addresses: Unused imports, syntax modernization, import sorting
   - Avoids: Manual work on things the tool can handle automatically

3. **Manual Cleanup** - Break up long functions, improve naming, remove dead code
   - Addresses: The structural issues that tools cannot fix
   - Avoids: Premature refactoring before the codebase is consistently formatted

**Phase ordering rationale:**
- Formatting must come first because it creates clean diffs for subsequent changes
- Auto-fixes second because they reduce noise before manual review
- Manual cleanup last because it requires human judgment and benefits from a clean baseline

**Research flags for phases:**
- Phase 1: No research needed -- standard Ruff setup
- Phase 2: No research needed -- just running auto-fixes
- Phase 3: May benefit from reviewing module-specific complexity (which functions to split, etc.)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Ruff 0.15.6 confirmed via local install; version and capabilities verified |
| Features | HIGH | Rule sets verified against `ruff linter` output on local machine |
| Architecture | HIGH | Configuration is a pyproject.toml addition; no structural changes |
| Pitfalls | MEDIUM | Based on community patterns; no project-specific issues discovered yet |

## Gaps to Address

- Specific functions/modules that need manual refactoring (needs codebase analysis, not ecosystem research)
- Whether any existing code patterns conflict with selected rule sets (will surface when Ruff first runs)
- Editor integration preferences (VS Code extension exists but setup is per-developer)

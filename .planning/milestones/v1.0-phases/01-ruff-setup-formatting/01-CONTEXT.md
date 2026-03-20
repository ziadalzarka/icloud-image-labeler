# Phase 1: Ruff Setup & Formatting - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Configure Ruff in pyproject.toml and format all modules consistently. This phase delivers: Ruff configuration with all rule sets, consistent formatting across all 12 Python modules, and sorted imports. No lint enforcement beyond isort — lint fixes come in Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Formatting style
- Line length: 88 (Black default, industry standard)
- Quote style: double quotes (Ruff default, matches existing codebase)
- Trailing commas and indentation: Ruff defaults (no customization needed)

### Rule set scope
- Configure ALL 13 rule sets in Phase 1 pyproject.toml: F, E, W, I, UP, B, SIM, C4, RET, PIE, ERA, ARG, RUF
- Ignore E501 (line too long) — formatter handles line wrapping, linter E501 creates conflicts
- Phase 1 only *enforces* formatting + isort; lint rules are configured but not enforced until Phase 2
- `known-first-party = ["labeler"]` for correct import grouping

### Commit strategy
- Three separate commits in order:
  1. `chore: add Ruff configuration` — pyproject.toml changes only
  2. `style: format all modules with Ruff` — bulk format of all 12 .py files
  3. `style: sort imports with Ruff isort` — `ruff check --fix --select I`
- No `.git-blame-ignore-revs` file (single-developer project, not worth the overhead)

### Per-file overrides
- No per-file ignores configured in Phase 1
- Discover actual overrides needed in Phase 2 when lint rules are enforced
- Known edge cases to watch for in Phase 2: `pillow_heif.register_heif_opener()` (side-effect import), conditional `osxphotos` import in cli.py

### Claude's Discretion
- Ruff version pinning strategy (dev dependency or not)
- Exact `target-version` setting (py310 per project constraint)
- Any formatter options not discussed (magic trailing comma, etc.)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope
- `.planning/PROJECT.md` — Project definition, constraints (no behavior changes, Python 3.10+)
- `.planning/REQUIREMENTS.md` — TOOL-01, TOOL-02, TOOL-05 are this phase's requirements

### Research findings
- `.planning/research/ARCHITECTURE.md` — Format-first workflow, per-file override patterns, anti-patterns to avoid
- `.planning/research/FEATURES.md` — Rule set rationale, feature dependencies, MVP recommendation

### Existing config
- `pyproject.toml` — Where Ruff config will be added (existing build-system and project metadata)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pyproject.toml` already exists with build-system and project metadata — Ruff config adds `[tool.ruff]` sections alongside existing config

### Established Patterns
- 12 Python modules in `labeler/` package (0-386 lines each, 1504 total)
- Existing code uses double quotes predominantly — aligns with chosen quote style
- No existing linter or formatter configuration — clean slate

### Integration Points
- `pyproject.toml` is the only file modified for configuration
- All 12 `.py` files in `labeler/` will be reformatted in place
- No build/CI pipeline to update — purely local tooling

</code_context>

<specifics>
## Specific Ideas

No specific requirements — standard Ruff setup following research recommendations.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-ruff-setup-formatting*
*Context gathered: 2026-03-19*

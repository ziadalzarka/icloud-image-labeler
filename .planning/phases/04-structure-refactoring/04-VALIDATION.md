---
phase: 4
slug: structure-refactoring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | None (no test infrastructure — ruff lint only) |
| **Config file** | pyproject.toml (ruff config) |
| **Quick run command** | `ruff check labeler/ && ruff format --check labeler/` |
| **Full suite command** | `ruff check labeler/ && python -c "from labeler import cli, processor, exporter"` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `ruff check labeler/ && ruff format --check labeler/`
- **After every plan wave:** Run `ruff check labeler/ && python -c "from labeler import cli, processor, exporter"`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | STRC-01 | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/processor.py` | N/A (ruff rule) | ⬜ pending |
| 04-01-02 | 01 | 1 | STRC-02 | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/cli.py` | N/A (ruff rule) | ⬜ pending |
| 04-01-03 | 01 | 1 | STRC-03 | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/exporter.py` | N/A (ruff rule) | ⬜ pending |
| 04-01-04 | 01 | 1 | STRC-04 | lint | `ruff check --select C901,PLR0912,PLR0915 labeler/` | N/A (ruff rule) | ⬜ pending |
| 04-01-05 | 01 | 1 | STRC-05 | manual | Visual inspection of indentation levels | N/A | ⬜ pending |
| 04-01-06 | 01 | 1 | STRC-06 | manual | Visual inspection + grep for bare literals | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.* Ruff is already configured and operational. No test framework to set up.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Deep nesting eliminated | STRC-05 | Nesting depth is not directly measurable by a single ruff rule | Visually inspect target functions; no indentation block should exceed 3 levels |
| Magic literals extracted | STRC-06 | No automated rule catches all magic values | Grep for bare numeric/string literals in target modules; confirm module-level constants exist |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

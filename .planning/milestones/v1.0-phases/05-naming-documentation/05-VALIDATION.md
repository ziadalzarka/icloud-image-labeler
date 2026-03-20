---
phase: 05
slug: naming-documentation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | ruff (linter-based verification) |
| **Config file** | pyproject.toml |
| **Quick run command** | `ruff check labeler/` |
| **Full suite command** | `ruff check labeler/ && python -m labeler --help` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `ruff check labeler/`
- **After every plan wave:** Run `ruff check labeler/ && python -m labeler --help`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | NAME-01, NAME-02, NAME-03 | lint+grep | `ruff check labeler/ && grep -r 'for [a-z] in' labeler/ --include='*.py'` | ✅ | ⬜ pending |
| 05-01-02 | 01 | 1 | DOCS-01, DOCS-02 | lint+grep | `ruff check --select D100,D103 labeler/` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements. Ruff D100/D103 rules will be enabled as part of the work itself.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Function names are clear verb-phrases | NAME-01 | Semantic clarity requires human judgment | Review renamed functions for clarity |

*Most verifications are automated via ruff and grep.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---
phase: 2
slug: automated-lint-fixes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | ruff CLI (lint checker) |
| **Config file** | pyproject.toml |
| **Quick run command** | `ruff check . --select {rule}` |
| **Full suite command** | `ruff check . && python -m labeler --help` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `ruff check . --select {changed_rules}`
- **After every plan wave:** Run `ruff check . && python -m labeler --help`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | TOOL-03 | lint | `ruff check . --select PTH` | ✅ | ⬜ pending |
| 02-01-02 | 01 | 1 | TOOL-06, DEAD-01 | lint | `ruff check . --select PLR && ruff check . --select F401` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements — ruff is already configured from Phase 1.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CLI behavior unchanged | All | Cannot lint-check runtime behavior | Run `python -m labeler --help` and verify subcommands present |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

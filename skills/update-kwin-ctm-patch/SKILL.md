---
name: update-kwin-ctm-patch
description: Repair and validate the kwin-ctm-monitor downstream patch when a new KDE Plasma KWin or KDE neon packaging release causes patch, compile, or focused test failures. Use for source drift, rejected hunks, renamed color-pipeline APIs, output configuration changes, D-Bus changes, or neon package restructuring.
---

# Update the KWin CTM patch

Preserve behavior before adapting syntax. Read `references/invariants.md` first.

## Workflow

1. Read `kwin-ctm-monitor status` and the monitor journal.
2. Identify the exact neon candidate with `apt-cache madison kwin-wayland`.
3. Clone the matching KWin tag and neon `Neon/release` packaging into temporary worktrees.
4. Run `scripts/check_patch.py PATCH SOURCE` to identify strict patch drift.
5. Inspect upstream changes around rejected hunks; never enable fuzz.
6. Adapt a temporary source tree while preserving every invariant.
7. Regenerate a clean patch relative to the untouched upstream tag. Never commit KWin source or binaries.
8. Run focused KWin tests and monitor package tests.
9. Stage a monitor build without publishing it to the active repository.
10. Report versions, semantic changes, diff scope, and test results.

## Guardrails

- Do not install packages, alter APT pins, publish changes, or replace the active repository without explicit authorization.
- Do not touch `~/AMD_Saturate`.
- Do not move the matrix into linear light or enable it for HDR.
- Do not add a software fallback under exact hardware mode.
- Preserve compositor-owned rollback for unconfirmed changes.

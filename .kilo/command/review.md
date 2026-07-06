---
description: Run read-only safety review on current uncommitted changes
agent: code
subtask: true
---
Review the current uncommitted changes. First run `git status` and `git diff` to see the change
surface (include untracked files via `git status --porcelain`).

Then invoke the reviewer via the Task tool:
1. @reviewer-safety — secrets/keyring handling, tool-gate enforcement, sandbox isolation, path traversal, injection, data exposure.

Consolidate the findings into a single report with these sections:
- **BLOCKERS** (must fix before commit)
- **WARNINGS** (should fix)
- **NITS** (optional)

Do NOT edit any files. This is read-only review. Present the consolidated report to the user.

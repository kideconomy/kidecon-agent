---
description: Run read-only safety review on current uncommitted changes
agent: code
subtask: true
---
Review the current uncommitted changes. First run `git status` and `git diff` to see the change
surface (include untracked files via `git status --porcelain`).

Then invoke the reviewer via the Task tool:
1. @reviewer-safety — secrets/keyring handling, tool-gate enforcement, sandbox isolation, path traversal, injection, data exposure.

Also scan the change surface for secrets-on-disk (any match is a BLOCKER — credentials belong in the keyring, never in files):

```bash
changed=$( { git diff --name-only --diff-filter=ACMRTUXB HEAD; git ls-files --others --exclude-standard; } | sort -u )
grep -nEi "jwt|api[_-]?key|secret|token|password" $changed | grep -viE "def |import |#|\.example|keyring|get_password|set_password|delete_password" || true
```

Consolidate the findings into a single report with these sections:
- **BLOCKERS** (must fix before commit)
- **WARNINGS** (should fix)
- **NITS** (optional)

Do NOT edit any files. This is read-only review. Present the consolidated report to the user.

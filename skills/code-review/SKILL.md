---
name: code-review
description: Review a diff or file for bugs, risks, and clarity before changes are committed.
---

# Code review

Review the requested code and report findings ordered by severity. Do not
rewrite the code unless asked.

## Process

1. Read every file under review in full before judging any of it.
2. Understand what the change is supposed to do; if a test exists, read it.
3. Hunt in this order:
   - **Correctness** — logic errors, off-by-ones, unhandled error paths,
     broken edge cases (empty input, huge input, non-UTF-8, missing files).
   - **State** — anything persisted, cached, or shared: can a crash or
     interrupt leave it inconsistent?
   - **Security** — injection into shells or queries, paths escaping the
     workspace, secrets in code or logs.
   - **Clarity** — misleading names, dead code, duplicated knowledge.
4. For each finding, give: file and line, one-sentence issue, a concrete fix.
5. End with a verdict: safe to commit, or blockers first.

## Rules

- Report only findings you can defend from the code you actually read;
  say "I did not review X" for anything skipped.
- Severity order: correctness > state > security > clarity.
- If the code is fine, say so plainly — do not invent nitpicks.

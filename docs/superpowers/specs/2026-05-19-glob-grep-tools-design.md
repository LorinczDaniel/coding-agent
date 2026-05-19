# Glob and Grep Tools — Design Spec

**Date:** 2026-05-19
**Status:** Approved

## Overview

Add two new tools to the agent — `Glob` (file pattern matching) and `Grep` (content search) — so the model can navigate and search codebases without resorting to shell one-liners via Bash. Both are Python-native implementations using `pathlib` and `re`.

## Architecture

Both tools follow the existing pattern in `app/tools.py`: a Python function implementation paired with an OpenAI-compatible schema dict. `app/agent.py` registers the new schema dicts in the `tools` list passed to the API.

Output is capped to prevent flooding the model's context window on large repos.

## Components

### `Glob(pattern, path=".")` — `app/tools.py`

Finds files matching a glob pattern under a given directory.

- Uses `pathlib.Path(path).rglob(pattern)` for patterns containing `**`, otherwise `Path(path).glob(pattern)`
- Skips `.git/` and `.venv/` directory trees
- Returns newline-separated relative file paths, sorted alphabetically
- Caps at 50 results; if over the limit appends a final line: `(showing 50 of N results)`
- On error (bad path, permission) returns an error string

**Schema:** `GLOB_TOOL`
```
name: Glob
description: Find files matching a glob pattern. Use ** for recursive search (e.g. **/*.py).
parameters:
  pattern: string (required) — glob pattern, e.g. "**/*.py" or "src/*.ts"
  path: string (optional, default ".") — directory to search in
```

### `Grep(pattern, path=".", include="*")` — `app/tools.py`

Searches file contents for lines matching a regex pattern.

- Walks all files under `path` whose filename matches the `include` glob
- Skips `.git/` and `.venv/` directory trees
- Searches each file line-by-line using `re.search(pattern)`
- Returns `filepath:lineno: line` per match, one per line
- Caps at 100 matches; if over the limit appends: `(showing 100 of N matches)`
- Skips binary files (catches `UnicodeDecodeError` silently)
- On error (bad path, bad regex) returns an error string

**Schema:** `GREP_TOOL`
```
name: Grep
description: Search file contents for lines matching a regex pattern.
parameters:
  pattern: string (required) — regex pattern to search for
  path: string (optional, default ".") — directory or file to search in
  include: string (optional, default "*") — filename glob filter, e.g. "*.py"
```

### `app/agent.py` — register new tools

Add `GLOB_TOOL` and `GREP_TOOL` to the imports and to the `tools=[...]` list in `run_agent()`.

## File Map

| File | Action |
|---|---|
| `app/tools.py` | Add `Glob`, `Grep` functions and `GLOB_TOOL`, `GREP_TOOL` schema dicts |
| `app/agent.py` | Import and register `GLOB_TOOL`, `GREP_TOOL` |
| `tests/test_tools.py` | Create — unit tests for Glob and Grep |

## Error Handling

- Non-existent `path` → return `"Error: path does not exist: <path>"`
- Invalid regex in `Grep` → return `"Error: invalid pattern: <msg>"`
- Binary files in `Grep` → silently skip (catch `UnicodeDecodeError`)
- Permission errors on individual files → silently skip

## Testing

**Glob:**
- Pattern matching files in a temp directory tree
- `**` recursive pattern finds nested files
- `.git/` and `.venv/` are excluded from results
- Results capped at 50; truncation message appears when over limit
- Non-existent path returns error string

**Grep:**
- Finds matching lines with correct `filepath:lineno: line` format
- `include` filter restricts to matching filenames
- `.git/` and `.venv/` are excluded
- Binary files are skipped silently
- Results capped at 100; truncation message appears when over limit
- Invalid regex returns error string

## Out of Scope

- Case-insensitive search flag
- Context lines before/after matches
- Symlink following
- Output modes (count-only, files-only)

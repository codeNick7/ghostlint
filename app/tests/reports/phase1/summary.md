# Phase 1 Test Report — 2026-07-09

## Testbeds
- VectorShift-Assignment: 28 files, 28 symbols, 0 findings, score 100/100
- AI-Assistant: 14 files, 16 symbols, 0 findings, score 100/100

## Bugs Found and Fixed

### Bug 1: decorated_definition not handled in Python parser
**Problem**: The Python parser's `_walk_definitions` did not handle `decorated_definition` AST nodes.
In tree-sitter Python grammar, functions decorated with `@decorator` are wrapped in a `decorated_definition`
parent node; the `function_definition` is a child. As a result, no decorated functions were parsed.

**Fix**: Added `decorated_definition` branch that collects decorators from the parent node and passes
them as `inherited_decorators` when recursing into the inner `function_definition` or `class_definition`.

## Findings Analysis
Both repos scored 100/100 with 0 findings. At Phase 1 only the dead code detector runs.
The repos are small and all functions are either route handlers, test functions, or actively used.

## Phase 1 Checklist
- [x] GitAnalyzer: is_git_repo, get_changed_files, get_changed_files_vs_branch, get_file_first_seen, get_file_commit_count
- [x] --changed flag in CLI, ScanConfig.changed_files in scanner
- [x] 32 unit tests across 5 test files — all pass
- [x] Bug fix: decorated_definition handling in Python parser
- [x] Phase 1 JSON scan reports saved for both testbeds

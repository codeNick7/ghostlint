# Phase 2 Test Report — All 9 Engines

**Date:** 2026-07-09  
**Engines active:** dead_code, duplicate_logic, refactor, arch_drift, config_health, doc_health, dependency_health, test_health, naming

## VectorShift-Assignment

| Metric | Value |
|---|---|
| Health Score | 99.7 / 100 |
| Files Scanned | 28 |
| Symbols Found | 28 |
| Total Findings | 1 |

| Engine | Findings |
|---|---|
| dependency_health | 1 |

*Verdict: Near-perfect score. One unused dependency detected. No dead code, duplicates, or architectural drift.*

---

## AI-Assistant

| Metric | Value |
|---|---|
| Health Score | 98.3 / 100 |
| Files Scanned | 14 |
| Symbols Found | 16 |
| Total Findings | 4 |

| Engine | Findings |
|---|---|
| dependency_health | 3 |
| duplicate_logic | 1 |

*Verdict: Very healthy codebase. Three unused dependencies and one structurally duplicate function pair detected.*

---

## Summary

All 9 engines ran successfully across both testbeds with no crashes or false positives. Both repos score above 98/100. The dependency_health and duplicate_logic engines produced the only findings — consistent with the clean, well-maintained state of both repositories.

# Product Requirements Document (PRD)

# Repository Health Intelligence Platform

Version: 0.1 (Foundational Vision)

---

> **Implementation Status (2026-07-15) — ghostlint v0.1 shipped**
>
> V1 Deliverables delivered:
> - **CLI** ✅ — `ghostlint scan`, `ghostlint report`, `ghostlint engines`, `ghostlint mcp setup`
> - **GitHub Action** ✅ — `github-action/` with score threshold + step summary
> - **Tree-sitter parser** ✅ — Python + JS/TS via tree-sitter
> - **Git history analyzer** ✅ — stability index, maintenance velocity, refactor completion, friction index
> - **Repository Health Score** ✅ — weighted 9-category score
> - **Cleanup recommendations** ✅ — ranked by effort/impact
> - **MCP server** ✅ — 19 tools (not in original V1 spec; shipped alongside CLI)
> - **HTML report** ✅ — self-contained, served on random localhost port with DNS-rebinding protection
>
> V1 Deliverables **not shipped** (deferred):
> - **Web dashboard (Next.js)** — superseded by HTML report; frontend directory removed
> - **FastAPI backend** — skeleton exists at `app/app/`; not a required runtime dependency
> - **PostgreSQL** — replaced by SQLite at `~/.ghostlint/ghostlint.db` for local-first operation

---

## Executive Summary

Repository Health Intelligence (working name) is a repository analysis
platform that helps engineering teams identify structural degradation,
incomplete refactors, obsolete code, duplicated logic, configuration
inconsistencies, architectural drift, and other maintainability issues
that accumulate over time.

Unlike static analyzers, linters, or security scanners, the platform
focuses on answering:

-   Why does this still exist?
-   What changed?
-   What became obsolete?
-   What is safe to remove?
-   What cleanup provides the highest return with the least risk?

The product is intended for senior engineers, staff engineers,
architects, CTOs and platform teams.

------------------------------------------------------------------------

# Problem Statement

Modern repositories evolve through:

-   rapid feature development
-   AI-assisted coding
-   multiple contributors
-   partial refactors
-   changing architectures
-   dependency upgrades

Traditional tooling validates correctness, formatting and security.

Very few tools continuously evaluate the long-term health of the
repository.

The result is gradual degradation:

-   duplicate implementations
-   obsolete abstractions
-   dead code
-   architectural drift
-   inconsistent naming
-   forgotten feature flags
-   stale documentation
-   conflicting configuration

The platform provides continuous repository health assessment.

------------------------------------------------------------------------

# Goals

1. Identify usual / regular patterns of AI code production for nonrelevent code. 
2. Become the "code cleaner" for every repository.
2.  Produce actionable insights rather than raw warnings.
3.  Explain reasoning behind every recommendation.
4.  Integrate naturally into developer workflows.
5. Integrate with AI Agentic workflow that makes this tool talk to any AI tool/ AI IDE. 
5.  Operate incrementally or full-repository.
6.  Support local execution and enterprise CI/CD.

Non-goals: - Replace linters. - Replace security scanners. - Replace
SAST tools. - Generate arbitrary code.

------------------------------------------------------------------------

# Primary Users

-   Principal Engineers
-   Staff Engineers
-   Software Architects
-   Platform Teams
-   CTOs
-   Engineering Managers
-   Open-source maintainers

------------------------------------------------------------------------

# Product Principles

-   Evidence over speculation.
-   Confidence score for every finding.
-   Explainability first.
-   Low false-positive rate.
-   Safe-by-default cleanup.
-   Language agnostic architecture.
-   Extensible rule engine.

------------------------------------------------------------------------

# Detection Engines

## Repository Structure

-   orphan directories
-   empty modules
-   abandoned packages

## Dead Code

-   unused symbols
-   unreachable branches
-   obsolete helpers
-   unused exports

## Duplicate Logic

-   AST similarity
-   semantic similarity
-   algorithm duplication
-   duplicated validation

## Refactor Completion

Detect: - coexistence of old/new APIs - wrapper layers never removed -
migration leftovers - deprecated modules still referenced

## Architectural Drift

-   boundary violations
-   cyclic dependencies
-   unexpected coupling
-   layer leakage

## Configuration Health

Compare: - .env - docker compose - kubernetes - terraform - application
configs

## Documentation Health

-   stale README
-   misleading comments
-   broken examples

## Dependency Health

-   unused packages
-   overlapping packages
-   outdated packages
-   duplicate libraries

## Test Health

-   orphan tests
-   obsolete snapshots
-   missing tests after refactor

## Naming Consistency

-   duplicate DTOs
-   inconsistent conventions
-   near-identical models

------------------------------------------------------------------------

# Analysis Pipeline

Repository → File Indexer → AST Parser → Symbol Graph → Dependency Graph
→ Git History → Semantic Embeddings → Rule Engine → LLM Reasoning →
Recommendation Engine → Health Report

------------------------------------------------------------------------

# Scanning Modes

## Full Scan

Entire repository.

## Incremental Scan

Only changed files plus dependency graph impact.

## Pull Request Scan

Changed files. Nearby dependencies. Impact analysis.

## Commit Scan

Fast execution for developer workflow.

## Scheduled Scan

Nightly or weekly organization-wide.

------------------------------------------------------------------------

# Integration Points

## Git Pre-commit Hook

Purpose: Prevent obvious health regressions.

Checks: - duplicated helpers - unreachable code - unused imports - stale
TODO explosion

Fast (\<10 sec target).

------------------------------------------------------------------------

## Pre-push Hook

Broader analysis including: - dependency changes - duplicate
implementations - architecture violations

------------------------------------------------------------------------

## Pull Request Reviews

Native GitHub/GitLab integration.

Bot comments: - findings - explanations - confidence - suggested
cleanup - optional patch

Only comment on newly introduced issues by default.

------------------------------------------------------------------------

## CI/CD Pipeline

Run after: - PR creation - merge - nightly - release candidate

Pipeline exits configurable: - advisory - warning - blocking

Health thresholds configurable.

------------------------------------------------------------------------

# Configurable Scan Scope

Support repository configuration file:

health.yml

Examples: - full repository - src only - changed files only - ignore
generated code - ignore vendor - ignore build output - ignore
migrations - ignore snapshots

Per-rule enable/disable.

Severity thresholds.

Confidence thresholds.

------------------------------------------------------------------------

# Recommendation Engine

Every finding contains:

Title

Description

Evidence

Files

Confidence

Risk

Estimated cleanup effort

Potential benefit

Optional autofix

------------------------------------------------------------------------

# Health Dashboard

Metrics: - Overall Repository Health - Cleanup Opportunity - Duplicate
Logic - Architectural Drift - Documentation Freshness - Dependency
Health - Test Health - Trend over time

Historical comparisons.

Release comparisons.

Team comparisons.

------------------------------------------------------------------------

# AI Usage

LLM responsibilities: - semantic reasoning - duplicate explanation -
migration detection - cleanup prioritization - report generation

Never rely exclusively on AI. Structural evidence always required.

------------------------------------------------------------------------

# Security

Local-first mode.

Enterprise offline mode.

No source upload required.

Optional cloud intelligence.

------------------------------------------------------------------------

# Extensibility

Plugin SDK: - language plugins - custom rules - organization policies -
framework adapters

Languages roadmap: Python TypeScript JavaScript Go Java C# Rust

------------------------------------------------------------------------

# API

REST + CLI.

CLI examples:

health scan health scan --changed health scan --pr health scan --full
health report health fix

------------------------------------------------------------------------

# GitHub Action

Example:

on: pull_request:

steps: - checkout - health scan --pr - upload report - comment findings

------------------------------------------------------------------------

# V1 Deliverables

-   CLI
-   GitHub Action
-   Web dashboard
-   FastAPI backend
-   Next.js frontend
-   PostgreSQL
-   Tree-sitter parser
-   Git history analyzer
-   Repository Health Score
-   Cleanup recommendations

------------------------------------------------------------------------

# V2

-   Autofix PR generation
-   Multi-repository analytics
-   Slack/Teams notifications
-   Jira ticket creation
-   Architectural trend prediction
-   Organization dashboards

------------------------------------------------------------------------

# Competitive Positioning

Not: - SonarQube replacement - ESLint replacement - Semgrep
replacement - CodeQL replacement

Instead:

Repository Health Intelligence sits above existing tooling, aggregating
structural, historical, semantic and architectural signals into a single
actionable health assessment.

It complements existing quality, security and linting tools rather than
replacing them.

------------------------------------------------------------------------

# Key Success Metrics

-   False positive rate
-   Accepted recommendations
-   Cleanup time saved
-   LOC safely removed
-   Duplicate logic eliminated
-   Repository health trend
-   Developer satisfaction
-   PR review time reduction

------------------------------------------------------------------------

# Strategic Recommendation

Do not market this initially as an "AI code reviewer."

Position it as an engineering platform.

Messaging: "Every repository deserves regular health check-ups."

That framing appeals to engineering leadership, scales beyond
AI-assisted coding, and remains relevant even as coding assistants
evolve.

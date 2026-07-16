# Repository Health Intelligence Platform (Working Specification)

> **Implementation Status (2026-07-15)** — Shipped as **ghostlint**. Technology stack differs from the spec below: no Next.js frontend (replaced by self-contained HTML report), no PostgreSQL/Redis (SQLite only), no LiteLLM/embeddings in the analysis loop (analysis is fully deterministic). MCP server with 19 tools was added beyond this original spec.

> **Working Goal**
>
> Build an AI-assisted engineering platform that continuously scans a
> software repository and identifies the hidden artifacts that naturally
> accumulate during iterative development---especially during
> AI-assisted coding, large refactors, rapid prototyping, and feature
> churn.

------------------------------------------------------------------------

# Vision

Modern software teams don't just accumulate technical debt.

They accumulate:

-   orphaned code
-   abandoned refactors
-   duplicated business logic
-   stale abstractions
-   obsolete helpers
-   conflicting implementations
-   forgotten feature flags
-   configuration drift
-   architectural drift

The platform should detect these automatically and explain **why they
exist**, **how they appeared**, and **what can safely be cleaned up**.

Unlike a linter, this tool understands the repository as a living
system.

------------------------------------------------------------------------

# Naming Direction

Avoid terms like **AI Slop** or **Entropy**.

Instead, explore names that communicate repository health and software
evolution.

Candidate concepts:

-   Repository Health Index
-   Code Health Intelligence
-   Repository Drift
-   Engineering Drift
-   Architectural Drift
-   Codebase Integrity
-   Repository Pulse
-   Repository Hygiene
-   Software Decay Index
-   Repository Signal
-   Code Evolution Insights
-   Project Health Score

The final name should feel suitable for engineering leaders, not just
social media.

------------------------------------------------------------------------

# Target Audience

-   Staff Engineers
-   Principal Engineers
-   Software Architects
-   CTOs
-   Engineering Managers
-   Platform Teams
-   AI-first software teams

------------------------------------------------------------------------

# Core Value Proposition

Instead of saying:

> "There are 43 issues."

The platform should say:

> "This repository contains several incomplete refactors, duplicated
> implementations, obsolete abstractions and unused assets that are safe
> to remove. Estimated cleanup effort: 6 hours."

The emphasis is actionable engineering insight.

------------------------------------------------------------------------

# Core Analysis Engine

The platform combines multiple signals.

## Static Analysis

-   AST parsing
-   Symbol resolution
-   Imports/exports
-   Call graph
-   Dependency graph

## Git History

-   File evolution
-   Rename detection
-   Deleted symbols
-   Commit frequency
-   Ownership

## Semantic Understanding

LLM-powered reasoning:

-   Was this code replaced?
-   Is this abstraction obsolete?
-   Is this helper duplicated elsewhere?
-   Does this comment still describe reality?

## Architecture Analysis

Detect

-   duplicated services
-   architectural drift
-   broken boundaries
-   cyclic dependencies
-   abandoned modules

------------------------------------------------------------------------

# Detection Categories

## Dead Code

-   unused functions
-   unreachable branches
-   obsolete utilities
-   abandoned helpers

------------------------------------------------------------------------

## Duplicate Logic

Detect semantically similar implementations.

Example

-   multiple debounce()
-   multiple date formatters
-   repeated validation logic

------------------------------------------------------------------------

## Incomplete Refactors

Identify situations like:

Old Service ↓

New Service

↓

Both coexist

↓

Old implementation still referenced

------------------------------------------------------------------------

## Configuration Drift

Compare

-   .env
-   Docker
-   Kubernetes
-   config files

Identify conflicting values.

------------------------------------------------------------------------

## Duplicate Models

Detect

UserDTO

UserResponse

UserData

with equivalent fields.

------------------------------------------------------------------------

## Feature Flag Cleanup

Detect

-   stale flags
-   unused toggles
-   permanently enabled features

------------------------------------------------------------------------

## Documentation Drift

Detect

-   comments contradicting implementation
-   outdated README sections
-   obsolete examples

------------------------------------------------------------------------

## Test Drift

Detect

-   orphan tests
-   missing tests
-   obsolete snapshots

------------------------------------------------------------------------

## Dependency Drift

Detect

-   unused packages
-   duplicate libraries
-   overlapping dependencies

------------------------------------------------------------------------

# AI-assisted Development Detection

The platform should avoid blaming AI.

Instead, identify repository patterns that frequently emerge during
iterative AI-assisted development.

Examples

-   duplicate helpers
-   temporary wrappers
-   abandoned utilities
-   repeated prompt-generated implementations
-   inconsistent naming
-   placeholder comments

Confidence should always be evidence-based.

------------------------------------------------------------------------

# Repository Health Dashboard

Display:

-   Overall Health Score
-   Cleanup Opportunity Score
-   Refactor Completion Score
-   Duplicate Logic Score
-   Architectural Drift Score
-   Configuration Consistency
-   Documentation Freshness
-   Dependency Health

Trend over time.

------------------------------------------------------------------------

# Cleanup Recommendations

Instead of warnings, generate tasks.

Example

✓ Remove helper_old.ts

✓ Merge duplicate DTOs

✓ Delete unreachable branch

✓ Consolidate duplicate validation logic

✓ Remove unused dependencies

Each recommendation includes:

-   confidence
-   impact
-   estimated effort
-   risk level

------------------------------------------------------------------------

# Pull Request Generation

Future capability.

Automatically generate cleanup PRs.

Every change should include:

-   explanation
-   affected files
-   rollback guidance
-   estimated impact

------------------------------------------------------------------------

# High-Level Architecture

Repository ↓

Repository Scanner

↓

AST Engine

↓

Dependency Graph

↓

Git History Analyzer

↓

Semantic Index

↓

LLM Reasoning Engine

↓

Health Intelligence Engine

↓

Recommendation Engine

↓

Dashboard + CLI + GitHub Action

------------------------------------------------------------------------

# Technology Stack

Frontend

-   Next.js
-   React
-   Tailwind CSS

Backend

-   Python
-   FastAPI

Analysis

-   Tree-sitter
-   GitPython
-   NetworkX

Storage

-   PostgreSQL
-   pgvector
-   Redis

AI

-   LiteLLM
-   OpenAI-compatible models
-   Local model support

Deployment

-   Docker
-   GitHub Actions
-   Vercel (UI)

------------------------------------------------------------------------

# Differentiation

Existing tools answer:

-   Is the code correct?
-   Is it secure?
-   Does it compile?

This platform answers:

-   Why does this code still exist?
-   What became obsolete?
-   What is safe to remove?
-   Where is the repository slowly diverging from its intended
    architecture?
-   What cleanup provides the greatest return with the least risk?

The goal is to become the **repository health platform** engineering
leaders consult before major releases and refactoring efforts.

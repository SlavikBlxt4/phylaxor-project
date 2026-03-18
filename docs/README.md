# Phylaxor Docs Map

This directory is the entry point for understanding the application repository.

## Start Here

If you are new to Phylaxor, read these files in order:

1. `PROJECT_CONTEXT.md`
2. `ARCHITECTURE.md`
3. `CONTRACT_ENV.md`
4. `SECURITY_MODEL.md`

That sequence gives you:
- what the product does
- how the runtime flow works
- how services are configured
- what security boundaries are non-negotiable

## Current Focus

The current codebase already includes:
- the full ingest -> enricher -> decision -> notifier pipeline
- feedback capture and dashboard
- logging modes (`none`, `loki`, `podlogs`) with conditional RBAC support in GitOps
- Brain Gateway integration for AI-generated recommendations

The main gaps are:
- Loki provider implementation
- end-to-end validation and operational hardening of the AI path
- continued deployment and docs cleanup

## Document Guide

Core:
- `PROJECT_CONTEXT.md`: current state, scope, priorities
- `ARCHITECTURE.md`: service flow and responsibilities
- `CONTRACT_ENV.md`: environment contract for services
- `SECURITY_MODEL.md`: RBAC and data-access boundaries

Operational:
- `LOGGING_MODES.md`: why logging is configurable and what each mode means
- `TEST_MATRIX.md`: validation scenarios and expected behavior
- `PHYLAXOR_DATABASE.md`: schema and data model reference

AI and decisioning:
- `ai_interaction_contract.md`: AI request/response contract
- `contracts/README.md`: schema files and examples
- `decision_confidence.md`: decision ranking model
- `fingerprint_and_history.md`: fingerprinting and history lookup background

Deferred design:
- `ADR-00X-history-outcomes.md`: post-MVP learning and outcomes ideas

# Project Context — Phylaxor

This is the canonical global context for the application repository.

## What Phylaxor Is

Phylaxor is a microservice-based incident-response assistant for Kubernetes and OpenShift.

Its runtime flow is:

1. ingest receives alerts from Alertmanager
2. enricher adds cluster context and optional log context
3. decision combines history, KB matches, and AI analysis
4. notifier sends the recommendation to Telegram
5. feedback services persist operator feedback in Postgres

The goal is to reduce MTTR with structured, context-aware guidance while keeping security boundaries tight.

## Where The Project Is Now

The current codebase already includes:
- end-to-end ingest/enrich/decide/notify flow
- feedback gateway and dashboard
- logging modes with graceful RBAC degradation
- GitOps support for conditional `pods/log` permissions
- Brain Gateway integration and structured AI request/response contracts

This means the project is no longer at the stage of “designing logging modes” or “planning conditional RBAC”. Those pieces exist already.

## What Is Stable

Stable and implemented:
- alert ingestion and deterministic fingerprinting
- cluster enrichment with events and pod metadata
- log provider abstraction with `none`, `loki`, and `podlogs`
- history lookup and KB matching in decision
- AI path via Brain Gateway
- Telegram notification with feedback buttons
- Helm deployment for Minikube and OpenShift
- validated end-to-end flow from alert ingestion to AI-backed Telegram notification
- validated end-to-end flow from real OpenShift Alertmanager delivery to AI-backed Telegram notification

Partially implemented or still pending:
- real Loki provider behavior
- network isolation and other hardening extras

## Main Repositories

- `phylaxor-project`: application code
- `phylaxor-gitops`: Helm charts, deployment values, RBAC, topology docs

## Architecture Summary

See `ARCHITECTURE.md` for the full version.

```text
Alertmanager
  -> ingest
  -> Redis(phylaxor_raw)
  -> enricher
  -> Redis(phylaxor_enriched)
  -> decision
     -> Postgres(history, KB, decisions, feedback)
     -> Brain Gateway
     -> notifier
     -> feedback-gateway / feedback UI
```

## Security Posture

These rules are still non-negotiable:

1. No Kubernetes Secret reads by default
2. Log access is explicit and mode-driven
3. RBAC denials must degrade gracefully, not break the pipeline
4. Notifier has no Kubernetes permissions
5. Minimum RBAC and separation of duties remain mandatory

See `SECURITY_MODEL.md` for the full boundary model.

## Target Environments

- Minikube for local and iterative development
- OpenShift CRC for strict-RBAC and enterprise-like validation

OpenShift remains the main security reference environment.

## Current Priorities

The documentation and code suggest the next meaningful priorities are:

1. keep the AI/Brain Gateway path documented and repeatably validated
2. implement the Loki provider behind `PHYLAXOR_LOGS_MODE=loki`
3. keep deployment docs aligned with actual behavior
4. continue hardening for OpenShift-style operation

## Reading Order

If you are new to the repo, read:

1. `README.md`
2. `docs/README.md`
3. `docs/PROJECT_CONTEXT.md`
4. `docs/ARCHITECTURE.md`
5. `docs/CONTRACT_ENV.md`
6. `docs/SECURITY_MODEL.md`

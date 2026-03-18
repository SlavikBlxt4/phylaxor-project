# Phylaxor Architecture

## Overview

Phylaxor is a microservice-based incident-response assistant for Kubernetes and OpenShift.

The platform combines three types of reasoning:
- cluster context from the enricher
- deterministic decisions from history and KB rules
- AI-generated analysis via Brain Gateway when needed

## Main Runtime Flow

```text
Alertmanager
  -> ingest
  -> Redis list: phylaxor_raw
  -> enricher
  -> Redis list: phylaxor_enriched
  -> decision
     -> Postgres
     -> Brain Gateway
     -> notifier
     -> feedback-gateway
     -> feedback UI
```

## Detailed Flow

```text
Alertmanager
  -> ingest
     - validates and normalizes incoming alerts
     - computes deterministic fingerprint
     - pushes event to phylaxor_raw

phylaxor_raw
  -> enricher
     - reads cluster and workload context
     - fetches events
     - fetches logs depending on mode:
       - none
       - loki
       - podlogs
     - degrades gracefully on RBAC failures
     - pushes event to phylaxor_enriched

phylaxor_enriched
  -> decision
     - checks history in Postgres
     - checks KB rules in Postgres
     - builds structured AIRequest when AI path is used
     - calls Brain Gateway
     - stores decision in Postgres
     - sends notification payload to notifier

notifier
  -> Telegram

feedback-gateway
  -> Postgres feedback table

feedback UI
  -> reads alerts, decisions, KB, and feedback from Postgres
```

## Components

### ingest

Responsibility:
- accept Alertmanager-style payloads
- normalize shape
- compute fingerprints
- queue raw events

Key dependencies:
- Redis

### enricher

Responsibility:
- attach cluster-wide and workload-specific context
- fetch recent events
- fetch logs according to `PHYLAXOR_LOGS_MODE`

Key dependencies:
- Redis
- Kubernetes API
- optional Loki endpoint in future

Important behavior:
- `pods/log` access is optional and mode-dependent
- RBAC denials must log warnings and continue

### decision

Responsibility:
- rank possible decision sources
- use history and KB first
- call Brain Gateway for structured AI analysis when applicable
- persist the selected decision

Key dependencies:
- Redis
- Postgres
- Brain Gateway
- notifier service

Decision sources:
- history
- KB
- AI
- fallback when AI is unavailable

### brain_gateway

Responsibility:
- validate AIRequest against schema
- call OpenAI
- normalize output
- validate AIResponse against schema before returning it

Key dependencies:
- OpenAI API
- JSON schemas from `docs/contracts`

### notifier

Responsibility:
- send the final recommendation to Telegram
- attach feedback buttons when a `decision_id` exists

Key constraint:
- no Kubernetes permissions

### feedback-gateway

Responsibility:
- receive Telegram callbacks
- store operator feedback in Postgres

### feedback

Responsibility:
- expose a lightweight dashboard
- browse alerts, decisions, KB items, matchers, and feedback

## Data Stores

Redis:
- `phylaxor_raw`
- `phylaxor_enriched`

Postgres:
- `alerts`
- `decisions`
- `feedback`
- `kb_items`
- `kb_matchers`

## Architectural Principles

### Queue-Based Decoupling

Redis decouples ingest, enrich, and decision stages so they can fail and restart independently.

### Explicit Logging Modes

The enricher must not assume log access. Log retrieval is a runtime choice and a security choice.

### AI Behind A Contract Boundary

The decision service does not call the model directly. It talks to Brain Gateway through a strict schema contract.

### Graceful Degradation

Missing logs, RBAC denials, or AI unavailability should reduce context quality, not stop the pipeline.

### Separation Of Duties

Cluster-aware services and Internet-facing services remain separated on purpose.

## Related Documents

- `PROJECT_CONTEXT.md`
- `CONTRACT_ENV.md`
- `SECURITY_MODEL.md`
- `LOGGING_MODES.md`
- `TEST_MATRIX.md`
- `ai_interaction_contract.md`
